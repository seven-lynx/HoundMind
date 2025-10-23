from __future__ import annotations
import random
from packmind.behaviors.base_behavior import BaseBehavior
from packmind.core.context import AIContext


class ExploringBehavior(BaseBehavior):
    """Exploring behavior - active movement and head scanning."""

    def execute(self, context: AIContext) -> None:
        dog = context.dog
        if not dog:
            return
        if random.random() < 0.05:
            yaw = random.randint(-45, 45)
            try:
                dog.head_move([[yaw, 0, 0]], speed=70)
            except Exception:
                pass
        if random.random() < 0.02:
            actions = ["forward", "turn_left", "turn_right"]
            action = random.choice(actions)
            speed = 50 + int(context.energy_level * 30)
            try:
                dog.do_action(action, step_count=1, speed=speed)
            except Exception:
                pass
