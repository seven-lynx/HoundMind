"""The actuator side of the loop: decide *when* to move, never *how*.

`MotorModule` keeps the policy — the action cooldown, quiet mode, the retreat/turn followups and
the closed-loop turn that reads the heading between steps. The vendor calls moved to
`hal/vendor.py`:

- the `pidog` import and the `ActionFlow` queue, which this module used to own,
- `do_action` / `wait_all_done` for a single supervised step,
- `head_move` for head-follow, `set_rpy` for balance,
- `apply_servo_offsets` for calibration,
- closing the dog, which every module used to attempt for itself.

The module reads exactly one command key, `motion_command`, which `act/gateway.py` produced
after resolving precedence and applying the interlock (H-10). A vetoed command cannot be
resurrected by a lower-priority producer, because nobody else is writing that key.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.kernel.scheduler import LatestJobWorker

logger = logging.getLogger(__name__)


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


def _canonical(action: str) -> str:
    """`turn left` and `turn_left` are the same command; the HAL speaks the underscore form."""
    return action.strip().lower().replace(" ", "_")


def _params_key(params: Any) -> tuple[tuple[str, str], ...]:
    """A comparable form of a command's parameters (`act/gateway.py` keys its dedupe the same way).

    `repr` rather than `value` because a params dict is JSON, so `"2"` and `2` are different
    commands, and a nested value that never reaches a servo still has to compare equal to itself.

    `cue` is excluded, deliberately: it rides the command as a transition marker (P3 L3), so two
    otherwise identical commands — one announcing a state entry, one not — must stay the same step.
    Otherwise every entry into a state would re-issue the action it was already running.
    """
    if not isinstance(params, dict):
        return ()
    return tuple(
        sorted(
            (str(key), repr(value))
            for key, value in params.items()
            if key != "cue"
        )
    )


# Actions whose parameters are the whole command. A `sound` with no effect name, or an `rgb` with
# no colour, is a no-op, so these must reach the HAL verbatim. Locomotion joined them in P2 R4
# (#64): `config/actions.jsonc` has declared `speed`/`steps`/`wait` for the five moving actions all
# along, and `hal/vendor.py:385` is the code that honours them — dropping them here made the
# catalog a promise the device did not keep.
_PARAM_ACTIONS = frozenset(
    {
        "sound",
        "speak",
        "rgb",
        "rpy",
        "head",
        "forward",
        "backward",
        "turn_left",
        "turn_right",
        "trot",
    }
)

# The subset that can block. A parameterised step takes `hal/vendor.py::_direct`, which holds the
# servo bus and, with `wait`, keeps it until the gait finishes; one head sweep can own that bus for
# seconds. Those calls leave the tick and run on the module's own worker. A bare `forward` still
# goes straight through: the vendor queues it and returns.
_LOCOMOTION_ACTIONS = frozenset({"forward", "backward", "turn_left", "turn_right", "trot"})


class MotorModule(Module):
    """Executes the gateway's command through the HAL."""

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.hal: DogHAL | None = None
        # The dedupe memory is the action *and its parameters*: two identical steps are one
        # command unless something else happened between them, and an absent command clears it
        # (`tick`), which is what lets a routine run the same step twice (F-P2-2, #65).
        self.last_action: str | None = None
        self.last_params: tuple[tuple[str, str], ...] = ()
        self.last_action_ts = 0.0
        # The cue this module last played, as `(name, volume, action, params)`. A board slot stays
        # live for its TTL, so the same command reaches this module on several ticks; the signature
        # is what keeps a transition to one sound (P3 L3).
        self._cue_key: tuple[str, int, str, tuple[tuple[str, str], ...]] | None = None
        # Blocking locomotion steps run here, never on the decision loop.
        self.worker: LatestJobWorker | None = None
        # Diagnostics. A deferral is a command that will run later; a silent one is the hole #65
        # reported. Both counters rise only while something is genuinely holding the dog back.
        self.rate_limited = 0
        self.deferred = 0

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        hal = context.get("hal")
        if hal is None:
            self.disable("no HAL available")
            return
        self.hal = hal
        self.worker = LatestJobWorker(f"houndmind-{self.name}")
        self.worker.start()

        # Servo offsets are user data written by the calibration workflow: apply them if the
        # file asks for it, otherwise leave the servos where the hardware put them.
        calibration = (context.get("settings") or {}).get("calibration", {})
        if calibration.get("auto_apply_servo_offsets", False):
            offsets = calibration.get("servo_zero_offsets", {})
            if isinstance(offsets, dict) and offsets:
                self.hal.apply_offsets(offsets)
            else:
                self._apply_persisted_offsets(calibration)

    def tick(self, context) -> None:
        self._release_head_follow_if_due(context)
        command = context.get("motion_command")
        if not isinstance(command, dict):
            # "Nothing asked" is a state, not a pause: forget the last command, so an identical one
            # that arrives later is a new step. The gateway clears its own dedupe key the same way
            # (`act/gateway.py::tick`), and the routine runner retracts between two equal steps
            # precisely so this branch runs (F-P2-2, #65).
            self.last_action = None
            self.last_params = ()
            self._cue_key = None
            return
        raw = command.get("canonical_action") or command.get("action")
        if not raw:
            return
        action = _canonical(str(raw))
        params = command.get("params")
        # The cue is played before the dedupe below on purpose: a state entry must sound even when
        # the action it rides is a repeat of the one already running (`patrol` → `explore` picking
        # the same `forward`). It is stripped from the payload and from the fingerprint, so it can
        # never turn that repeat into a second step, and `_cue_key` keeps a live slot to one sound.
        self._play_cue(action, params)
        params_key = _params_key(params)
        if action == self.last_action and params_key == self.last_params:
            return
        if self.hal is None:
            return

        # Configurable cooldown keeps actions from spamming the action queue.
        settings = (context.get("settings") or {}).get("motors", {})
        min_interval = _safe_float(settings.get("min_action_interval_s", 0.2), 0.2)
        quiet = (context.get("settings") or {}).get("quiet_mode", {})
        if context.get("quiet_mode_active"):
            quiet_interval = _safe_float(
                quiet.get("motor_min_action_interval_s", min_interval), min_interval
            )
            min_interval = max(min_interval, quiet_interval)
        safety_settings = (context.get("settings") or {}).get("safety", {})
        if context.get("emergency_stop_active") and safety_settings.get(
            "emergency_stop_use_hardware_stop", False
        ):
            self._hardware_stop()

        try:
            now = time.time()
            # The rate limiter protects the action queue from a producer that changes its mind
            # every tick. It must never delay a `stop`: at the shipped 200 ms interval, a
            # watchdog hold could sit behind a gait for a fifth of a second, and "stop" a fifth
            # of a second late is a different dog.
            if action != "stop" and now - self.last_action_ts < min_interval:
                # The command is *not* consumed: it stays in the context, so the first tick after
                # the interval runs it. Returning without a word is what made a dropped step
                # invisible (#65).
                self.rate_limited += 1
                if self.rate_limited == 1:
                    logger.info(
                        "Action %s deferred: %.2f s of the %.2f s interval left",
                        action,
                        min_interval - (now - self.last_action_ts),
                        min_interval,
                    )
                return
            navigation_turn = context.get("navigation_turn")
            if isinstance(navigation_turn, dict):
                if self._turn_by_angle(context, navigation_turn):
                    context.set("navigation_turn", None)
                    self.last_action = "turn"
                    self.last_params = ()
                    self.last_action_ts = now
                    return

            if action in ("turn_left", "turn_right"):
                direction = "left" if action == "turn_left" else "right"
                self._schedule_head_follow(context, direction)

            # Execute action; optionally follow with a retreat/turn sequence. The actions whose
            # params are the whole command get them; everything else stays fire-and-forget.
            payload: dict[str, Any] = {}
            if action in _PARAM_ACTIONS:
                raw_params = params
                payload = dict(raw_params) if isinstance(raw_params, dict) else {}
                # The cue is this repo's annotation, not the vendor's parameter: it was played
                # above and must not ride into a vendor call that has no idea what it means.
                payload.pop("cue", None)
                if action == "head":
                    # The API answers 202 before the head arrives; blocking here would let a
                    # cosmetic command set the loop's cadence (P3-2).
                    payload["wait"] = False
            # A retreat the navigation layer asked for travels with the step: both run on the worker,
            # in that order, so the closed-loop turn behind a retreat cannot hold the tick. The job
            # is taken before the step runs and the key is retracted after it has been handed over,
            # which is what stops a followup from being re-run by every later command (#120).
            followup = self._followup_job(context)
            if action in _LOCOMOTION_ACTIONS and payload:
                if not self._dispatch_off_tick(action, payload, then=followup):
                    # Nothing was consumed, so the followup stays in the context for the retry.
                    return
            else:
                self.hal.action(action, payload)
                if followup is not None and not self._queue_followup(followup):
                    followup = None
            # Retract whatever was there: it was either handed to the worker above or dropped as
            # stale. A followup describes a step that has already happened, so it must not outlive it.
            if context.get("navigation_followup") is not None:
                context.set("navigation_followup", None)
            self.last_action = action
            self.last_params = params_key
            self.last_action_ts = now
            self.rate_limited = 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Motor action failed: %s", exc)
            self.disable(str(exc))

    def _play_cue(self, action: str, params: Any) -> None:
        """Play the sound attached to this command, at most once per command.

        A cue is a transition marker the behaviour layer hangs on the command it is already
        publishing (P3 L3): it is not an action, it never reaches `motion_command`'s action, and it
        never enters the fingerprint `_params_key` builds. Two failure modes are handled here rather
        than upstream: the board slot lives for its TTL, so the same command arrives on several
        ticks (`_cue_key` is what keeps that to one sound), and a malformed cue is dropped with one
        warning instead of reaching the audio path.
        """
        cue = params.get("cue") if isinstance(params, dict) else None
        if not isinstance(cue, dict):
            self._cue_key = None
            return
        name = cue.get("name")
        if not isinstance(name, str) or not name.strip():
            self._cue_key = None
            return
        name = name.strip()
        volume = max(0, min(100, _safe_int(cue.get("volume"), 70)))
        key = (name, volume, action, _params_key(params))
        if key == self._cue_key:
            return
        self._cue_key = key
        if self.hal is None:
            return
        try:
            self.hal.sound(name, volume)
        except Exception:  # noqa: BLE001 - a cue is cosmetic and must never fail a step
            logger.warning("Cue %r failed to play", name, exc_info=True)

    def _dispatch_off_tick(
        self, action: str, payload: dict[str, Any], then: Callable[[], None] | None = None
    ) -> bool:
        """Run one blocking step on this module's worker. False means "retry next tick".

        A refusal is not a drop: `motion_command` stays in the context, so the tick after the
        worker frees is this step, not whichever step a producer has moved on to.

        `then` is work that belongs behind the step (a navigation retreat). It runs in the same job,
        after the action, so the two stay in order and neither occupies the decision loop.
        """
        worker = self.worker
        hal = self.hal
        if worker is None or hal is None:
            return False
        if worker.busy:
            self.deferred += 1
            if self.deferred == 1:
                logger.info("Locomotion step %s deferred: the motor worker is busy", action)
            return False
        worker.submit("step", lambda: self._run_step(hal, action, payload, then))
        self.deferred = 0
        return True

    @staticmethod
    def _run_step(
        hal: DogHAL,
        action: str,
        payload: dict[str, Any],
        then: Callable[[], None] | None,
    ) -> None:
        """One step, then whatever trails it. The worker runs this, never the decision loop."""
        hal.action(action, payload)
        if then is not None:
            then()

    def _followup_job(self, context) -> Callable[[], None] | None:
        """The retreat the navigation layer asked for, as a runnable job, or None.

        Two rules the old inline path did not have (#120). The payload is retracted once it has been
        handed over, because a followup describes the step that just happened: nothing cleared the
        key before, so every later command re-ran a stale retreat. And one older than
        `movement.followup_ttl_s` is dropped instead of run late, so a producer that wedged cannot
        make the dog retreat on an observation it no longer has.
        """
        followup = context.get("navigation_followup")
        if not isinstance(followup, dict):
            return None
        settings = context.get("settings") or {}
        max_age = _safe_float((settings.get("movement") or {}).get("followup_ttl_s", 1.0), 1.0)
        issued = followup.get("timestamp")
        if max_age > 0 and isinstance(issued, (int, float)):
            age = time.time() - float(issued)
            if age > max_age:
                logger.debug("Dropping a %.1f s old navigation followup", age)
                return None
        # The context entry is replaced by the producer next tick, so the job owns its own copy.
        payload = dict(followup)
        return lambda: self._run_followup(context, payload)

    def _queue_followup(self, job: Callable[[], None]) -> bool:
        """Hand a followup to the worker when the action it trails did not go there itself."""
        worker = self.worker
        if worker is None:
            return False
        return worker.submit("followup", job)

    def _run_followup(self, context, followup: dict) -> None:
        """The retreat itself: the backward steps, then the turn. Runs on the motor worker."""
        hal = self.hal
        if hal is None:
            return
        if followup.get("type") == "retreat_turn":
            backup_steps = _safe_int(followup.get("backup_steps", 2), 2)
            direction = str(followup.get("direction", "auto"))
            if direction == "auto":
                direction = "left"
            for _ in range(max(1, backup_steps)):
                hal.action("backward", {})
            self._enqueue_turn(context, direction, steps=backup_steps)
        elif followup.get("type") == "sequence":
            for entry in followup.get("actions", []):
                if isinstance(entry, str):
                    hal.action(_canonical(entry), {})

    def _enqueue_turn(self, context, direction: str, steps: int = 1) -> None:
        if self.hal is None:
            return
        if self._turn_by_angle(context, {"direction": direction, "steps": steps}):
            return
        turn = "turn_left" if direction == "left" else "turn_right"
        for _ in range(max(1, _safe_int(steps, 1))):
            self.hal.action(turn, {})

    def _turn_by_angle(self, context, payload: dict) -> bool:
        """Closed-loop turn: one supervised step at a time until the heading is close enough."""
        heading = context.get("current_heading")
        if heading is None or self.hal is None:
            return False

        direction = str(payload.get("direction", "left"))
        degrees = payload.get("degrees")
        steps = _safe_int(payload.get("steps", 1), 1)

        settings = context.get("settings") or {}
        movement = settings.get("movement", {})
        orientation = settings.get("orientation", {})
        perf = settings.get("performance", {})
        safe_mode = bool(perf.get("safe_mode_enabled", False))
        degrees_per_step = _safe_float(movement.get("turn_degrees_per_step", 15.0), 15.0)
        if degrees is None:
            degrees = degrees_per_step * steps
        degrees = _safe_float(degrees, degrees_per_step * steps)
        if direction == "right":
            degrees = -degrees

        tolerance = _safe_float(orientation.get("turn_tolerance_deg", 5.0), 5.0)
        timeout_s = _safe_float(orientation.get("turn_timeout_s", 3.0), 3.0)
        speed = _safe_int(movement.get("speed_turn_normal", 200), 200)
        if safe_mode:
            speed = _safe_int(perf.get("safe_mode_turn_speed", speed), speed)
        hint = context.get("energy_speed_hint")
        if hint == "fast":
            speed = _safe_int(movement.get("speed_turn_fast", speed), speed)
        elif hint == "slow":
            speed = _safe_int(movement.get("speed_turn_slow", speed), speed)

        def ang_diff(a: float, b: float) -> float:
            return (a - b + 180.0) % 360.0 - 180.0

        start = _safe_float(heading, 0.0)
        target = (start + degrees) % 360.0
        end_time = time.time() + timeout_s

        self._apply_head_follow(direction, context)

        while time.time() < end_time:
            current = _safe_float(context.get("current_heading"), start)
            remaining = ang_diff(target, current)
            if abs(remaining) <= tolerance:
                self._apply_head_center(context)
                return True
            step = "turn_left" if remaining > 0 else "turn_right"
            try:
                self.hal.action(step, {"speed": speed, "steps": 1, "wait": True})
            except Exception:  # noqa: BLE001
                self._apply_head_center(context)
                return False
            time.sleep(0.05)
        self._apply_head_center(context)
        return False

    def stop(self, context) -> None:
        """The HAL belongs to `HalModule`; this module only gives up its reference."""
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.stop()
        self.hal = None

    def _hardware_stop(self) -> None:
        if self.hal is None:
            return
        try:
            self.hal.stop()
        except Exception:  # noqa: BLE001
            logger.warning("HAL stop failed", exc_info=True)

    def _head_follow_config(
        self, context
    ) -> tuple[bool, float, int, float, bool, float, bool, float]:
        settings = (context.get("settings") or {}).get("motors", {})
        enabled = bool(settings.get("head_turn_follow_enabled", True))
        degrees = _safe_float(settings.get("head_turn_follow_deg", 0.0), 0.0)
        speed = _safe_int(settings.get("head_turn_follow_speed", 70), 70)
        hold_s = _safe_float(settings.get("head_turn_follow_hold_s", 0.4), 0.4)
        respect_scanning = bool(settings.get("head_turn_follow_respect_scanning", True))
        scan_block_s = _safe_float(settings.get("head_turn_follow_scan_block_s", 0.4), 0.4)
        respect_attention = bool(
            settings.get("head_turn_follow_respect_attention", True)
        )
        attention_block_s = _safe_float(
            settings.get("head_turn_follow_attention_block_s", 0.6), 0.6
        )
        return (
            enabled,
            degrees,
            speed,
            hold_s,
            respect_scanning,
            scan_block_s,
            respect_attention,
            attention_block_s,
        )

    def _head_follow_blocked(self, context) -> bool:
        (
            _,
            _,
            _,
            _,
            respect_scanning,
            scan_block_s,
            respect_attention,
            attention_block_s,
        ) = self._head_follow_config(context)
        if not respect_scanning:
            scan_block_s = 0.0
        # A scan owns the head for its whole sweep. Moving it from here would corrupt the
        # reading the navigator is about to act on, and would race the scan worker for the bus.
        if respect_scanning and context.get("scan_in_flight"):
            return True
        if not respect_attention:
            attention_block_s = 0.0
        blocked = False
        if scan_block_s > 0:
            scan_reading = context.get("scan_reading")
            scan_ts = _safe_float(
                getattr(scan_reading, "timestamp", 0.0) if scan_reading else 0.0, 0.0
            )
            blocked = blocked or (time.time() - scan_ts) < max(0.0, scan_block_s)
        if attention_block_s > 0:
            attention_ts = context.get("attention_active_ts")
            try:
                attention_ts = (
                    _safe_float(attention_ts, 0.0) if attention_ts is not None else 0.0
                )
            except Exception:  # noqa: BLE001
                attention_ts = 0.0
            blocked = blocked or (time.time() - attention_ts) < max(
                0.0, attention_block_s
            )
        return blocked

    def _apply_head_follow(self, direction: str, context) -> None:
        if self.hal is None:
            return
        enabled, degrees, speed, _, _, _, _, _ = self._head_follow_config(context)
        if not enabled or degrees <= 0 or self._head_follow_blocked(context):
            return
        yaw = degrees if direction == "left" else -degrees
        try:
            # `wait=False`: this is cosmetic head-following. Blocking the tick on it is how a
            # behaviour module ends up setting the loop's cadence (P3-2).
            self.hal.action("head", {"yaw": yaw, "pitch": 0, "speed": speed, "wait": False})
        except Exception:  # noqa: BLE001
            return

    def _apply_head_center(self, context) -> None:
        if self.hal is None:
            return
        enabled, _, speed, _, _, _, _, _ = self._head_follow_config(context)
        if not enabled or self._head_follow_blocked(context):
            return
        try:
            self.hal.action("head", {"yaw": 0, "pitch": 0, "speed": speed, "wait": False})
        except Exception:  # noqa: BLE001
            return

    def _schedule_head_follow(self, context, direction: str) -> None:
        enabled, degrees, _, hold_s, _, _, _, _ = self._head_follow_config(context)
        if not enabled or degrees <= 0:
            return
        self._apply_head_follow(direction, context)
        context.set("head_turn_follow_release_ts", time.time() + max(0.0, hold_s))

    def _release_head_follow_if_due(self, context) -> None:
        release_ts = context.get("head_turn_follow_release_ts")
        try:
            release_ts = float(release_ts) if release_ts is not None else None
        except (TypeError, ValueError):
            release_ts = None
        if release_ts is None:
            return
        if time.time() >= release_ts:
            context.set("head_turn_follow_release_ts", None)
            self._apply_head_center(context)

    def _apply_persisted_offsets(self, calibration: dict) -> None:
        """Fall back to the calibration file when the config carries no offsets of its own."""
        import json
        from pathlib import Path

        path = Path(str(calibration.get("persist_path", "data/calibration.json")))
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            offsets = payload.get("last_result", {}).get("servo_zero_offsets", {})
            if isinstance(offsets, dict) and offsets and self.hal is not None:
                self.hal.apply_offsets(offsets)
        except Exception:  # noqa: BLE001
            logger.debug("Failed to read persisted calibration", exc_info=True)