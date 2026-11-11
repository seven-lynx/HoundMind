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
here — one place, not four. The control plane is the exception: it submits a ``Command`` on the
:class:`~houndmind_ai.kernel.commands.CommandBus` and expects a ``Verdict`` back, so a client is
told the truth about its own request instead of a guess. The legacy adapter is deleted in Phase 3,
when behaviour, navigation and safety are ported onto typed commands.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from houndmind_ai.act.interlock import Interlock
from houndmind_ai.core.module import Module
from houndmind_ai.hal.iface import SensorSnapshot, as_float
from houndmind_ai.kernel.commands import (
    DEFAULT_MODE,
    MOTION_ACTIONS,
    RUNTIME_MODES,
    Command,
    CommandBus,
    Source,
    Verdict,
)

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
        bus: CommandBus | None = None,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._clock = clock or time.monotonic
        self.interlock = interlock or Interlock(now=self._clock)
        # The control plane's inbox. None means "no client can drive this dog", which is the
        # state of every test that drives the gateway through the legacy keys alone.
        self.bus = bus
        self._last_key: tuple[str, Source] | None = None
        self._last_verdict: Verdict | None = None

    def tick(self, context) -> None:
        now = self._clock()
        snapshot = self._snapshot(context)
        winner, verdict = self._resolve(context, now, snapshot)

        if winner is None or verdict is None:
            # Nobody is asking for anything. Publishing None rather than leaving a stale
            # command in place is what makes the deadman real: a producer that dies stops the
            # dog on the next tick instead of leaving it walking.
            self._last_key = None
            self._last_verdict = None
            self._publish(context, None, None)
            context.set("tilt_latched", self.interlock.tilt_latched)
            return

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

    def _resolve(
        self, context, now: float, snapshot: SensorSnapshot
    ) -> tuple[Command | None, Verdict | None]:
        """Pick one winner and return it with its verdict.

        Two sources feed this: the legacy context keys (re-stamped every tick) and the
        :class:`CommandBus` (stamped once, with a real deadman). A bus command is judged and
        acknowledged individually, so every client learns the fate of its *own* request even
        when a higher-priority producer wins the tick.
        """
        best: Command | None = None
        best_rank: tuple[int, int] | None = None
        verdicts: dict[str, Verdict] = {}

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
            rank = (int(source), 0)
            if best_rank is None or rank > best_rank:
                best, best_rank = command, rank

        for command in self._drain_bus():
            verdict = self._vet(command, snapshot, context)
            verdicts[command.id] = verdict
            # Ack before deciding the winner: a refusal is information the client asked for.
            if self.bus is not None:
                self.bus.acknowledge(command, verdict)
            if not verdict.accepted:
                continue
            rank = (int(command.source), 1)
            if best_rank is None or rank > best_rank:
                best, best_rank = command, rank

        if best is None:
            return None, None
        return best, verdicts.get(best.id) or self._vet(best, snapshot, context)

    def _drain_bus(self) -> list[Command]:
        if self.bus is None:
            return []
        return self.bus.drain()

    def _vet(self, command: Command, snapshot: SensorSnapshot, context) -> Verdict:
        # A client cannot drive a dog that has been put to rest. The interlock has no notion of
        # mode (it is a safety envelope, not a policy), so the refusal lives here, next to the
        # other precedence rules, and it is reported like any other veto.
        if command.source is Source.CLIENT and _mode_name(context) == "rest":
            return Verdict(
                accepted=False,
                action=command.action,
                params=dict(command.params),
                veto="mode",
                detail="the dog is in rest mode; switch to manual to drive it",
            )
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


def _mode_name(context) -> str:
    """The mode a client selected, or the default when nothing sane is set."""
    mode = context.get("runtime_mode")
    return mode if isinstance(mode, str) and mode in RUNTIME_MODES else DEFAULT_MODE


def _opt_float(value: Any) -> float | None:
    """None-preserving coercion: absent stays absent, it never becomes 0.0."""
    if value is None or value == "":
        return None
    number = as_float(value, float("nan"))
    return None if number != number else number