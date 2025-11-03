#!/usr/bin/env python3
"""
Run the PackMind Telemetry Server.

Optional deps required:
    pip install fastapi uvicorn

Usage:
    python tools/run_telemetry.py                 # uses config defaults
    python tools/run_telemetry.py --host 0.0.0.0 --port 8765
    python tools/run_telemetry.py --force         # start even if disabled in config
"""
from __future__ import annotations

import argparse
import os
import sys

# Ensure repo root in sys.path for direct execution from tools/
if __name__ == "__main__" and (__package__ is None or __package__ == ""):
    _tools_dir = os.path.abspath(os.path.dirname(__file__))
    _repo_root = os.path.abspath(os.path.join(_tools_dir, os.pardir))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

try:
    from packmind.packmind_config import load_config
    from packmind.runtime.telemetry_server import start
except Exception as e:  # pragma: no cover
    raise SystemExit(
        "Telemetry server dependencies missing or project not importable.\n"
        "Install deps with: pip install fastapi uvicorn\n"
        f"Error: {e}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="PackMind Telemetry Server")
    p.add_argument("--host", default=None, help="Host override (defaults to config)")
    p.add_argument("--port", default=None, type=int, help="Port override (defaults to config)")
    p.add_argument("--force", action="store_true", help="Run even if TELEMETRY_ENABLED is False")
    args = p.parse_args(argv)

    cfg = load_config()
    # Resolve enable flag
    enabled = bool(getattr(cfg, "TELEMETRY_ENABLED", True))
    if not enabled and not args.force:
        print("[telemetry] TELEMETRY_ENABLED is False in config. Use --force to start anyway.")
        return 1

    # Resolve host/port from config with CLI overrides
    host = args.host or str(getattr(cfg, "TELEMETRY_HOST", "127.0.0.1"))
    try:
        port = int(args.port if args.port is not None else getattr(cfg, "TELEMETRY_PORT", 8765))
    except Exception:
        port = 8765

    basic_auth = getattr(cfg, "TELEMETRY_BASIC_AUTH", None)
    print(f"[telemetry] Starting server on {host}:{port} (enabled={enabled})")
    if basic_auth:
        print("[telemetry] Basic auth configured in TELEMETRY_BASIC_AUTH (user:pass).")

    # TELEMETRY_BASIC_AUTH may be None or a tuple (user, pass)
    try:
        ba = tuple(basic_auth) if basic_auth else None  # type: ignore[assignment]
    except Exception:
        ba = None
    start(host=host, port=port, basic_auth=ba)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
