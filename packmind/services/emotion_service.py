from __future__ import annotations
from typing import Dict
from packmind.core.context import AIContext
from packmind.core.types import EmotionalState, EmotionalProfile

class EmotionService:
    """
    Centralizes emotional state transitions and optional physical feedback (LED/sounds).
    """

    def __init__(self, profiles: Dict[EmotionalState, EmotionalProfile] | None = None) -> None:
        self.profiles = profiles or {}

    def compute_base_emotion(self, context: AIContext, interaction_count: int, last_interaction_time: float, now: float) -> EmotionalState:
        # Base on energy
        if context.energy_level > 0.8:
            base = EmotionalState.EXCITED
        elif context.energy_level > 0.6:
            base = EmotionalState.HAPPY
        elif context.energy_level > 0.4:
            base = EmotionalState.CALM
        elif context.energy_level > 0.2:
            base = EmotionalState.CONFUSED
        else:
            base = EmotionalState.TIRED

        # Interaction modifier
        if (now - last_interaction_time) < 30 and base != EmotionalState.TIRED:
            if interaction_count > 10:
                base = EmotionalState.EXCITED
            elif interaction_count > 5:
                base = EmotionalState.HAPPY
        return base

    def set_emotion(self, context: AIContext, emotion: EmotionalState, dog: object | None = None) -> None:
        if emotion == context.current_emotion:
            return
        old = context.current_emotion
        context.previous_emotion = old
        context.current_emotion = emotion

        profile = self.profiles.get(emotion)
        if not profile or not dog:
            return

        # Best-effort feedback (guard against missing attrs on host PCs)
        try:
            if hasattr(dog, "rgb_strip") and hasattr(dog.rgb_strip, "set_mode"):
                if profile.led_style == "boom":
                    dog.rgb_strip.set_mode(profile.led_style, profile.led_color, bps=2.0, brightness=0.8)
                else:
                    dog.rgb_strip.set_mode(profile.led_style, profile.led_color, brightness=0.7)
        except Exception:
            pass

        # Optional sound
        try:
            if hasattr(dog, "speak") and profile.sounds:
                # Keep it quiet by default here; orchestrator can choose volume
                dog.speak(profile.sounds[0], volume=60)
        except Exception:
            pass
