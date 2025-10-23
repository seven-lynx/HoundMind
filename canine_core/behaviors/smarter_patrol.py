#!/usr/bin/env python3
"""
Smarter Patrol has been combined into SmartPatrolBehavior.
This module re-exports the same behavior for backward-compatibility.
"""
from __future__ import annotations

from .smart_patrol import SmartPatrolBehavior as _SmartPatrolBehavior


BEHAVIOR_CLASS = _SmartPatrolBehavior
