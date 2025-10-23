from __future__ import annotations
import random
from packmind.behaviors.base_behavior import BaseBehavior
from packmind.core.context import AIContext


class RestingBehavior(BaseBehavior):
    """Resting behavior - minimal movement and energy recovery."""

    def execute(self, context: AIContext) -> None:
        dog = context.dog
        if not dog:
            return
        if random.random() < 0.005:
            try:
                dog.do_action("doze_off", speed=20)
            except Exception:
                pass
        context.energy_level = min(1.0, context.energy_level + 0.002)
