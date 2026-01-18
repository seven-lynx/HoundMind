from __future__ import annotations

import logging
import time

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class EnergyEmotionModule(Module):
    """Optional lightweight energy/emotion tracker.

    Emits `energy_level`, `energy_speed_hint`, and `emotion_state` into context.
    Optionally updates PiDog LEDs for emotion feedback.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_led_ts = 0.0

    def tick(self, context) -> None:
        settings = context.get("settings") or {}
        energy_cfg = settings.get("energy", {})
        emotion_cfg = settings.get("emotion", {})

        energy = context.get("energy_level")
        try:
            energy = (
                float(energy)
                if energy is not None
                else float(energy_cfg.get("initial", 0.6))
            )
        except Exception:
            energy = 0.6

        decay = float(energy_cfg.get("decay_per_tick", 0.01))
        boost_touch = float(energy_cfg.get("boost_touch", 0.08))
        boost_sound = float(energy_cfg.get("boost_sound", 0.05))
        boost_obstacle = float(energy_cfg.get("boost_obstacle", 0.02))
        min_energy = float(energy_cfg.get("min", 0.0))
        max_energy = float(energy_cfg.get("max", 1.0))

        perception = context.get("perception") or {}
        if perception.get("touch") not in (None, "N"):
            energy += boost_touch
        if perception.get("sound"):
            energy += boost_sound
        if perception.get("obstacle"):
            energy += boost_obstacle
        energy = max(min_energy, min(max_energy, energy - decay))

        context.set("energy_level", energy)

        # Speed hint for movement subsystems.
        if energy >= float(energy_cfg.get("speed_fast_threshold", 0.75)):
            speed_hint = "fast"
        elif energy <= float(energy_cfg.get("speed_slow_threshold", 0.35)):
            speed_hint = "slow"
        else:
            speed_hint = "normal"
        context.set("energy_speed_hint", speed_hint)

        # Emotion state selection.
        if perception.get("obstacle") or perception.get("sound"):
            emotion_state = "alert"
        elif energy <= 0.3:
            emotion_state = "tired"
        elif energy >= 0.8:
            emotion_state = "excited"
        else:
            emotion_state = "calm"
        context.set("emotion_state", emotion_state)

        # Optional LED request.
        if not emotion_cfg.get("led_enabled", False):
            return
        now = time.time()
        cooldown = float(emotion_cfg.get("led_cooldown_s", 1.0))
        if now - self._last_led_ts < cooldown:
            return
        self._last_led_ts = now
        context.set(
            "led_request:emotion",
            {
                "timestamp": now,
                "mode": emotion_state,
                "priority": int(emotion_cfg.get("led_priority", 40)),
            },
        )
