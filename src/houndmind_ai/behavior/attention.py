from __future__ import annotations

import logging
import time
from typing import Any


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class AttentionModule(Module):
    """Turn head toward detected sound direction.

    Uses the PiDog sound direction sensor to orient the head within safe yaw limits.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_attention_ts = 0.0

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("attention", {})
        if not settings.get("enabled", True):
            return

        perception = context.get("perception") or {}
        if not perception.get("sound"):
            return

        # Respect habituation: if sound events are habituated, skip attention
        if context.get("habituation:sound:habituated"):
            return

        now = time.time()
        cooldown = _safe_float(settings.get("sound_cooldown_s", 0.5), 0.5)
        if now - self._last_attention_ts < cooldown:
            return

        sound_direction = perception.get("sound_direction")
        if sound_direction is None:
            return

        # Optionally avoid head moves while scanning.
        if settings.get("respect_scanning", True):
            scan_reading = context.get("scan_reading")
            scan_ts = (
                _safe_float(getattr(scan_reading, "timestamp", 0.0), 0.0) if scan_reading else 0.0
            )
            block_s = _safe_float(settings.get("scan_block_s", 0.4), 0.4)
            if now - scan_ts < block_s:
                return

        yaw = _direction_to_yaw(
            sound_direction, _safe_float(settings.get("head_yaw_max_deg", 60.0), 60.0)
        )
        dog = context.get("pidog")
        if dog is None:
            return

        try:
            dog.head_move([[yaw, 0, 0]], speed=int(settings.get("head_turn_speed", 70)))
            if hasattr(dog, "wait_head_done"):
                dog.wait_head_done()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Attention head move failed: %s", exc)
            return

        self._last_attention_ts = now
        context.set("attention_active_ts", now)
        context.set(
            "led_request:attention",
            {
                "timestamp": now,
                "mode": "listen",
                "priority": int(settings.get("led_priority", 60)),
            },
        )


def _direction_to_yaw(direction: Any, yaw_max: float) -> float:
    direction = _safe_float(direction, 0.0) % 360.0
    if direction > 180:
        yaw = (direction - 360.0) / 2.0
    else:
        yaw = direction / 2.0
    return max(-yaw_max, min(yaw_max, yaw))
