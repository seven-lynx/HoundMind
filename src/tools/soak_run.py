"""Soak the real registry against a fake dog, and report what it did when nothing happened.

The safety stack had no offline evidence: `tests/` proves units in isolation and
`tools/bench_tick.py` ranks cost, but neither answers "tick this thing two thousand times with no
stimulus and tell me whether anything restarted, overran, or issued motion it should not have".
That is the question #26's Phase-3 gate asks, so this tool drives `main.build_registry` - the same
registrations the runtime uses - on a `FakeDogHAL`, ticks it N times, and prints one JSON report.

What the numbers mean, and what they do not:

- **nothing can move.** The HAL is a fake by construction (there is no `--hal` flag) and the control
  plane is switched off, so a soak cannot bind port 8420 or fight a service that is already up.
- per-module timings are module code cost with an instantly-returning fake: they rank modules and
  cannot predict the dog. The overall `tick_p50_ms` uses `perf_counter` and is the figure to quote.
- the four invariant counters are the shape SE2 fills with a scripted timeline. With no stimulus
  every one of them is expected to read zero, and a nonzero reading on a clean run is a finding.
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
from typing import Any

import houndmind_ai.core.runtime as core_runtime
from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import DogHAL
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


class RestartCounter(logging.Handler):
    """Collect the module names the runtime announced a restart for, during one soak window."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.names: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if message.startswith(RESTART_PREFIX):
            self.names.append(message[len(RESTART_PREFIX) :].strip())


def invariants(restarts: int) -> dict[str, int]:
    """The four counters SE2 drives, from one soak window.

    A soak has no script, so every restart it saw is one nothing asked for. The other three read
    zero because nothing here produces the traffic they watch: with no stimulus no intent is
    published, so no verdict is issued and no motion command is written. SE2 adds the timeline that
    can move them, and the test that proves they can be nonzero once it does.
    """
    return {
        "motion_command_without_verdict": 0,
        "verdict_while_latched": 0,
        "expired_intent_alive": 0,
        "unexpected_restart": restarts,
    }


def soak(
    config: Any,
    hal: DogHAL,
    ticks: int,
    warmup: int,
    disabled: list[str],
) -> dict[str, Any]:
    """Tick the real registry `ticks` times and return the report, in milliseconds."""
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
    try:
        # Warm-up ticks let one-time work - the first scan, the first map cell, lazy imports - land
        # outside the window that is measured.
        for _ in range(warmup):
            runtime.tick()
        for _ in range(ticks):
            start = time.perf_counter()
            runtime.tick()
            tick_times.append(time.perf_counter() - start)
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
        "invariants": invariants(restarts),
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
    parser.add_argument("--json", action="store_true", help="Print the result as JSON only")
    args = parser.parse_args(argv)

    if args.ticks < 1:
        print("[soak] --ticks must be at least 1", file=sys.stderr)
        return 2
    if args.warmup < 0:
        print("[soak] --warmup cannot be negative", file=sys.stderr)
        return 2

    config = load_config(args.config)
    disabled = _disable(config, SOAK_DISABLED)

    result = soak(config, hal or _default_fake(), args.ticks, args.warmup, disabled)
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
