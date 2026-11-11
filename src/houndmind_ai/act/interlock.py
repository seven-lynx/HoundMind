"""The mandatory interlock.

Safety is not a module here. It is the last thing every command passes through before it
reaches a servo, and it cannot be disabled from configuration. Every refusal returns a
reason: a silent refusal is a bug, because the operator then has no way to know why the dog
did not move.

The *class* of the action decides how much of the envelope applies. The classification is data
(`config/actions.jsonc`, loaded by `kernel/actions.py`), not a second list in Python, and a class
never edits a limit — it only selects which of them apply. Checks, in order:

1. ``stop`` is always accepted — the escape hatch can never be vetoed.
2. Unknown action → refused.
3. Past its TTL → refused (deadman). Every class spends its deadman, an LED included: a stale
   colour request is as wrong as a stale gait.
4. ``non_motion`` → accepted here. A dog at 6.3 V must still be able to whine about it.
5. Tilt beyond the latch threshold → refused until cleared.
6. Low battery → refused.
7. ``locomotion`` with a last *valid* distance at or below the emergency distance → refused — the
   *forward family* only (`FORWARD_ACTIONS`): retreat and turn-in-place are what get the dog out of
   that situation, so blocking them at 8 cm would freeze it against the obstacle.
8. Speed clamped to the board limit.

Obstacle and tilt checks use validity flags, so a broken sensor cannot veto motion forever
and a stale good value cannot authorise it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from houndmind_ai.hal.iface import SensorSnapshot, as_int
from houndmind_ai.kernel.actions import Repertoire
from houndmind_ai.kernel.commands import FORWARD_ACTIONS, ActionClass, Command, Verdict

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
        repertoire: Repertoire | None = None,
    ) -> None:
        self.limits = limits or InterlockLimits()
        self._now = now or time.monotonic
        # With nothing loaded, the built-in classification still answers coherently: a gateway
        # built without config (a unit test, an embedding) is not a gateway without an envelope.
        self._repertoire = repertoire or Repertoire.builtin()
        self._tilt_latched = False
        self._clamp_reported = False

    # ---- state -------------------------------------------------------------

    @property
    def tilt_latched(self) -> bool:
        return self._tilt_latched

    def clear_tilt(self) -> None:
        """A human has confirmed the dog is upright again."""
        self._tilt_latched = False

    def set_repertoire(self, repertoire: Repertoire | None) -> None:
        """Install the classification this runtime is running with.

        Called once by the gateway at start, from the runtime's settings. This is the whole point
        of the classes being config: adding an action to `config/actions.jsonc` classifies it. It
        cannot weaken the envelope, because `build_repertoire` re-applies the locomotion floor.
        """
        self._repertoire = repertoire or Repertoire.builtin()

    # ---- evaluation --------------------------------------------------------

    def evaluate(self, command: Command, snapshot: SensorSnapshot) -> Verdict:
        action = command.action
        params = dict(command.params)

        if action == "stop":
            return Verdict(accepted=True, action=action, params=params)

        spec = self._repertoire.spec(action)
        if spec is None:
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

        if spec.action_class is ActionClass.NON_MOTION:
            # A sound, an LED or a head angle must not be gated on a flat battery or a wall in
            # front of the dog. An expression that can be blocked is how a pet stops feeling
            # alive — and it is how the dog cannot report that it is in trouble.
            return Verdict(accepted=True, action=action, params=params)

        # Everything below this line moves the dog, however slightly.

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

        # The obstacle rule is the forward family, not the whole locomotion class: `backward` and
        # the turns are how the dog gets out of a corner, and a turn-in-place refused at 8 cm is a
        # dog frozen facing a wall. (`trot` is a forward gait but is not in the family yet —
        # `MOTION_ACTIONS` feeds the watchdog hold and the scan lock, so widening the forward
        # family is its own change, not a side effect of this one.)
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