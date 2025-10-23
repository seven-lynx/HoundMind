#!/usr/bin/env python3
"""
PackMind launcher

Run the full PackMind AI demo with one command:
  python packmind.py

This wraps packmind/orchestrator.py's main().
"""
from packmind.orchestrator import main

if __name__ == "__main__":
    raise SystemExit(main())
