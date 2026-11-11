"""The single path a motion request takes on its way to a servo.

`MotorModule` used to pick its action with

    context.get("safety_action") or context.get("watchdog_action") \\
        or context.get("navigation_action") or context.get("behavior_action")

and then deduplicate on the action *string*. Two bugs came straight out of that:

- Precedence was implicit. `safety/supervisor.py` carried a `priority_map` describing the same
  order, and the two had to stay in sync by hand.
- A `forward` from navigation and a `forward` from behaviour were the same string, so the
  second was silently dropped.

The gateway resolves one winner per tick, sends it through the :class:`Interlock`, and
publishes the outcome under `motion_command` / `motion_verdict`. Motors executes what the
gateway decided; it no longer decides.

Transitional note: producers still write their legacy context keys, so this module adapts them
here — one place, not four. When the control API lands, clients submit a ``Command`` directly
and the adapter is deleted.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from houndmind_ai.act.interlock import Interlock
from houndmind_ai.core.module import Module
from houndmind_ai.hal.iface import SensorSnapshot, as_float
from houndmind_ai.kernel.commands import MOTION_ACTIONS, Command, Source, Verdict

logger = logging.getLogger(__name__)

__all__ = ["MotionGatewayModule"]

# Legacy producers spell motion with spaces; the command vocabulary uses underscores.
# These are *aliases only*: the canonical spelling is always the underscore form, so the
# inverse map below must not contain an entry for a canonical name.
_TO_CANONICAL = {
    "turn left": "turn_left",
    "turn right": "turn_right",
}
_TO_LEGACY = {canonical: legacy for legacy, canonical in _TO_CANONICAL.items()}

# Legacy key → who is asking. This is the precedence order that used to live in the `or` chain.
_LEGACY_SOURCES: tuple[tuple[str, Source], ...] = (
    ("safety_action", Source.SYSTEM),
    ("watchdog_action", Source.WATCHDOG),
    ("navigation_action", Source.NAVIGATION),
    ("behavior_action", Source.BEHAVIOUR),
)


def canonical_action(action: str) -> str:
    key = action.strip().lower()
    return _TO_CANONICAL.get(key, key.replace(" ", "_"))


def legacy_action(action: str) -> str:
    """The spelling `pidog.ActionFlow` accepts."""
    return _TO_LEGACY.get(action, action.replace("_", " "))


class MotionGatewayModule(Module):
    """Resolves competing motion intents into one interlock-approved command per tick."""

    def __init__(
        self,
        name: str,
        enabled: bool = True,
        required: bool = False,
        interlock: Interlock | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._clock = clock or time.monotonic
        self.interlock = interlock or Interlock(now=self._clock)
        self._last_key: tuple[str, Source] | None = None
        self._last_verdict: Verdict | None = None

    def tick(self, context) -> None:
        now = self._clock()
        snapshot = self._snapshot(context)
        winner = self._resolve(context, now)

        if winner is None:
            # Nobody is asking for anything. Publishing None rather than leaving a stale
            # command in place is what makes the deadman real: a producer that dies stops the
            # dog on the next tick instead of leaving it walking.
            self._last_key = None
            self._last_verdict = None
            self._publish(context, None, None)
            context.set("tilt_latched", self.interlock.tilt_latched)
            return

        verdict = self._vet(winner, snapshot)

        if not verdict.accepted:
            self._last_key = None
            self._last_verdict = verdict
            self._publish(context, None, verdict)
            # Publish the latch *after* evaluation: the veto above may have just set it.
            context.set("tilt_latched", self.interlock.tilt_latched)
            return

        key = (winner.action, winner.source)
        if key == self._last_key:
            # Same intent as last tick: keep the verdict visible but do not re-issue, or the
            # motor cooldown is bypassed and the action queue floods.
            context.set("motion_verdict", verdict.to_dict())
            context.set("tilt_latched", self.interlock.tilt_latched)
            return
        self._last_key = key
        self._last_verdict = verdict
        self._publish(context, winner, verdict)
        context.set("tilt_latched", self.interlock.tilt_latched)

    def _publish(self, context, command: Command | None, verdict: Verdict | None) -> None:
        if command is None:
            context.set("motion_command", None)
        else:
            payload = command.to_dict()
            # Hand motors the spelling pidog understands; keep the canonical one for readers.
            payload["action"] = legacy_action(command.action)
            payload["canonical_action"] = command.action
            context.set("motion_command", payload)
        context.set("motion_verdict", verdict.to_dict() if verdict is not None else None)

    def _resolve(self, context, now: float) -> Command | None:
        best: Command | None = None
        for key, source in _LEGACY_SOURCES:
            raw = context.get(key)
            if not raw:
                continue
            command = Command(
                action=canonical_action(str(raw)),
                source=source,
                # Legacy producers express intent by *value*, not by heartbeat: the key holds
                # whatever they last wanted. Stamping it now keeps the command live while the
                # value stands; the deadman governs submitted commands (API, clients).
                issued_at=now,
            )
            if best is None or command.source > best.source:
                best = command
        return best

    def _vet(self, command: Command, snapshot: SensorSnapshot) -> Verdict:
        if command.action not in MOTION_ACTIONS:
            # Posture and expression are not gated. The authoritative action list belongs to
            # the HAL (`actions()`); refusing unknown names here would break the dog's
            # repertoire for every action this module has not been taught about.
            return Verdict(accepted=True, action=command.action, params=dict(command.params))
        return self.interlock.evaluate(command, snapshot)

    @staticmethod
    def _snapshot(context) -> SensorSnapshot:
        """Best-effort snapshot from the context keys the runtime already publishes."""
        reading = context.get("sensor_reading")
        tilt = context.get("tilt_warning")
        battery = context.get("battery_voltage")

        pitch = roll = None
        imu_valid = False
        if isinstance(tilt, dict):
            pitch = _opt_float(tilt.get("pitch"))
            roll = _opt_float(tilt.get("roll"))
            imu_valid = pitch is not None and roll is not None

        battery_v = _opt_float(battery)
        return SensorSnapshot(
            ts=as_float(getattr(reading, "timestamp", None), 0.0),
            distance_cm=_opt_float(getattr(reading, "distance_cm", None)),
            distance_valid=bool(getattr(reading, "distance_valid", False)),
            touch=str(getattr(reading, "touch", "N")),
            touch_valid=bool(getattr(reading, "touch_valid", False)),
            pitch_deg=pitch,
            roll_deg=roll,
            imu_valid=imu_valid,
            battery_v=battery_v,
            battery_valid=battery_v is not None,
        )


def _opt_float(value: Any) -> float | None:
    """None-preserving coercion: absent stays absent, it never becomes 0.0."""
    if value is None or value == "":
        return None
    number = as_float(value, float("nan"))
    return None if number != number else number