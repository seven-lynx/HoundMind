"""Step odometry: a pose from the heading plus the moves the gateway actually issued.

The dog has no wheel encoders. What it does have is a heading (`navigation/orientation.py`) and a
record of every motion the gateway accepted *and issued* (`act/gateway.py` publishes
`motion_command` once per new command, carrying a `seq` that increments). So distance is
`steps x step_cm`, and the pose is that distance walked along the heading.

`step_cm` is a calibrated guess, not a measurement - `navigation/place_navigator.py` says the same
about its own counting - so this pose is only as good as that constant and gets worse with every
step. `navigation/localization.py` treats it as the middle tier and expires it accordingly; nothing
here claims to be SLAM.

Publishes `odometry`::

    {"ts": float, "steps": int, "distance_cm": float, "travelled_cm": float,
     "x_cm": float, "y_cm": float, "yaw_deg": float, "pose_valid": bool,
     "reason": str | None}

Convention: `x` is forward at heading 0, `y` is to the left, and `yaw_deg` is the heading. That
matches the scan yaw `mapping/mapper.py` records (0 = forward, positive = left,
`place_navigator.py:104`).

Set `odometry_reset` in the context to re-anchor the pose at the origin, which is what a taught
place or a fresh SLAM fix does.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)

__all__ = [
    "LINEAR_ACTIONS",
    "DEFAULT_STEP_CM",
    "OdometryModule",
    "StepScale",
    "resolve_step_cm",
]

#: The two actions that advance the dog along its own heading.
LINEAR_ACTIONS = ("forward", "backward")

#: Assumed stride in centimetres. A guess until someone measures it; see the module docstring.
DEFAULT_STEP_CM = 25.0


@dataclass(frozen=True)
class StepScale:
    """The centimetres one gait cycle is believed to carry, and where that number came from.

    `source` is `"assumed"` or `"measured:<surface>"`, and it is published rather than kept private:
    a pose built on a guess and a pose built on a measured constant look identical otherwise, and
    every place anchor inherits whichever one was in force when it was taught.
    """

    cm: float
    source: str
    surface: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "step_cm": round(self.cm, 3),
            "step_cm_source": self.source,
            "surface": self.surface,
        }


def resolve_step_cm(settings: Mapping[str, Any]) -> StepScale:
    """Pick the stride: a measured per-surface value when one exists, else `step_cm`.

    A surface that has no entry - or one that is zero, negative or junk - falls back to `step_cm`
    and says `assumed`. Silently treating a missing entry as 0 cm would collapse every distance
    the map holds, so the fallback is the loud path, not the quiet one.
    """
    assumed = _safe_float(settings.get("step_cm"), DEFAULT_STEP_CM)
    if assumed <= 0 or not math.isfinite(assumed):
        assumed = DEFAULT_STEP_CM

    raw_surface = settings.get("surface")
    surface = (
        raw_surface.strip()
        if isinstance(raw_surface, str) and raw_surface.strip()
        else None
    )
    table = settings.get("surface_step_cm")
    if surface is not None and isinstance(table, Mapping):
        measured = _safe_float(table.get(surface), 0.0)
        if measured > 0:
            return StepScale(cm=measured, source=f"measured:{surface}", surface=surface)
    return StepScale(cm=assumed, source="assumed", surface=surface)



def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


class OdometryModule(Module):
    """Integrate executed linear moves into a relative pose.

    An observer: it reads `motion_command` and `current_heading` and publishes `odometry`. It
    never publishes intent and never touches the HAL, so it cannot move the dog.
    """

    def __init__(
        self, name: str, enabled: bool = True, required: bool = False, **kwargs: object
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_seq: int | None = None
        self._steps = 0
        self._distance_cm = 0.0
        self._travelled_cm = 0.0
        self._x_cm = 0.0
        self._y_cm = 0.0
        self._reason: str | None = None

    def reset(self) -> None:
        """Re-anchor the pose at the origin, keeping the counters' meaning for the next window."""
        self._steps = 0
        self._distance_cm = 0.0
        self._travelled_cm = 0.0
        self._x_cm = 0.0
        self._y_cm = 0.0
        self._reason = None

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("odometry", {}) or {}
        scale = resolve_step_cm(settings)
        step_cm = scale.cm
        track_backward = bool(settings.get("track_backward", True))

        if context.get("odometry_reset"):
            self.reset()

        command = context.get("motion_command")
        if isinstance(command, dict):
            self._consume(command, context, step_cm, track_backward)

        self._publish(context, scale)

    def _consume(self, command: dict, context, step_cm: float, track_backward: bool) -> None:
        """Count one step per *issued* command.

        `act/gateway.py` re-keeps a repeated intent without republishing it, so the published
        `motion_command` only changes when the gateway really issued something. `seq` makes that
        explicit: a command without one cannot be counted without guessing, so it is not.
        """
        seq = _safe_int(command.get("seq"), -1)
        if seq < 0:
            self._reason = "motion_command carries no seq"
            return
        if seq == self._last_seq:
            return
        self._last_seq = seq

        action = str(command.get("canonical_action") or command.get("action") or "")
        if action not in LINEAR_ACTIONS:
            return
        signed = -1.0 if action == "backward" else 1.0
        if action == "backward" and not track_backward:
            return

        self._steps += 1
        self._distance_cm += signed * step_cm
        self._travelled_cm += abs(step_cm)

        heading = context.get("current_heading")
        if heading is None:
            # Steps without a heading cannot be placed: the distance is real, the pose is not.
            self._reason = "no heading for this step"
            return
        yaw = math.radians(_safe_float(heading, 0.0))
        self._x_cm += signed * step_cm * math.cos(yaw)
        self._y_cm += signed * step_cm * math.sin(yaw)

    def _publish(self, context, scale: StepScale) -> None:
        heading = context.get("current_heading")
        pose_valid = self._reason is None and heading is not None
        context.set(
            "odometry",
            {
                "ts": time.time(),
                "steps": self._steps,
                "distance_cm": round(self._distance_cm, 3),
                "travelled_cm": round(self._travelled_cm, 3),
                "x_cm": round(self._x_cm, 3),
                "y_cm": round(self._y_cm, 3),
                "yaw_deg": round(_safe_float(heading, 0.0), 3),
                "pose_valid": pose_valid,
                "reason": self._reason,
                # Which constant built those numbers, and whether anyone measured it (L3.2).
                **scale.to_dict(),
            },
        )
