from dataclasses import dataclass, field
from typing import Optional, Any

# Type-only imports for enums and base behavior
from packmind.behaviors.base_behavior import BaseBehavior
from packmind.core.types import EmotionalState, BehaviorState

@dataclass
class AIContext:
    """
    A shared context object holding the AI's state, accessible by the orchestrator,
    services, and behaviors.
    """
    # Core hardware abstraction (Pidog hardware object at runtime)
    # Keep as Any to avoid cross-package analyzer issues; runtime guards are in place
    dog: Optional[Any] = None

    # Emotional State
    current_emotion: EmotionalState = EmotionalState.CALM
    previous_emotion: EmotionalState = EmotionalState.CALM
    emotion_intensity: float = 0.5

    # Energy Management
    energy_level: float = 100.0
    is_sleeping: bool = False

    # Sensory Input
    last_heard_sound: Optional[Any] = None
    last_seen_face: Optional[Any] = None
    detected_obstacle: bool = False
    obstacle_distance: float = float('inf')

    # Operational State
    is_awake: bool = True
    current_behavior: Optional[BaseBehavior] = None 
    behavior_state: BehaviorState = BehaviorState.IDLE
    user_command: Optional[str] = None
    is_running: bool = True

    # Mapping and Navigation
    current_location: tuple[float, float] = (0, 0)
    current_heading: float = 0.0
    house_map: Optional[Any] = None # Placeholder for the map object

    # Custom data storage for services or behaviors
    custom_data: dict[str, Any] = field(default_factory=dict)

    def set_value(self, key: str, value: Any):
        """Set a value in the custom data dictionary."""
        self.custom_data[key] = value

    def get_value(self, key: str, default: Any = None) -> Any:
        """Get a value from the custom data dictionary."""
        return self.custom_data.get(key, default)
