"""Motionless smoke test: the runtime runs, the sensors answer, and nothing moves.

`scanning` is in `MOTIONLESS_MODULES` because it drives the head straight through the HAL rather
than through `hal_motors` (`navigation/scanning.py:178-182`) - leaving it enabled is how this tool
swept the head while the guide said nothing could move (#184).
"""

from __future__ import annotations

import argparse

from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.main import build_modules

# Everything that can move the dog: the motor module, the two that scan and walk, the behaviour FSM
# that publishes intent, and the safety stack that reacts to it. `scanning` is here for the reason in
# the module docstring. `mapping` is deliberately absent - it consumes a scan rather than producing
# one, so a motionless run leaves it with nothing to publish rather than with something to move.
MOTIONLESS_MODULES = frozenset(
    {
        "hal_motors",
        "scanning",
        "navigation",
        "behavior",
        "watchdog",
        "safety",
        "vision",
        "voice",
    }
)


def _disable_modules(config, names: frozenset[str]) -> None:
    for name in names:
        if name in config.modules:
            config.modules[name].enabled = False


def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Automated PiDog smoke test (sensors + scan + mapping)"
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to settings.jsonc"
    )
    parser.add_argument(
        "--cycles", type=int, default=20, help="Runtime cycles to execute"
    )
    parser.add_argument("--tick-hz", type=int, default=5, help="Runtime tick rate")
    parser.add_argument(
        "--include-motion",
        action="store_true",
        help="Allow navigation/motor actions (default: disabled)",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    config.loop.tick_hz = max(1, int(args.tick_hz))
    config.loop.max_cycles = max(1, int(args.cycles))

    motionless = not args.include_motion
    if motionless:
        _disable_modules(config, MOTIONLESS_MODULES)

    runtime = HoundMindRuntime(config, build_modules(config, hal=hal))
    runtime.run()

    context = runtime.context
    sensor_ok = context.get("sensor_reading") is not None
    scan_ok = context.get("scan_latest") is not None
    mapping_ok = context.get("mapping_openings") is not None

    print("[smoke] sensor_reading:", "OK" if sensor_ok else "MISSING")
    if motionless:
        # Neither key can appear in this mode: `scanning` is off, so no scan exists, and `mapping`
        # publishes from a scan. Printing MISSING would report a fault in a run that is working
        # exactly as designed, and the guide would then have to explain away its own output.
        print("[smoke] scan_latest: SKIPPED (scanning is disabled in the motionless run)")
        print("[smoke] mapping_openings: SKIPPED (nothing to consume without a scan)")
        print("[smoke] disabled:", ", ".join(sorted(MOTIONLESS_MODULES)))
        ok = sensor_ok
    else:
        print("[smoke] scan_latest:", "OK" if scan_ok else "MISSING")
        print("[smoke] mapping_openings:", "OK" if mapping_ok else "MISSING")
        ok = sensor_ok and scan_ok and mapping_ok

    print("[smoke] PASS" if ok else "[smoke] FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

