from __future__ import annotations
import random
from packmind.behaviors.base_behavior import BaseBehavior
from packmind.core.context import AIContext

class PatrollingBehavior(BaseBehavior):
    """
    Intelligent patrol that will eventually leverage scan data and navigation.
    For now, it keeps the dog moving forward with occasional turns.
    """

    def on_enter(self, context: AIContext) -> None:
        context.custom_data["patrol_start"] = context.custom_data.get("time", 0.0)

    def execute(self, context: AIContext) -> None:
        dog = context.dog
        if not dog:
            return
        # Basic forward-biased movement placeholder
        try:
            if random.random() < 0.75:
                dog.do_action("forward", step_count=1, speed=70)
            else:
                dog.do_action(random.choice(["turn_left", "turn_right"]), step_count=1, speed=70)
        except Exception:
            pass

    def on_exit(self, context: AIContext) -> None:
        pass
