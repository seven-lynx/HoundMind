from __future__ import annotations
from typing import Optional
from packmind.core.context import AIContext
from packmind.core.types import SensorReading

class EnergyService:
    """
    Handles energy accounting and exposes helpers for speed decisions.
    """

    def update(self, context: AIContext, reading: SensorReading, timestamp: float) -> None:
        # Base decay
        context.energy_level = max(0.0, context.energy_level - 0.001)
        # Interaction boosts
        if reading.touch != "N" or reading.sound_detected:
            context.energy_level = min(1.0, context.energy_level + 0.05)
        # Motion activity cost (gyro magnitude proxy)
        gx, gy, gz = reading.gyroscope
        movement_activity = (abs(gx) + abs(gy) + abs(gz)) / 3000.0
        if movement_activity > 0.1:
            context.energy_level = max(0.1, context.energy_level - 0.02)

    def get_turn_speed(self, context: AIContext, config) -> int:
        if context.energy_level > 0.7:
            return config.SPEED_TURN_FAST
        if context.energy_level > 0.4:
            return config.SPEED_TURN_NORMAL
        return config.SPEED_TURN_SLOW

    def get_walk_speed(self, context: AIContext, config) -> int:
        if context.energy_level > 0.7:
            return config.SPEED_FAST
        if context.energy_level > 0.4:
            return config.SPEED_NORMAL
        return config.SPEED_SLOW
