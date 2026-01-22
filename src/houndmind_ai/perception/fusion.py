from __future__ import annotations

import logging
from typing import Any

from houndmind_ai.core.module import Module


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default

logger = logging.getLogger(__name__)


class PerceptionModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._context = None
        self._sensor_service = None

    def start(self, context) -> None:
        self._context = context
        service = context.get("sensor_service")
        if service is not None and hasattr(service, "subscribe"):
            self._sensor_service = service
            service.subscribe(self._on_sensor_reading)

    def tick(self, context) -> None:
        if context.get("sensor_reading") is not None:
            self._update_from_reading(context, context.get("sensor_reading"))

    def stop(self, context) -> None:
        if self._sensor_service is not None:
            try:
                self._sensor_service.unsubscribe(self._on_sensor_reading)
            except Exception:  # noqa: BLE001
                pass

    def _on_sensor_reading(self, reading) -> None:
        if self._context is None:
            return
        self._update_from_reading(self._context, reading)

    def _update_from_reading(self, context, reading) -> None:
        distance = getattr(reading, "distance_cm", None)
        touch = getattr(reading, "touch", "N")
        sound_detected = getattr(reading, "sound_detected", False)
        sound_direction = getattr(reading, "sound_direction", None)

        settings = (context.get("settings") or {}).get("perception", {})
        obstacle_cm = settings.get("obstacle_cm", 20)

        # Minimal, lightweight localization hint using IMU heading + distance
        # This is intentionally coarse — it emits a `pose_hint` into the
        # context for downstream modules to use as a soft localization cue.
        fusion_cfg = settings.get("fusion", {}) if isinstance(settings, dict) else {}
        anchor_max_cm = _safe_float(fusion_cfg.get("fusion_anchor_distance_cm", 120), 120.0)
        min_conf = _safe_float(fusion_cfg.get("fusion_min_confidence", 0.3), 0.3)

        obstacle = False
        if isinstance(distance, (int, float)) and distance > 0:
            obstacle = distance < obstacle_cm

        context.set(
            "perception",
            {
                "obstacle": obstacle,
                "touch": touch,
                "sound": bool(sound_detected),
                "sound_direction": sound_direction,
                "distance": distance,
            },
        )
        logger.debug("Perception: %s", context.get("perception"))

        # Emit pose_hint when distance is a reasonable anchor and IMU heading exists.
        try:
            if isinstance(distance, (int, float)) and 0 < distance <= anchor_max_cm:
                heading = context.get("current_heading") or (
                    context.get("orientation") or {}
                ).get("heading")
                if heading is not None:
                    hint = {
                        "timestamp": getattr(reading, "timestamp", None) or None,
                        "type": "anchor_distance",
                        "distance_cm": _safe_float(distance, 0.0),
                        "heading_deg": _safe_float(heading, 0.0),
                        "confidence": min(
                            1.0,
                            (anchor_max_cm - _safe_float(distance, 0.0)) / max(1.0, anchor_max_cm),
                        ),
                    }
                    # Apply min confidence filter.
                    if _safe_float(hint.get("confidence", 0.0), 0.0) >= min_conf:
                        context.set("pose_hint", hint)
        except Exception:
            logger.debug("pose_hint calc failed", exc_info=True)
