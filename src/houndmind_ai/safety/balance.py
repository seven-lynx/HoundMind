from __future__ import annotations

import logging
import math
import time

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class BalanceModule(Module):
    """IMU balance compensation using roll/pitch from accelerometer.

    Uses PiDog `set_rpy` if available to smooth walking posture.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_ts = 0.0
        self._roll_lpf = 0.0
        self._pitch_lpf = 0.0

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("balance", {})
        if not settings.get("enabled", True):
            return

        update_hz = float(settings.get("update_hz", 10.0))
        now = time.time()
        if update_hz > 0 and (now - self._last_ts) < (1.0 / update_hz):
            return
        self._last_ts = now

        if settings.get("active_when_moving", True):
            action = str(context.get("navigation_action") or "")
            allowed = settings.get(
                "active_actions",
                ["forward", "backward", "turn left", "turn right", "trot"],
            )
            if allowed and action not in allowed:
                return

        reading = context.get("sensor_reading")
        acc = getattr(reading, "acc", None) if reading else None
        if acc is None:
            sensors = context.get("sensors") or {}
            acc = sensors.get("acc")
        if acc is None or len(acc) < 3:
            return

        ax, ay, az = float(acc[0]), float(acc[1]), float(acc[2])
        # Pitch/roll in degrees.
        pitch = math.degrees(math.atan2(ay, math.sqrt(ax * ax + az * az)))
        roll = math.degrees(math.atan2(-ax, az))

        scale = float(settings.get("compensation_scale", 1.0))
        pitch *= scale
        roll *= scale

        max_pitch = float(settings.get("max_pitch_deg", 12.0))
        max_roll = float(settings.get("max_roll_deg", 12.0))
        pitch = max(-max_pitch, min(max_pitch, pitch))
        roll = max(-max_roll, min(max_roll, roll))

        alpha = float(settings.get("lpf_alpha", 0.4))
        if 0.0 < alpha <= 1.0:
            self._pitch_lpf = (1 - alpha) * self._pitch_lpf + alpha * pitch
            self._roll_lpf = (1 - alpha) * self._roll_lpf + alpha * roll
            pitch = self._pitch_lpf
            roll = self._roll_lpf

        dog = context.get("pidog")
        if dog is None:
            return
        if not hasattr(dog, "set_rpy"):
            return

        try:
            dog.set_rpy(roll=roll, pitch=pitch, yaw=0, pid=True)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Balance set_rpy failed: %s", exc)
