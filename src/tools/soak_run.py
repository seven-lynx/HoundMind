"""Soak the real registry against a fake dog, and report what it did when nothing happened.

The safety stack had no offline evidence: `tests/` proves units in isolation and
`tools/bench_tick.py` ranks cost, but neither answers "tick this thing two thousand times with
nothing wrong and tell me whether anything restarted, overran, or issued motion it should not
have". That is the question #26's Phase-3 gate asks, so this tool drives `main.build_registry` -
the same registrations the runtime uses - on a `FakeDogHAL`, ticks it N times, and prints one JSON
report.

What the numbers mean, and what they do not:

- **nothing can move.** The HAL is a fake by construction (there is no `--hal` flag) and the control
  plane is switched off, so a soak cannot bind port 8420 or fight a service that is already up.
- per-module timings are module code cost with an instantly-returning fake: they rank modules and
  cannot predict the dog. The overall `tick_p50_ms` uses `perf_counter` and is the figure to quote.
- the stimulus is a declarative timeline: `--script <file.json>`, or the built-in `default`. It
  applies sensor readings and the runtime mode at named tick numbers through `FakeDogHAL`'s own
  setters, so a script cannot reach a real dog even by mistake.
- the four invariant counters are read after every measured tick: a motion command with no verdict
  past its deadman, a verdict issued after the tilt latch was already set, an intent still on the
  board past its hold window, and a restart the timeline never asked for. All four are expected to
  read zero, and a nonzero reading on a clean run is a finding.
- a restart is read from the runtime's own announcement (`core/runtime.py:253`) through a logging
  handler: `ModuleStatus` carries no restart field, and `restart_modules` is consumed inside the
  tick that set it, so the context is already empty by the time a soak could look.
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import houndmind_ai.core.runtime as core_runtime
from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.kernel.actions import Repertoire, repertoire_from_settings
from houndmind_ai.kernel.commands import RUNTIME_MODES, ActionClass, canonical_action
from houndmind_ai.main import build_registry

# A soak must never bind a port: the control plane is the only listener in the tree, and a service
# that is already up would fail the run on `address in use` instead of measuring anything.
SOAK_DISABLED = frozenset({"api"})

# `core/runtime.py:253` announces a successful restart with this record. Counting the announcement
# is the only view from outside: the context key that asked for the restart is cleared as it is read.
RESTART_PREFIX = "Restarted module:"

_DEFAULT_TICKS = 2000
_DEFAULT_WARMUP = 30


def _disable(config: Any, names: frozenset[str]) -> list[str]:
    """Switch off every named module the config declares, and return the ones it did not have."""
    disabled: list[str] = []
    modules = config.modules or {}
    for name in sorted(names):
        entry = modules.get(name)
        if entry is None or not hasattr(entry, "enabled"):
            continue
        entry.enabled = False
        disabled.append(name)
    return disabled


def _default_fake() -> FakeDogHAL:
    """A dog with plausible readings, so a module takes its normal path instead of a veto."""
    hal = FakeDogHAL()
    hal.set_distance(120.0)
    hal.set_battery(8.0)
    hal.set_touch("none")
    hal.set_sound(1)
    hal.set_gyro((0.0, 0.0, 0.0))
    hal.set_acc((0.0, 0.0, -1.0))
    hal.set_imu(0.0, 0.0)
    return hal


# ---- stimulus timeline -----------------------------------------------------------------------

# The setters a timeline may name (`hal/fake.py:87-125`), and the fields that spread over more than
# one argument. Anything a timeline can say that is not listed here is a typo, refused at load.
_SETTERS: dict[str, str] = {
    "distance": "set_distance",
    "imu": "set_imu",
    "acc": "set_acc",
    "gyro": "set_gyro",
    "touch": "set_touch",
    "sound": "set_sound",
    "battery": "set_battery",
}
_SHAPE: dict[str, int] = {"imu": 2, "acc": 3, "gyro": 3}
# `mode` is not a reading: it writes `runtime_mode`, the key the gateway judges against
# (`act/gateway.py:451-454`). It is the only thing a timeline may set outside the HAL.
_EVENT_FIELDS: frozenset[str] = frozenset(_SETTERS) | {"mode"}


@dataclass(frozen=True)
class Event:
    """One timeline entry: what to set, at one measured tick (1-based)."""

    tick: int
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class Timeline:
    """A whole script: a name for the report, and the events it applies."""

    name: str
    events: tuple[Event, ...]


# The built-in timeline: what a dog with nothing wrong does for a couple of hundred ticks. A wall
# in front, a pat, a noise, the pack settling, the mode changing - every event is ordinary, so the
# four invariant counters must still read zero. A counter that fires here is the finding, not the
# stimulus.
DEFAULT_TIMELINE = Timeline(
    name="default",
    events=(
        Event(5, {"distance": 45.0}),
        Event(15, {"touch": "front"}),
        Event(20, {"touch": "none"}),
        Event(30, {"sound": 90}),
        Event(35, {"sound": None}),
        Event(50, {"distance": 120.0}),
        Event(60, {"imu": (3.0, -2.0)}),
        Event(65, {"imu": (0.0, 0.0)}),
        Event(80, {"battery": 7.8}),
        Event(100, {"mode": "manual"}),
        Event(120, {"mode": "idle"}),
    ),
)


def _percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile: the answer is one of the measurements, not an interpolation."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = int(round(fraction * (len(ordered) - 1)))
    return ordered[max(0, min(len(ordered) - 1, index))]


def _stats(values: list[float]) -> dict[str, float]:
    return {
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "max": max(values) if values else 0.0,
    }


def _as_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number")
    return float(value)


def _parse_value(key: str, value: Any, where: str) -> Any:
    """One event field, checked and normalised: a typo is a refused script, not a quiet dog."""
    if key in _SHAPE:
        if value is None:
            # `set_acc(None)` marks the sensor *invalid* rather than silent, which is an event too.
            return None
        if not isinstance(value, (list, tuple)) or len(value) != _SHAPE[key]:
            raise ValueError(f"{where}: {key!r} must be a list of {_SHAPE[key]} numbers or null")
        return tuple(_as_number(item, f"{where}: {key!r}") for item in value)
    if key == "mode":
        if value not in RUNTIME_MODES:
            raise ValueError(f"{where}: 'mode' must be one of {list(RUNTIME_MODES)}")
        return value
    if key == "touch":
        if not isinstance(value, str):
            raise ValueError(f"{where}: 'touch' must be a string")
        return value
    if key == "sound":
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"{where}: 'sound' must be an integer bearing or null")
        return value
    # `distance` and `battery`: a number, or null for "the sensor did not answer".
    return None if value is None else _as_number(value, f"{where}: {key!r}")


def _parse_event(raw: Any, index: int, source: str) -> Event:
    where = f"{source} event {index}"
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where}: expected an object")
    tick = raw.get("tick")
    if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
        raise ValueError(f"{where}: 'tick' must be an integer >= 0")
    fields: dict[str, Any] = {}
    for key, value in raw.items():
        if key == "tick":
            continue
        if key not in _EVENT_FIELDS:
            raise ValueError(
                f"{where}: unknown field {key!r}; expected one of {sorted(_EVENT_FIELDS)}"
            )
        fields[key] = _parse_value(key, value, where)
    if not fields:
        raise ValueError(f"{where}: nothing to set")
    return Event(tick=tick, fields=fields)


def _parse_timeline(raw: Any, source: str) -> Timeline:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{source}: expected an object with an 'events' list")
    name = raw.get("name", source)
    if not isinstance(name, str) or not name:
        raise ValueError(f"{source}: 'name' must be a non-empty string")
    entries = raw.get("events")
    if not isinstance(entries, list):
        raise ValueError(f"{source}: 'events' must be a list")
    return Timeline(
        name=name,
        events=tuple(_parse_event(entry, index, source) for index, entry in enumerate(entries)),
    )


def load_timeline(spec: str) -> Timeline:
    """`default`, or the path of a JSON script, as a checked `Timeline`.

    Raises `ValueError` with a line an operator can act on: a script is typed by hand, so a refused
    field has to name the event that spelled it.
    """
    if spec == DEFAULT_TIMELINE.name:
        return DEFAULT_TIMELINE
    try:
        with open(spec, encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError as exc:
        raise ValueError(f"cannot read script {spec!r}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"script {spec!r} is not JSON: {exc}") from exc
    return _parse_timeline(raw, f"script {spec!r}")


def apply_event(hal: DogHAL, context: Any, event: Event) -> int:
    """Apply one event and return how many of its fields landed.

    Sensor fields go through the fake's scripting setters; a HAL that does not offer one is skipped
    rather than half-applied, because this tool must never write a reading into a dog. `mode` needs
    no HAL at all. The count is what lets the report say a script was applied instead of a typo
    looking like a quiet dog.
    """
    applied = 0
    for key, value in event.fields.items():
        if key == "mode":
            context.set("runtime_mode", value)
            applied += 1
            continue
        setter = getattr(hal, _SETTERS[key], None)
        if not callable(setter):
            continue
        if key in _SHAPE and value is not None:
            setter(*value)
        else:
            setter(value)
        applied += 1
    return applied


class RestartCounter(logging.Handler):
    """Collect the module names the runtime announced a restart for, during one soak window."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.names: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith(RESTART_PREFIX):
            self.names.append(message[len(RESTART_PREFIX) :].strip())


