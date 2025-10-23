from __future__ import annotations
import random
from packmind.behaviors.base_behavior import BaseBehavior
from packmind.core.context import AIContext

class IdleBehavior(BaseBehavior):
    """Occasional subtle movements while conserving energy."""

    def on_enter(self, context: AIContext) -> None:
        pass

    def execute(self, context: AIContext) -> None:
        dog = context.dog
        if not dog:
            return
        if random.random() < 0.01:
            action = random.choice(["tilting_head", "head_up_down"])
            speed = int(30 + context.energy_level * 40)
            try:
                dog.do_action(action, step_count=1, speed=speed)
            except Exception:
                pass

    def on_exit(self, context: AIContext) -> None:
        pass
