"""The single path a motion request takes on its way to a servo.

`MotorModule` used to pick its action with

    context.get("safety_action") or context.get("watchdog_action") \\
        or context.get("navigation_action") or context.get("behavior_action")

and then deduplicate on the action *string*. Three bugs came straight out of that:

- Precedence was implicit. `safety/supervisor.py` carried a `priority_map` describing the same
  order, and the two had to stay in sync by hand.
- A `forward` from navigation and a `forward` from behaviour were the same string, so the
  second was silently dropped.
- The intent never expired. Whatever was in those keys was re-stamped with the current tick's
  timestamp, so a producer that wedged kept the dog walking: the deadman only ever protected
  clients.

The gateway now reads one winner per tick from the :class:`~houndmind_ai.kernel.intents.IntentBoard`
(internal producers, expiring unless refreshed) and from the
:class:`~houndmind_ai.kernel.commands.CommandBus` (clients, with a per-command verdict), applies
the mode policy, sends the winner through the :class:`Interlock`, and publishes the outcome under
`motion_command` / `motion_verdict` / `motion_cancel`. Motors executes what the gateway decided;
it no longer decides.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from houndmind_ai.act.interlock import Interlock
from houndmind_ai.core.module import Module
from houndmind_ai.hal.iface import SensorSnapshot, as_float
from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.commands import (
    DEFAULT_MODE,
    RUNTIME_MODES,
    Command,
    CommandBus,
    Source,
    Verdict,
    canonical_action,
    legacy_action,
    mode_allows,
)
from houndmind_ai.kernel.intents import IntentBoard

logger = logging.getLogger(__name__)

# `canonical_action` / `legacy_action` live in `kernel/commands.py` now, next to the action
# vocabulary they translate. Re-exported because this module was their only home until Phase 3.
__all__ = ["MotionGatewayModule", "canonical_action", "legacy_action"]

# Why a mode refused a request. A refusal without a reason is a bug: the operator is left
# guessing whether the dog is broken or simply parked.
_MODE_DETAIL = {
    "rest": "the dog is in rest mode; switch to manual to drive it",
    "manual": "the dog is in manual mode; autonomy is off until you switch back to idle",
}


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
        board: IntentBoard | None = None,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._clock = clock or time.monotonic
        self.interlock = interlock or Interlock(now=self._clock)
        # The control plane's inbox. None means "no client can drive this dog".
        self.bus = bus
        # The internal producers' notice board. Created here when a caller does not inject one,
        # so a gateway built on its own still works; `main.build_registry` lets it default.
        self.board = board or IntentBoard(clock=self._clock)
        self._last_key: tuple[str, Source, tuple[tuple[str, str], ...]] | None = None
        self._last_verdict: Verdict | None = None
        self._last_cancelled: frozenset[tuple[str, Source]] = frozenset()

    def start(self, context) -> None:
        # Producing modules find the board through the context, so that not one constructor has
        # to grow a parameter. Publication happens at start, which is before any producer's
        # first tick because the gateway is registered ahead of them.
        context.set("intent_board", self.board)
        # The classification the interlock judges with, read once: it is data in
        # `config/actions.jsonc`, so it cannot be a value this module hard-codes.
        self.interlock.set_repertoire(repertoire_from_settings(context.get("settings")))
        super().start(context)

    def stop(self, context) -> None:
        context.set("intent_board", None)
        super().stop(context)

    def tick(self, context) -> None:
        now = self._clock()
        snapshot = self._snapshot(context)
        winner, verdict, cancelled = self._resolve(context, now, snapshot)
        self._publish_cancellations(context, cancelled)

        if winner is None or verdict is None:
            # Nobody is asking for anything. Publishing None rather than leaving a stale
            # command in place is what makes the deadman real: a producer that stops refreshing
            # its intent, or dies, stops the dog on the next tick instead of leaving it walking.
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

        key = (winner.action, winner.source, _params_key(winner.params))
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
    ) -> tuple[Command | None, Verdict | None, list[Command]]:
        """Pick one winner, return it with its verdict, and list what it displaced.

        Two sources feed this. The :class:`IntentBoard` holds internal intents (behaviour,
        navigation, watchdog, system): latest value per source, expiring unless refreshed. The
        :class:`CommandBus` holds client commands: stamped once, with a real deadman, and judged
        and acknowledged individually so every client learns the fate of its *own* request even
        when a higher-priority producer wins the tick.

        The mode gate is applied to both before ranking, because a mode is a statement about the
        whole machine, not a veto the interlock should have to express (it is a safety envelope,
        not a policy).
        """
        mode = _mode_name(context)
        candidates: list[tuple[tuple[int, int], Command]] = []
        verdicts: dict[str, Verdict] = {}

        for command in self.board.latest(now):
            # `stop` passes the mode gate like it passes the interlock: it is how a motion ends.
            if command.action != "stop" and not mode_allows(mode, command.source):
                continue
            candidates.append(((int(command.source), 0), command))

        for command in self._drain_bus():
            verdict = self._vet(command, snapshot, mode)
            verdicts[command.id] = verdict
            # Ack before deciding the winner: a refusal is information the client asked for.
            if self.bus is not None:
                self.bus.acknowledge(command, verdict)
            if not verdict.accepted:
                continue
            candidates.append(((int(command.source), 1), command))

        if not candidates:
            return None, None, []

        # A `stop` outranks every other intent, whatever its source. It is the one action that
        # exists to end motion, so a supervisor's stop must not lose a tick to a safety retreat
        # merely because safety has a higher `Source`. Ties keep production order.
        candidates.sort(key=lambda item: (item[1].action == "stop", item[0]))
        _, best = candidates[-1]
        # Anything a different action displaced this tick. Reported rather than silently
        # dropped: "the dog ignored me" is the question this answers.
        cancelled = [other for _, other in candidates[:-1] if other.action != best.action]
        return best, verdicts.get(best.id) or self._vet(best, snapshot, mode), cancelled

    def _publish_cancellations(self, context, cancelled: list[Command]) -> None:
        payload = [command.to_dict() for command in cancelled]
        context.set("motion_cancel", payload)
        signature = frozenset((command.action, command.source) for command in cancelled)
        if signature != self._last_cancelled:
            self._last_cancelled = signature
            if signature:
                logger.info(
                    "Precedence displaced: %s",
                    ", ".join(
                        f"{action} from {source.name.lower()}"
                        for action, source in sorted(signature, key=lambda item: item[1])
                    ),
                )

    def _drain_bus(self) -> list[Command]:
        if self.bus is None:
            return []
        return self.bus.drain()

    def _vet(self, command: Command, snapshot: SensorSnapshot, mode: str) -> Verdict:
        # `stop` outranks every policy, including the mode gate: an escape hatch that a mode
        # can refuse is not an escape hatch. The interlock says the same thing, first.
        if command.action == "stop":
            return Verdict(accepted=True, action="stop", params=dict(command.params))
        # The mode gate. Every source is subject to it, not just clients: while the dog was
        # reported as resting, the FSM and the navigator could still walk it (P3-3). A refusal
        # always says which mode is in force and what would unblock it.
        if not mode_allows(mode, command.source):
            return Verdict(
                accepted=False,
                action=command.action,
                params=dict(command.params),
                veto="mode",
                detail=_MODE_DETAIL.get(mode, f"'{mode}' mode does not allow that source"),
            )
        # Every class is judged here, not just the gaits: the interlock applies the envelope its
        # class selects (`posture`/`expression` get tilt and battery, `non_motion` gets the
        # deadman), and an action nothing classifies is refused with a reason instead of reaching
        # a servo on the strength of a spelling.
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


def _params_key(params: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """A hashable, order-independent fingerprint of a command's parameters.

    Dedupe used to compare `(action, source)` only, so a producer that kept asking for
    `forward` at a new speed was silently ignored. `repr` is deliberate: motion params are
    scalars, and a value that is not hashable still must not crash the tick.
    """
    return tuple(sorted((str(key), repr(value)) for key, value in params.items()))