# How long a command may sit in the context with no verdict before it counts. The gateway writes
# both keys in the same call (`act/gateway.py:226-239`), so an absent verdict is a writer that
# bypassed it; the grace lets a command finish its own deadman first, and absorbs a consumer that
# reads the two keys in between.
_VERDICT_GRACE_S = 0.5

# How long a slot may sit past its own deadline before it counts. A slot can cross that deadline
# between the gateway's `latest()` and this observation - microseconds of other modules - so only a
# slot stale by more than a couple of ticks is one the board failed to let die.
_EXPIRY_GRACE_S = 0.25


def _stale_slots(board: Any, now: float) -> int:
    """Slots that outlived their hold window and are still on the board, at the observation point.

    `latest()` (`kernel/intents.py:111`) and `find()` (`:125`) delete a stale slot and bump
    `expired` as they answer, so asking the board "is this intent live?" would destroy the evidence
    and the counter could only ever read zero. This reads `_slots` under the board's own lock
    instead - the other route the plan's risk note allows - and asks the board nothing.
    """
    lock = getattr(board, "_lock", None)
    slots = getattr(board, "_slots", None)
    if lock is None or not isinstance(slots, dict):
        return 0
    with lock:
        return sum(1 for slot in slots.values() if now > slot.expires_at + _EXPIRY_GRACE_S)


