from __future__ import annotations

import argparse
import sys

from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.main import build_modules


def _disable_modules(config, names: set[str]) -> None:
    for name in names:
        if name in config.modules:
            config.modules[name].enabled = False


def main() -> None:
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
    args = parser.parse_args()

    config = load_config(args.config)
    config.loop.tick_hz = max(1, int(args.tick_hz))
    config.loop.max_cycles = max(1, int(args.cycles))

    if not args.include_motion:
        _disable_modules(
            config,
            {
                "hal_motors",
                "navigation",
                "behavior",
                "watchdog",
                "safety",
                "vision",
                "voice",
            },
        )

    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.run()

    context = runtime.context
    sensor_ok = context.get("sensor_reading") is not None
    scan_ok = context.get("scan_latest") is not None
    mapping_ok = context.get("mapping_openings") is not None

    print("[smoke] sensor_reading:", "OK" if sensor_ok else "MISSING")
    print("[smoke] scan_latest:", "OK" if scan_ok else "MISSING")
    print("[smoke] mapping_openings:", "OK" if mapping_ok else "MISSING")

    if sensor_ok and scan_ok and mapping_ok:
        print("[smoke] PASS")
        sys.exit(0)
    print("[smoke] FAIL")
    sys.exit(1)


if __name__ == "__main__":
    main()
