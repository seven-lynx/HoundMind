"""The mandatory interlock.

Safety is not a module here. It is the last thing every command passes through before it
reaches a servo, and it cannot be disabled from configuration. Every refusal returns a
reason: a silent refusal is a bug, because the operator then has no way to know why the dog
did not move.

Checks, in order:

1. ``stop`` is always accepted — the escape hatch can never be vetoed.
2. Unknown action → refused.
3. Past its TTL → refused (deadman).
4. Tilt beyond the latch threshold → motion refused until cleared.
5. Low battery → motion refused.
6. Last *valid* distance at or below the emergency distance → forward motion refused.
7. Speed clamped to the board limit.

Obstacle and tilt checks use validity flags, so a broken sensor cannot veto motion forever
and a stale good value cannot authorise it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from houndmind_ai.hal.iface import SensorSnapshot, as_int
from houndmind_ai.kernel.commands import (
    FORWARD_ACTIONS,
    KNOWN_ACTIONS,
    MOTION_ACTIONS,
    Command,
    Verdict,
)

__all__ = ["Interlock", "InterlockLimits"]


@dataclass(frozen=True)
class InterlockLimits:
    """Per-board safety envelope. Loaded from the board profile, never from user config."""

    max_speed: int = 200
    emergency_stop_cm: float = 12.0
    tilt_latch_deg: float = 45.0
    min_battery_v: float = 6.4


class Interlock:
    def __init__(
        self,
        limits: InterlockLimits | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.limits = limits or InterlockLimits()
        self._now = now or time.monotonic
        self._tilt_latched = False
        self._clamp_reported = False

    # ---- state -------------------------------------------------------------

    @property
    def tilt_latched(self) -> bool:
        return self._tilt_latched

    def clear_tilt(self) -> None:
        """A human has confirmed the dog is upright again."""
        self._tilt_latched = False

    # ---- evaluation --------------------------------------------------------

    def evaluate(self, command: Command, snapshot: SensorSnapshot) -> Verdict:
        action = command.action
        params = dict(command.params)

        if action == "stop":
            return Verdict(accepted=True, action=action, params=params)

        if action not in KNOWN_ACTIONS:
            return Verdict(
                accepted=False,
                action=action,
                params=params,
                veto="unknown_action",
                detail=f"'{action}' is not in the action catalog",
            )

        now = self._now()
        if command.expired(now):
            return Verdict(
                accepted=False,
                action=action,
                params=params,
                veto="expired",
                detail=f"command exceeded its {command.ttl_ms} ms deadman",
            )

        is_motion = action in MOTION_ACTIONS
        if not is_motion:
            return Verdict(accepted=True, action=action, params=params)

        # Tilt latch. Evaluated from a valid IMU only; an invalid IMU neither latches nor
        # clears, so a flaky sensor cannot silently authorise motion.
        if snapshot.tilted:
            pitch = abs(snapshot.pitch_deg or 0.0)
            roll = abs(snapshot.roll_deg or 0.0)
            if max(pitch, roll) >= self.limits.tilt_latch_deg:
                self._tilt_latched = True
        if self._tilt_latched:
            return Verdict(
                accepted=False,
                action=action,
                params=params,
                veto="tilt",
                detail="dog is tilted; right it and clear the latch",
            )

        if (
            snapshot.battery_valid
            and snapshot.battery_v is not None
            and snapshot.battery_v < self.limits.min_battery_v
        ):
            return Verdict(
                accepted=False,
                action=action,
                params=params,
                veto="low_voltage",
                detail=f"{snapshot.battery_v:.2f} V below {self.limits.min_battery_v:.2f} V",
            )

        if action in FORWARD_ACTIONS and snapshot.distance_valid:
            distance = snapshot.distance_cm
            if distance is not None and 0 < distance <= self.limits.emergency_stop_cm:
                return Verdict(
                    accepted=False,
                    action=action,
                    params=params,
                    veto="obstacle",
                    detail=f"{distance:.1f} cm at sensor (limit {self.limits.emergency_stop_cm:.1f} cm)",
                )

        return self._clamp(action, params)

    def _clamp(self, action: str, params: dict[str, object]) -> Verdict:
        if "speed" not in params:
            return Verdict(accepted=True, action=action, params=params)

        raw = params.get("speed")
        requested = as_int(raw, self.limits.max_speed)
        clamped = max(0, min(requested, self.limits.max_speed))
        # Rewrite the value when it was clamped *or* when it was not an int to begin with,
        # so a junk value ("fast") can never reach the servo bus.
        needs_rewrite = clamped != requested or not isinstance(raw, int) or isinstance(raw, bool)
        if not needs_rewrite:
            return Verdict(accepted=True, action=action, params=params)

        clamped_params = dict(params)
        clamped_params["speed"] = clamped
        detail = None
        if clamped != requested and not self._clamp_reported:
            # Report a genuine clamp once per session so the log is not flooded at tick rate.
            self._clamp_reported = True
            detail = f"speed clamped {requested} -> {clamped}"
        return Verdict(accepted=True, action=action, params=clamped_params, detail=detail)