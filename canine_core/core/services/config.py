from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import List
try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # optional dependency; defaults used if missing

@dataclass
class CoreConfig:
    enable_voice_commands: bool = True
    enable_slam_mapping: bool = True
    enable_sensor_fusion: bool = True
    enable_emotional_system: bool = True
    enable_learning_system: bool = True
    enable_autonomous_navigation: bool = True
    behavior_queue: List[str] = field(default_factory=list)  # dotted module paths or canonical names
    interrupt_key: str = "esc"


def load_config(config_path: str) -> CoreConfig:
    if not os.path.exists(config_path):
        return CoreConfig(behavior_queue=[
            "canine_core.behaviors.idle_behavior",
        ])
    if yaml is None:
        # YAML not available; return defaults and warn via print
        print("[Config] PyYAML not installed; using default configuration.")
        return CoreConfig(behavior_queue=[
            "canine_core.behaviors.idle_behavior",
        ])
    with open(config_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return CoreConfig(
        enable_voice_commands=data.get("enable_voice_commands", True),
        enable_slam_mapping=data.get("enable_slam_mapping", True),
        enable_sensor_fusion=data.get("enable_sensor_fusion", True),
        enable_emotional_system=data.get("enable_emotional_system", True),
        enable_learning_system=data.get("enable_learning_system", True),
        enable_autonomous_navigation=data.get("enable_autonomous_navigation", True),
        behavior_queue=data.get("behavior_queue", [
            "canine_core.behaviors.idle_behavior",
        ]),
        interrupt_key=data.get("interrupt_key", "esc"),
    )
