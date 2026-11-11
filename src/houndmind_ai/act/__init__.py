"""The actuator boundary: every motion command passes through `act.interlock` first."""

from __future__ import annotations

from houndmind_ai.act.interlock import Interlock, InterlockLimits

__all__ = ["Interlock", "InterlockLimits"]