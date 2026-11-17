"""Measure where the loop spends its budget, without a dog and without a socket.

`core/runtime.py:158-190` already times every module tick (`module_tick_durations`) and warns when
one overruns the loop budget, but nothing ran a hot path for N ticks and compared the result with a
written number, so "the loop stutters" could not be attributed to a module. This tool drives the
real registry - `main.build_registry`, the same list the runtime uses - on a `FakeDogHAL`, ticks it a
fixed number of times, and prints p50/p95/max per module plus how often each one overran.

What the numbers mean, and what they do not:

- they are **module code cost with an instantly-returning fake**. Vendor I2C reads, the camera and
  the audio stack are absent by construction, so this ranks modules; it cannot predict the dog.
- the per-module figures use `time.time()` inside `tick()`, the same clock the runtime warns on, so
  a very short tick is dominated by clock granularity on Windows. The overall figure uses
  `perf_counter` and is the one to quote for "a tick costs X ms".
- **nothing can move.** The HAL is a fake by design - there is no `--hal` flag - and the control
  plane is switched off, so a bench run cannot bind port 8420 or fight a service that is already up.
- a device number comes from running this on the Pi and recording it in `docs/ARCHITECTURE.md`
  section 3.2, which keeps the interpreter and the board beside the figure.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from typing import Any

from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.main import build_modules

# A bench run must never bind a port: the control plane is the only listener in the tree, and a
# service that is already up would make the run fail on `address in use` for no useful number.
BENCH_DISABLED = frozenset({"api"})


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
    """A dog with plausible readings, so the modules take their normal path instead of a veto."""
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


def bench(
    config: Any,
    hal: DogHAL,
    ticks: int,
    warmup: int,
    disabled: list[str],
) -> dict[str, Any]:
    """Tick the real registry `ticks` times and return the measurements, in milliseconds."""
    runtime = HoundMindRuntime(config, build_modules(config, hal=hal))
    budget_s = 1.0 / max(1, config.loop.tick_hz)
    per_module: dict[str, list[float]] = {}
    overruns: dict[str, int] = {}
    tick_times: list[float] = []

    runtime.start()
    # Read the roster before `stop()`: stopping a module clears its `started` flag, and the report
    # has to say which modules were actually driven.
    started = [m.name for m in runtime.modules if m.status.started]
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
    return {
        "ticks": ticks,
        "warmup": warmup,
        "tick_hz_target": max(1, config.loop.tick_hz),
        "budget_ms": budget_s * 1000.0,
        "tick_p50_ms": overall["p50"] * 1000.0,
        "tick_p95_ms": overall["p95"] * 1000.0,
        "tick_max_ms": overall["max"] * 1000.0,
        "modules": rows,
        "started": started,
        "disabled": disabled,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def _print_report(result: dict[str, Any]) -> None:
    print(
        f"[bench] {result['ticks']} ticks (+{result['warmup']} warmup) at "
        f"{result['tick_hz_target']} Hz, budget {result['budget_ms']:.1f} ms"
    )
    print(
        f"[bench] tick  p50 {result['tick_p50_ms']:.3f} ms   "
        f"p95 {result['tick_p95_ms']:.3f} ms   max {result['tick_max_ms']:.3f} ms"
    )
    print(f"[bench] {'module':<22}{'p50 ms':>9}{'p95 ms':>9}{'max ms':>9}{'over':>6}")
    for row in result["modules"]:
        print(
            f"[bench] {row['module']:<22}{row['p50_ms']:>9.3f}{row['p95_ms']:>9.3f}"
            f"{row['max_ms']:>9.3f}{row['overruns']:>6}"
        )
    if result["disabled"]:
        print(f"[bench] disabled: {', '.join(result['disabled'])}")
    print(f"[bench] python {result['python']} on {result['platform']}")
    print("[bench] fake HAL: module code cost, not device cost; nothing moved")


def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure per-module tick cost on a fake dog (never moves, never listens)"
    )
    parser.add_argument("--config", type=str, default=None, help="Path to settings.jsonc")
    parser.add_argument("--ticks", type=int, default=300, help="Measured ticks (default 300)")
    parser.add_argument("--warmup", type=int, default=30, help="Unmeasured ticks first (default 30)")
    parser.add_argument(
        "--hz",
        type=int,
        default=None,
        help="Override loop.tick_hz, which sets the per-module budget",
    )
    parser.add_argument(
        "--disable",
        type=str,
        default="",
        help="Comma-separated modules to switch off, to isolate a hot path",
    )
    parser.add_argument("--json", action="store_true", help="Print the result as JSON only")
    args = parser.parse_args(argv)

    if args.ticks < 1:
        print("[bench] --ticks must be at least 1", file=sys.stderr)
        return 2
    if args.warmup < 0:
        print("[bench] --warmup cannot be negative", file=sys.stderr)
        return 2

    config = load_config(args.config)
    if args.hz is not None:
        config.loop.tick_hz = max(1, int(args.hz))

    extra = {name.strip() for name in args.disable.split(",") if name.strip()}
    disabled = _disable(config, BENCH_DISABLED | extra)

    result = bench(config, hal or _default_fake(), args.ticks, args.warmup, disabled)
    if not result["modules"]:
        print("[bench] no module produced a timing; nothing was started", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
