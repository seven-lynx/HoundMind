#!/usr/bin/env python3
"""
Run the PackMind Telemetry Server.

Optional deps required:
  pip install fastapi uvicorn

Usage:
  python3 tools/run_telemetry.py --host 0.0.0.0 --port 8765
"""
from __future__ import annotations

import argparse

try:
    from packmind.runtime.telemetry_server import start
except Exception as e:  # pragma: no cover
    raise SystemExit(
        "Telemetry server dependencies missing. Install with: pip install fastapi uvicorn\n"
        f"Error: {e}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="PackMind Telemetry Server")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", default=8765, type=int)
    args = p.parse_args(argv)
    start(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
