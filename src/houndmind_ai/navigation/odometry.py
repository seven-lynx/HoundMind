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
    "AUDIT_MAX_CM",
    "AUDIT_MIN_CHANGE_CM",
    "AUDIT_TIMEOUT_S",
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



#: The audit only believes a reading this close: beyond it the sonar's own error is larger than a
#: gait cycle, so a "measurement" would be noise with a decimal point (#300).
AUDIT_MAX_CM = 250.0
#: A step is audited against the next reading that differs by at least this much; anything smaller is
#: the same echo, and the reading has not caught up with the step yet.
AUDIT_MIN_CHANGE_CM = 0.5
#: How long a pending step waits for that reading before it is dropped. Three seconds covers a gait
#: cycle plus a sensor tick; past that the distance is no longer evidence about *this* step.
AUDIT_TIMEOUT_S = 3.0


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _distance(context) -> tuple[float | None, bool]:
    """The sonar reading and its validity flag, from the `SensorReading` the sensor module sets.

    Validity is checked before the value, always: a failed read that happens to remember the last
    number is not evidence, and the audit exists to compare a predicted step with a real one.
    """
    reading = context.get("sensor_reading")
    if reading is None:
        return None, False
    distance = getattr(reading, "distance_cm", None)
    valid = bool(getattr(reading, "distance_valid", False))
    if distance is None:
        return None, False
    return _safe_float(distance, -1.0), valid


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
        # The range-aided audit (#300): the step being watched, and the last record it produced.
        self._audit_pending: dict[str, Any] | None = None
        self._audit: dict[str, Any] | None = None
        self._clock = time.time

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
        track_backward = bool(settings.get("track_backward", True))

        if context.get("odometry_reset"):
            self.reset()

        # Close the previous step's audit before consuming this one, so a reading that arrived
        # between ticks is credited to the step it belongs to.
        self._close_audit(context)

        command = context.get("motion_command")
        if isinstance(command, dict):
            self._consume(command, context, scale, track_backward)

        self._publish(context, scale)

    def _consume(
        self, command: dict, context, scale: StepScale, track_backward: bool
    ) -> None:
        """Count one step per *issued* command.

        `act/gateway.py` re-keeps a repeated intent without republishing it, so the published
        `motion_command` only changes when the gateway really issued something. `seq` makes that
        explicit: a command without one cannot be counted without guessing, so it is not.
        """
        step_cm = scale.cm
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
        # Only a forward step closes on a wall, and only that gives the sonar a distance to compare
        # against. The audit is opened before the heading check: the step happened either way.
        if signed > 0:
            self._open_audit(context, scale, step_cm)

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
                # The last ranged comparison, or None until a step closed on a wall (#300). It is
                # logged, never applied: the constant changes only through `step_calibrate --apply`.
                "audit": self._audit,
            },
        )

    def _open_audit(self, context, scale: StepScale, predicted_cm: float) -> None:
        """Watch this step against the next distance reading, if one can testify to it."""
        distance, valid = _distance(context)
        if not valid or distance is None or not 0.0 < distance <= AUDIT_MAX_CM:
            self._audit_pending = None
            return
        self._audit_pending = {
            "predicted_cm": abs(predicted_cm),
            "before_cm": float(distance),
            "surface": scale.surface,
            "step_cm_source": scale.source,
            "deadline": self._clock() + AUDIT_TIMEOUT_S,
        }

    def _close_audit(self, context) -> None:
        """Turn a pending step into a record once a new reading exists, or drop it with a reason.

        Nothing here changes a constant. The record is evidence a human (or `--apply`) reads, and a
        step whose reading never moved is dropped rather than recorded as zero travel: a blocked
        gait and a missed echo are not measurements of a stride.
        """
        pending = self._audit_pending
        if pending is None:
            return
        distance, valid = _distance(context)
        if self._clock() > pending["deadline"]:
            self._audit_pending = None
            return
        if not valid or distance is None or not 0.0 < distance <= AUDIT_MAX_CM:
            self._audit_pending = None
            return
        travelled = pending["before_cm"] - float(distance)
        if travelled < AUDIT_MIN_CHANGE_CM:
            return  # the reading has not caught up (or the step was refused); keep waiting
        self._audit_pending = None
        predicted = pending["predicted_cm"]
        self._audit = {
            "ts": time.time(),
            "surface": pending["surface"],
            "step_cm_source": pending["step_cm_source"],
            "predicted_cm": round(predicted, 2),
            "actual_cm": round(travelled, 2),
            "ratio": round(travelled / predicted, 3) if predicted > 0 else None,
        }
