"""
pidog_sim — explicit simulator alias for the PiDog library.

Usage:
  from pidog_sim import Pidog

This guarantees the simulator is used (it sets HOUNDMIND_SIM=1) regardless of
whether the real pidog package is installed. It reuses the shim logic located
in our 'pidog' package.
"""
from __future__ import annotations

import os as _os

# Force simulator mode for the underlying shim.
_os.environ.setdefault("HOUNDMIND_SIM", "1")

# Import everything from our shim package.
from pidog import *  # noqa: F401,F403
