from __future__ import annotations

import logging
import time
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


def _number(value: Any) -> float | None:
    """A float, or `None`. `bool` is an `int` in Python, so `True` is not a reading."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class EnergyEmotionModule(Module):
    """Derives a speed hint, an emotion label and an LED request from an existing `energy_level`.

    A consumer, not a producer. `behavior/fsm.py` owns the reading and `settings.energy.enabled` is
    the switch: two modules each decaying the same number once per tick made the rate depend on
    module order rather than on either config section (#85). With no reading there is nothing to
    derive from, so this says once that the switch is off instead of inventing a value.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_led_ts = 0.0
        self._warned_no_reading = False

    def tick(self, context) -> None:
        settings = context.get("settings") or {}
        energy_cfg = settings.get("energy", {})
        emotion_cfg = settings.get("emotion", {})

        energy = _number(context.get("energy_level"))
        if energy is None:
            if not self._warned_no_reading:
                self._warned_no_reading = True
                logger.warning(
                    "No energy_level reading to derive from; settings.energy.enabled produces it"
                )
            return

        # Speed hint for movement subsystems.
        if energy >= float(energy_cfg.get("speed_fast_threshold", 0.75)):
            speed_hint = "fast"
        elif energy <= float(energy_cfg.get("speed_slow_threshold", 0.35)):
            speed_hint = "slow"
        else:
            speed_hint = "normal"
        context.set("energy_speed_hint", speed_hint)

        # Emotion state selection.
        perception = context.get("perception") or {}
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
            },
        )
