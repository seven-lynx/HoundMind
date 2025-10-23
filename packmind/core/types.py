from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple

class EmotionalState(Enum):
    """PiDog emotional states"""
    HAPPY = "happy"
    CALM = "calm"
    ALERT = "alert"
    CONFUSED = "confused"
    TIRED = "tired"
    EXCITED = "excited"


class BehaviorState(Enum):
    """High-level behavior states"""
    IDLE = "idle"
    EXPLORING = "exploring"
    PATROLLING = "patrolling"
    INTERACTING = "interacting"
    AVOIDING = "avoiding"
    RESTING = "resting"
    PLAYING = "playing"
    CALIBRATING = "calibrating"


@dataclass
class SensorReading:
    """Consolidated sensor data"""
    distance: float
    touch: str
    sound_detected: bool
    sound_direction: int
    acceleration: Tuple[int, int, int]
    gyroscope: Tuple[int, int, int]
    timestamp: float


@dataclass
class EmotionalProfile:
    """Emotional response configuration"""
    led_color: str
    led_style: str
    sounds: List[str]
    movement_energy: float  # 0.0 to 1.0
    head_responsiveness: float