class InvariantCounter:
    """The four things a healthy soak never does, counted at the observation point.

    One instance lives for one soak. `observe()` runs after every measured tick, over the keys
    `act/gateway.py` publishes: `motion_command` and `motion_verdict` in one call, `tilt_latched`
    after the interlock has judged the tick.
    """

    def __init__(self, repertoire: Repertoire | None = None) -> None:
        self._repertoire = repertoire if repertoire is not None else Repertoire.builtin()
        self._latched: bool | None = None
        self._counted: set[str] = set()
        self.motion_command_without_verdict = 0
        self.verdict_while_latched = 0
        self.expired_intent_alive = 0

    def observe(self, context: Any, now: float) -> None:
        command = context.get("motion_command")
        verdict = context.get("motion_verdict")
        command_payload = command if isinstance(command, Mapping) else None
        verdict_payload = verdict if isinstance(verdict, Mapping) else None
        if command_payload is not None:
            self._check_verdict(command_payload, verdict_payload, now)
        if self._latched and verdict_payload is not None:
            self._check_latch(verdict_payload)
        self.expired_intent_alive += _stale_slots(context.get("intent_board"), now)
        # Only now: the tick that *set* the latch is the tick the veto happened on, so a verdict on
        # it is correct behaviour. Comparing against the previous tick rather than this one is what
        # makes "a verdict while latched" mean "the interlock let something through anyway".
        self._latched = bool(context.get("tilt_latched"))

    def _check_verdict(
        self, command: Mapping[str, Any], verdict: Mapping[str, Any] | None, now: float
    ) -> None:
        if verdict is not None or not self._is_motion(command):
            return
        if not self._past_deadman(command, now):
            return
        identity = str(command.get("id") or command.get("seq") or command.get("action"))
        if identity in self._counted:
            return
        self._counted.add(identity)
        self.motion_command_without_verdict += 1

    @staticmethod
    def _past_deadman(command: Mapping[str, Any], now: float) -> bool:
        """Whether `now` is past the command's own expiry plus the grace.

        A payload with no usable `issued_at` proves no deadman at all, which is already the defect
        this counter names, so it counts rather than waiting for a clock it does not carry.
        """
        issued = command.get("issued_at")
        if isinstance(issued, bool) or not isinstance(issued, (int, float)):
            return True
        ttl = command.get("ttl_ms")
        span = (
            float(ttl) / 1000.0
            if isinstance(ttl, (int, float)) and not isinstance(ttl, bool)
            else 0.0
        )
        return now > float(issued) + span + _VERDICT_GRACE_S

    def _check_latch(self, verdict: Mapping[str, Any]) -> None:
        if verdict.get("status") != "accepted":
            return
        if not self._is_motion({"action": verdict.get("action")}):
            return
        self.verdict_while_latched += 1

    def _is_motion(self, command: Mapping[str, Any]) -> bool:
        """True when the action is one the tilt latch refuses.

        `stop` and the `non_motion` class are accepted while latched on purpose - the interlock
        returns before the latch for both (`act/interlock.py:143`, `:166-170`) - so counting them
        would fire this counter the first time the dog's head moved while it was tilted.
        """
        raw = command.get("canonical_action") or command.get("action")
        if not isinstance(raw, str):
            return True
        action = canonical_action(raw)
        if action == "stop":
            return False
        spec = self._repertoire.spec(action)
        return spec is None or spec.action_class is not ActionClass.NON_MOTION

    def counters(self) -> dict[str, int]:
        return {
            "motion_command_without_verdict": self.motion_command_without_verdict,
            "verdict_while_latched": self.verdict_while_latched,
            "expired_intent_alive": self.expired_intent_alive,
        }


