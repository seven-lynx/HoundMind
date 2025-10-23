from __future__ import annotations
import random
from packmind.behaviors.base_behavior import BaseBehavior
from packmind.core.context import AIContext


class PlayingBehavior(BaseBehavior):
    """Playing behavior - energetic and fun movements."""

    def execute(self, context: AIContext) -> None:
        dog = context.dog
        if not dog:
            return
        if random.random() < 0.05:
            actions = ["wag_tail", "head_up_down", "tilting_head", "shake_head"]
            action = random.choice(actions)
            speed = 70 + int(context.energy_level * 30)
            steps = random.randint(2, 5)
            try:
                dog.do_action(action, step_count=steps, speed=speed)
            except Exception:
                pass
        if random.random() < 0.02:
            moves = ["push_up", "stretch", "trot"]
            move = random.choice(moves)
            try:
                dog.do_action(move, step_count=2, speed=80)
            except Exception:
                pass
