from __future__ import annotations

import logging
import time
from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)

class SensorHealthModule(Module):
    """Monitors sensor health and updates LED/logs based on config thresholds."""
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_status = None
        self._last_led = None
        self._last_log_ts = 0.0

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("sensor_health", {})
        if not settings.get("enabled", False):
            return
        now = time.time()
        # Get latest sensor readings
        sensor = context.get("sensor_reading")
        if not sensor:
            return
        # Check staleness for each sensor type
        status = "ok"
        details = {}
        warn = False
        # Ultrasonic
        us_stale = now - getattr(sensor, "timestamp", 0) > float(settings.get("ultrasonic_stale_s", 1.0))
        if us_stale or not getattr(sensor, "distance_valid", True):
            warn = True
            details["ultrasonic"] = "stale" if us_stale else "invalid"
        # IMU
        imu_stale = now - getattr(sensor, "timestamp", 0) > float(settings.get("imu_stale_s", 1.0))
        if imu_stale or not getattr(sensor, "imu_valid", True):
            warn = True
            details["imu"] = "stale" if imu_stale else "invalid"
        # Touch
        touch_stale = now - getattr(sensor, "timestamp", 0) > float(settings.get("touch_stale_s", 1.0))
        if touch_stale or not getattr(sensor, "touch_valid", True):
            warn = True
            details["touch"] = "stale" if touch_stale else "invalid"
        # Sound
        sound_stale = now - getattr(sensor, "timestamp", 0) > float(settings.get("sound_stale_s", 1.0))
        if sound_stale or not getattr(sensor, "sound_valid", True):
            warn = True
            details["sound"] = "stale" if sound_stale else "invalid"
        # Determine status
        if warn:
            status = "warning"
        if settings.get("error_is_critical", True) and (not getattr(sensor, "distance_valid", True) or not getattr(sensor, "imu_valid", True)):
            status = "error"
        # LED color
        led_color = settings.get("led_ok_color", "green")
        if status == "warning":
            led_color = settings.get("led_warning_color", "yellow")
        if status == "error":
            led_color = settings.get("led_error_color", "red")
        # Update LED if changed
        if led_color != self._last_led:
            context.set("led_request:health", {"mode": "health", "color": led_color})
            self._last_led = led_color
        # Log if changed or periodically
        if (self._last_status != status or now - self._last_log_ts > 10) and settings.get("log_enabled", True):
            logger.info(f"Sensor health status: {status} details: {details}")
            self._last_log_ts = now
        self._last_status = status