def invariants(observed: InvariantCounter, restarts: int) -> dict[str, int]:
    """The four counters for one soak window, `unexpected_restart` included.

    A soak has no event that asks for a restart - the timeline drives readings and a mode, nothing
    else - so every restart it heard is one nothing asked for.
    """
    return {**observed.counters(), "unexpected_restart": restarts}


def soak(
    config: Any,
    hal: DogHAL,
    ticks: int,
    warmup: int,
    disabled: list[str],
    timeline: Timeline | None = None,
) -> dict[str, Any]:
    """Tick the real registry `ticks` times, applying `timeline`, and return the report in ms."""
    script = DEFAULT_TIMELINE if timeline is None else timeline
    registry = build_registry(config, hal=hal)
    # `registered` is the roster the registry holds, not the subset that ticks: `api` is switched off
    # for the port rule and a config-disabled module never starts, yet both are still wired. Reporting
    # the roster separately is what lets "names every registered module" survive that rule.
    registered = list(registry.names())
    runtime = HoundMindRuntime(config, registry.modules())
    budget_s = 1.0 / max(1, config.loop.tick_hz)
    per_module: dict[str, list[float]] = {}
    overruns: dict[str, int] = {}
    tick_times: list[float] = []
    counter = RestartCounter()
    runtime_logger = logging.getLogger(core_runtime.__name__)

    runtime.start()
    # Read the roster before `stop()`: stopping a module clears its `started` flag, and the report
    # has to say which modules were actually driven.
    started = [m.name for m in runtime.modules if m.status.started]
    runtime_logger.addHandler(counter)
    # The interlock's own classification, so an accepted head turn while the dog is tilted is not
    # mistaken for an accepted gait: `gateway.start` reads the same table (`kernel/actions.py:195`).
    observed = InvariantCounter(repertoire_from_settings(runtime.context.get("settings")))
    applied = 0
    try:
        # Warm-up ticks let one-time work - the first scan, the first map cell, lazy imports - land
        # outside the window that is measured.
        for _ in range(warmup):
            runtime.tick()
        for index in range(1, ticks + 1):
            # Applied before the tick, so every module judges the readings the script just set.
            for event in script.events:
                if event.tick == index:
                    applied += apply_event(hal, runtime.context, event)
            start = time.perf_counter()
            runtime.tick()
            tick_times.append(time.perf_counter() - start)
            # The observation point: after the tick, so every module has published, and before the
            # timings are read, so no counter can be charged for another module's work.
            observed.observe(runtime.context, time.monotonic())
            raw_durations = runtime.context.get("module_tick_durations")
            durations = raw_durations if isinstance(raw_durations, dict) else {}
            for name, seconds in durations.items():
                per_module.setdefault(name, []).append(float(seconds))
                if float(seconds) > budget_s:
                    overruns[name] = overruns.get(name, 0) + 1
    finally:
        runtime_logger.removeHandler(counter)
        runtime.stop()

    rows: list[dict[str, Any]] = []
    for name, samples in per_module.items():
        stats = _stats(samples)
        rows.append(
            {
                "module": name,
                "samples": len(samples),
                "p50_ms": stats["p50"] * 1000.0,
                "p95_ms": stats["p95"] * 1000.0,
                "max_ms": stats["max"] * 1000.0,
                "overruns": overruns.get(name, 0),
            }
        )
    rows.sort(key=lambda row: row["p95_ms"], reverse=True)

    overall = _stats(tick_times)
    restarts = len(counter.names)
    return {
        "ticks": ticks,
        "warmup": warmup,
        "tick_hz_target": max(1, config.loop.tick_hz),
        "budget_ms": budget_s * 1000.0,
        "tick_p50_ms": overall["p50"] * 1000.0,
        "tick_p95_ms": overall["p95"] * 1000.0,
        "tick_max_ms": overall["max"] * 1000.0,
        "registered": registered,
        "started": started,
        "disabled": disabled,
        "restarts": restarts,
        "restart_names": list(counter.names),
        "script": {"name": script.name, "events": len(script.events), "applied": applied},
        "invariants": invariants(observed, restarts),
        "modules": rows,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _print_report(result: dict[str, Any]) -> None:
    print(
        f"[soak] {result['ticks']} ticks (+{result['warmup']} warmup) at "
        f"{result['tick_hz_target']} Hz, budget {result['budget_ms']:.1f} ms"
    )
    print(
        f"[soak] tick  p50 {result['tick_p50_ms']:.3f} ms   "
        f"p95 {result['tick_p95_ms']:.3f} ms   max {result['tick_max_ms']:.3f} ms"
    )
    print(f"[soak] {'module':<22}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}{'over':>6}")
    for row in result["modules"]:
        print(
            f"[soak] {row['module']:<22}{row['p50_ms']:>9.3f}{row['p95_ms']:>9.3f}"
            f"{row['max_ms']:>9.3f}{row['overruns']:>6}"
        )
    print(
        f"[soak] registered {len(result['registered'])}   "
        f"started {len(result['started'])}   disabled {len(result['disabled'])}"
    )
    counters = ", ".join(f"{name}={value}" for name, value in result["invariants"].items())
    print(f"[soak] restarts {result['restarts']}   invariants {counters}")
    script = result["script"]
    print(
        f"[soak] script {script['name']}   "
        f"{script['applied']}/{script['events']} events applied"
    )
    if result["disabled"]:
        print(f"[soak] disabled: {', '.join(result['disabled'])}")
    print(f"[soak] python {result['python']} on {result['platform']}")
    print("[soak] fake HAL: nothing moved, nothing listened, no device cost measured")


def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Soak the real registry on a fake dog (never moves, never listens)"
    )
    parser.add_argument("--config", type=str, default=None, help="Path to settings.jsonc")
    parser.add_argument(
        "--ticks",
        type=int,
        default=_DEFAULT_TICKS,
        help=f"Soak ticks (default {_DEFAULT_TICKS})",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=_DEFAULT_WARMUP,
        help=f"Unmeasured ticks first (default {_DEFAULT_WARMUP})",
    )
    parser.add_argument(
        "--script",
        type=str,
        default=DEFAULT_TIMELINE.name,
        help=(
            f"Stimulus timeline: '{DEFAULT_TIMELINE.name}', or a JSON file of "
            "{'events': [{'tick': n, '<reading|mode>': value}]}"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print the result as JSON only")
    args = parser.parse_args(argv)

    if args.ticks < 1:
        print("[soak] --ticks must be at least 1", file=sys.stderr)
        return 2
    if args.warmup < 0:
        print("[soak] --warmup cannot be negative", file=sys.stderr)
        return 2
    # Refused here, before a config is read and before one module starts: a script that cannot be
    # parsed must not look like a soak that found nothing.
    try:
        timeline = load_timeline(args.script)
    except ValueError as exc:
        print(f"[soak] {exc}", file=sys.stderr)
        return 2

    config = load_config(args.config)
    disabled = _disable(config, SOAK_DISABLED)

    result = soak(
        config, hal or _default_fake(), args.ticks, args.warmup, disabled, timeline=timeline
    )
    if not result["modules"]:
        print("[soak] no module produced a timing; nothing was started", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
