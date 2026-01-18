from __future__ import annotations

import logging
import time

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class OrientationModule(Module):
    """Integrate IMU gyro Z into a heading estimate (0-360)."""

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_ts: float | None = None
        self._heading_deg = 0.0
        self._context = None
        self._sensor_service = None

    def start(self, context) -> None:
        self._context = context
        settings = (context.get("settings") or {}).get("orientation", {})
        initial = float(settings.get("initial_heading_deg", 0.0))
        self._heading_deg = initial % 360.0
        context.set("current_heading", self._heading_deg)
        service = context.get("sensor_service")
        if service is not None and hasattr(service, "subscribe"):
            self._sensor_service = service
            service.subscribe(self._on_sensor_reading)
        if settings.get("calibration_enabled", True):
            self._calibrate_bias(context, settings)

    def tick(self, context) -> None:
        reading = context.get("sensor_reading")
        if reading is not None:
            self._update_from_reading(context, reading)

    def stop(self, context) -> None:
        if self._sensor_service is not None:
            try:
                self._sensor_service.unsubscribe(self._on_sensor_reading)
            except Exception:  # noqa: BLE001
                pass
        self._sensor_service = None
        self._last_ts = None

    def _on_sensor_reading(self, reading) -> None:
        if self._context is None:
            return
        self._update_from_reading(self._context, reading)

    def _update_from_reading(self, context, reading) -> None:
        gyro = getattr(reading, "gyro", None)
        ts = float(getattr(reading, "timestamp", time.time()))
        if gyro is None:
            return
        try:
            gz = float(gyro[2])
        except Exception:
            return

        settings = (context.get("settings") or {}).get("orientation", {})
        scale = float(settings.get("gyro_scale", 1.0))
        bias = float(context.get("orientation_bias_z") or settings.get("bias_z", 0.0))

        if self._last_ts is None:
            self._last_ts = ts
            return
        dt = max(0.0, ts - self._last_ts)
        self._last_ts = ts

        gz_corrected = (gz - bias) * scale
        self._heading_deg = (self._heading_deg + gz_corrected * dt) % 360.0
        context.set("current_heading", self._heading_deg)

    def _calibrate_bias(self, context, settings: dict[str, object]) -> None:
        settle_s = float(settings.get("calibration_settle_s", 0.0))
        duration_s = float(settings.get("calibration_duration_s", 2.0))
        max_samples = int(settings.get("calibration_samples", 30))
        start = time.time()
        if settle_s > 0:
            time.sleep(settle_s)
        samples: list[float] = []

        while time.time() - start < duration_s and len(samples) < max_samples:
            reading = context.get("sensor_reading")
            if reading is None:
                time.sleep(0.05)
                continue
            gyro = getattr(reading, "gyro", None)
            if gyro is None:
                time.sleep(0.05)
                continue
            try:
                samples.append(float(gyro[2]))
            except Exception:
                pass
            time.sleep(0.05)

        if not samples:
            context.set("orientation_calibration_ok", False)
            logger.warning("Orientation calibration failed: no samples")
            return
        bias = sum(samples) / len(samples)
        max_bias = float(settings.get("calibration_max_bias_abs", 0.0))
        if max_bias > 0:
            if bias > max_bias:
                bias = max_bias
            elif bias < -max_bias:
                bias = -max_bias
        context.set("orientation_bias_z", bias)
        context.set("orientation_calibration_ok", True)
        logger.info(
            "Orientation bias calibrated: %.3f (%d samples)", bias, len(samples)
        )
