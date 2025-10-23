"""
Validated state store for CanineCore with simple transitions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
import time

VALID_MODE_TRANSITIONS = {
    "idle": ["patrol", "reacting", "sleeping"],
    "patrol": ["idle", "reacting"],
    "reacting": ["idle", "patrol"],
    "sleeping": ["idle"],
}

@dataclass
class StateStore:
    position: str = "standing"
    emotion: str = "neutral"
    speed: int = 80
    idle_behavior: bool = True
    obstacle_memory: List = field(default_factory=list)
    sound_direction: int | None = None
    touch_count: int = 0
    interaction_history: List = field(default_factory=list)
    battery_level: int = 100
    active_mode: str = "idle"
    environment_status: str = "clear"
    error_log: List = field(default_factory=list)

    def set(self, key: str, value):
        if key == "active_mode":
            if value not in VALID_MODE_TRANSITIONS.get(self.active_mode, []):
                self.log_error(f"Invalid transition {self.active_mode} → {value}")
                return False
        setattr(self, key, value)
        return True

    def log_error(self, msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.error_log.append({"timestamp": ts, "error": msg})
