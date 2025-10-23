from __future__ import annotations
import random
from packmind.behaviors.base_behavior import BaseBehavior
from packmind.core.context import AIContext


class InteractingBehavior(BaseBehavior):
    """Interactive behavior - responsive movements and attention to target."""

    def execute(self, context: AIContext) -> None:
        dog = context.dog
        if not dog:
            return
        if random.random() < 0.03:
            try:
                dog.do_action("wag_tail", step_count=3, speed=90)
            except Exception:
                pass
        if context.custom_data.get("attention_target") is None and context is not None:
            # Mirror orchestrator's attribute when available
            try:
                # Keep compatibility: orchestrator stores attention_target on self
                pass
            except Exception:
                pass
        if getattr(context, "attention_target", None) is not None:
            if random.random() < 0.1:
                yaw = max(-45, min(45, (getattr(context, "attention_target") - 180) / 4))
                try:
                    dog.head_move([[int(yaw), 0, 0]], speed=80)
                except Exception:
                    pass
