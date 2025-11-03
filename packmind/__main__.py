#!/usr/bin/env python3
"""
PackMind module entry point.

Allows running with:
  python -m packmind

This simply delegates to orchestrator.main().
"""
from .orchestrator import main

if __name__ == "__main__":
    raise SystemExit(main())
