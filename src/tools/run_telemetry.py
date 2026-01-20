from __future__ import annotations

import argparse

from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.main import build_modules


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run HoundMind with telemetry dashboard enabled"
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to settings.jsonc"
    )
    parser.add_argument(
        "--host", type=str, default=None, help="Telemetry host override"
    )
    parser.add_argument(
        "--port", type=int, default=None, help="Telemetry port override"
    )
    parser.add_argument(
        "--tick-hz", type=int, default=None, help="Runtime tick rate override"
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="Max runtime cycles (omit for continuous)",
    )
    args = parser.parse_args()

    config = load_config(args.config)

    if args.tick_hz is not None:
        config.loop.tick_hz = max(1, int(args.tick_hz))
    if args.cycles is not None:
        config.loop.max_cycles = None if args.cycles <= 0 else int(args.cycles)

    if "telemetry_dashboard" in config.modules:
        config.modules["telemetry_dashboard"].enabled = True

    telemetry_settings = (config.settings or {}).setdefault("telemetry_dashboard", {})
    telemetry_settings["enabled"] = True
    http_settings = telemetry_settings.setdefault("http", {})
    http_settings["enabled"] = True
    if args.host:
        http_settings["host"] = args.host
    if args.port:
        http_settings["port"] = int(args.port)

    runtime = HoundMindRuntime(config, build_modules(config))
    runtime.run()


if __name__ == "__main__":
    main()
