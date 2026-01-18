from __future__ import annotations

import logging
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BehaviorLibraryConfig:
    """Configuration for behavior sequences and weights."""

    idle_actions: list[str]
    alert_actions: list[str]
    avoid_actions: list[str]
    play_actions: list[str]
    rest_actions: list[str]
    patrol_actions: list[str]
    explore_actions: list[str]
    interact_actions: list[str]
    random_idle_chance: float = 0.05


class BehaviorLibrary:
    """Reusable behavior patterns that rely on PiDog ActionFlow actions."""

    def __init__(self, config: BehaviorLibraryConfig) -> None:
        self.config = config

    def pick_idle_action(self) -> str:
        """Pick a default idle action, occasionally adding variety."""
        if self.config.idle_actions:
            if random.random() < self.config.random_idle_chance:
                return random.choice(self.config.idle_actions)
            return self.config.idle_actions[0]
        return "stand"

    def pick_alert_action(self) -> str:
        return random.choice(self.config.alert_actions)

    def pick_avoid_action(self) -> str:
        return random.choice(self.config.avoid_actions)

    def pick_play_action(self) -> str:
        return random.choice(self.config.play_actions)

    def pick_rest_action(self) -> str:
        return random.choice(self.config.rest_actions)

    def pick_patrol_action(self) -> str:
        return random.choice(self.config.patrol_actions)

    def pick_explore_action(self) -> str:
        return random.choice(self.config.explore_actions)

    def pick_interact_action(self) -> str:
        return random.choice(self.config.interact_actions)
