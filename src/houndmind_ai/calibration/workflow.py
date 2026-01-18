from __future__ import annotations

import logging
import time
from typing import Any
from pathlib import Path
import json

from houndmind_ai.calibration.servo_calibration import collect_servo_defaults
from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class CalibrationModule(Module):
    """Lightweight calibration workflow runner.

    Calibration is triggered via `context['calibration_request']` or
    `settings.calibration.request` when provided. This module emits a
    `calibration_result` and may update `localization_confidence` in context.
    """

    def __init__(
        self, name: str = "calibration", enabled: bool = True, required: bool = False
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_request: str | None = None

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("calibration", {})
        request = context.get("calibration_request") or settings.get("request")
        if not request:
            return
        request = str(request)
        # Avoid re-running the same request every tick.
        if request == self._last_request:
            return
        self._last_request = request

        if request == "servo_zero":
            result = self._calibrate_servo_zero(context)
        elif request == "wall_follow":
            result = self._calibrate_wall_follow(context, settings)
        elif request == "corner_seek":
            result = self._calibrate_corner_seek(context, settings)
        elif request == "landmark_align":
            result = self._calibrate_landmark_align(context, settings)
        else:
            result = {"timestamp": time.time(), "request": request, "status": "unknown"}

        context.set("calibration_result", result)
        self._persist_result(result, settings)
        if result.get("status") == "ok":
            self._bump_localization_confidence(context, settings)
        logger.info("Calibration request=%s result=%s", request, result.get("status"))

    def _calibrate_servo_zero(self, context) -> dict[str, Any]:
        dog = context.get("pidog")
        offsets = collect_servo_defaults(dog)
        return {
            "timestamp": time.time(),
            "request": "servo_zero",
            "status": "ok" if offsets else "no_data",
            "servo_zero_offsets": offsets,
        }

    def _calibrate_wall_follow(
        self, context, settings: dict[str, Any]
    ) -> dict[str, Any]:
        target_cm = float(settings.get("wall_follow_target_distance_cm", 30.0))
        sensors = context.get("sensors") or {}
        distance = sensors.get("distance")
        if not isinstance(distance, (int, float)):
            return {
                "timestamp": time.time(),
                "request": "wall_follow",
                "status": "no_data",
            }
        error_cm = float(distance) - target_cm
        return {
            "timestamp": time.time(),
            "request": "wall_follow",
            "status": "ok",
            "target_distance_cm": target_cm,
            "measured_distance_cm": float(distance),
            "distance_error_cm": error_cm,
        }

    def _calibrate_corner_seek(
        self, context, settings: dict[str, Any]
    ) -> dict[str, Any]:
        turn_deg = float(settings.get("corner_seek_turn_deg", 45.0))
        scan_latest = context.get("scan_latest") or {}
        angles = scan_latest.get("angles", {}) if isinstance(scan_latest, dict) else {}
        best_angle = None
        best_distance = -1.0
        for key, val in angles.items():
            try:
                yaw = float(key)
                dist = float(val)
            except Exception:
                continue
            if dist > best_distance:
                best_distance = dist
                best_angle = yaw
        return {
            "timestamp": time.time(),
            "request": "corner_seek",
            "status": "ok" if best_angle is not None else "no_data",
            "turn_degrees": turn_deg,
            "best_angle": best_angle,
            "best_distance_cm": best_distance,
        }

    def _calibrate_landmark_align(
        self, context, settings: dict[str, Any]
    ) -> dict[str, Any]:
        min_conf = float(settings.get("landmark_alignment_confidence_min", 0.6))
        pose_hint = context.get("pose_hint") or {}
        conf = (
            float(pose_hint.get("confidence", 0.0))
            if isinstance(pose_hint, dict)
            else 0.0
        )
        status = "ok" if conf >= min_conf else "no_data"
        return {
            "timestamp": time.time(),
            "request": "landmark_align",
            "status": status,
            "confidence": conf,
        }

    def _bump_localization_confidence(self, context, settings: dict[str, Any]) -> None:
        bump = float(settings.get("localization_confidence_bump", 0.1))
        if bump <= 0:
            return
        current = context.get("localization_confidence")
        try:
            current_val = float(current) if current is not None else 0.0
        except Exception:
            current_val = 0.0
        context.set("localization_confidence", min(1.0, current_val + bump))

    def _persist_result(self, result: dict[str, Any], settings: dict[str, Any]) -> None:
        if not settings.get("persist_enabled", True):
            return
        path = Path(str(settings.get("persist_path", "data/calibration.json")))
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_result": result, "updated_at": time.time()}
        try:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.debug("Failed to persist calibration", exc_info=True)
