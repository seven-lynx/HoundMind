from __future__ import annotations
from typing import Optional
from packmind.core.context import AIContext
from packmind.core.types import SensorReading, BehaviorState

class EnergyService:
    """
    Handles energy accounting and exposes helpers for speed decisions.
    """

    def update(self, context: AIContext, reading: SensorReading, timestamp: float, config) -> None:
        """Update energy using config-driven rates and thresholds."""
        # Configurable rates
        try:
            decay = float(getattr(config, "ENERGY_DECAY_RATE", 0.001))
        except Exception:
            decay = 0.001
        try:
            boost = float(getattr(config, "ENERGY_INTERACTION_BOOST", 0.05))
        except Exception:
            boost = 0.05
        try:
            rest_recover = float(getattr(config, "ENERGY_REST_RECOVERY", 0.0))
        except Exception:
            rest_recover = 0.0

        # Base decay
        context.energy_level = max(0.0, context.energy_level - decay)
        # Interaction boosts
        if reading.touch != "N" or reading.sound_detected:
            context.energy_level = min(1.0, context.energy_level + boost)
        # Rest recovery when resting
        try:
            if getattr(context, "behavior_state", None) == BehaviorState.RESTING and rest_recover > 0:
                context.energy_level = min(1.0, context.energy_level + rest_recover)
        except Exception:
            pass
        # Motion activity cost (gyro magnitude proxy) - keep heuristic for now
        gx, gy, gz = reading.gyroscope
        movement_activity = (abs(gx) + abs(gy) + abs(gz)) / 3000.0
        if movement_activity > 0.1:
            context.energy_level = max(0.1, context.energy_level - 0.02)

    def get_turn_speed(self, context: AIContext, config) -> int:
        high = float(getattr(config, "ENERGY_HIGH_THRESHOLD", 0.7))
        low = float(getattr(config, "ENERGY_LOW_THRESHOLD", 0.4))
        if context.energy_level > high:
            return config.SPEED_TURN_FAST
        if context.energy_level > low:
            return config.SPEED_TURN_NORMAL
        return config.SPEED_TURN_SLOW

    def get_walk_speed(self, context: AIContext, config) -> int:
        high = float(getattr(config, "ENERGY_HIGH_THRESHOLD", 0.7))
        low = float(getattr(config, "ENERGY_LOW_THRESHOLD", 0.4))
        if context.energy_level > high:
            return config.SPEED_FAST
        if context.energy_level > low:
            return config.SPEED_NORMAL
        return config.SPEED_SLOW
