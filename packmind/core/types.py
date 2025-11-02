from enum import Enum
from dataclasses import dataclass
from typing import List, Tuple, Protocol, runtime_checkable, Any

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
    acceleration: Tuple[float, float, float]
    gyroscope: Tuple[float, float, float]
    timestamp: float


@dataclass
class EmotionalProfile:
    """Emotional response configuration"""
    led_color: str
    led_style: str
    sounds: List[str]
    movement_energy: float  # 0.0 to 1.0
    head_responsiveness: float


@runtime_checkable
class PidogLike(Protocol):
    """Minimal protocol for PiDog hardware used across PackMind.

    This narrows types for static analyzers without forcing a concrete dependency
    on the real pidog package.
    """
    # Common movement/head APIs
    def head_move(self, seq: List[List[int]] | Any, *, speed: int = 60) -> None: ...
    def wait_head_done(self) -> None: ...
    def do_action(self, action: str, *, step_count: int = 1, speed: int = 60, **kwargs: Any) -> bool | None: ...
    def wait_all_done(self) -> None: ...
    def body_stop(self) -> None: ...

    # Sensing
    def read_distance(self) -> float: ...

    # Lifecycle
    def close(self) -> None: ...

    # Telemetry-like attributes
    accData: Tuple[float, float, float]
    gyroData: Tuple[float, float, float]

    # Audio/voice & power
    def speak(self, sound: str, *, volume: int = 70) -> None: ...
    def power_down(self) -> None: ...
    def stop_and_lie(self) -> None: ...

    # LED strip control (minimal)
    @property
    def rgb_strip(self) -> "RgbStripLike": ...

    # Distance convenience
    @property
    def distance(self) -> float: ...

    # Exposed subcomponents used occasionally
    ultrasonic: "UltrasonicLike"
    dual_touch: "DualTouchLike"
    ears: "EarsLike"


class UltrasonicLike(Protocol):
    def read_distance(self) -> float: ...


class DualTouchLike(Protocol):
    def read(self) -> str: ...


class EarsLike(Protocol):
    def isdetected(self) -> bool: ...
    def read(self) -> int: ...


class RgbStripLike(Protocol):
    def set_mode(self, mode: str, color: str, **kwargs: Any) -> None: ...
