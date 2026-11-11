from __future__ import annotations

import logging
import math
import time

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.commands import canonical_action

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
            # What the actuators are actually doing, not what a producer happened to put in a
            # context key: `motion_command` is the gateway's single output.
            command = context.get("motion_command") or {}
            action = str(
                command.get("canonical_action") or canonical_action(str(command.get("action") or ""))
            )
            allowed = settings.get(
                "active_actions",
                ["forward", "backward", "turn left", "turn right", "trot"],
            )
            # The configured list is written the way the dog spells it ("turn left"); compare
            # in the canonical vocabulary so both spellings mean the same action.
            allowed_canonical = [canonical_action(str(entry)) for entry in allowed or []]
            if allowed_canonical and action not in allowed_canonical:
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

        hal = context.get("hal")
        if hal is None:
            return

        try:
            hal.action("rpy", {"roll": roll, "pitch": pitch, "yaw": 0})
        except Exception as exc:  # noqa: BLE001
            logger.debug("Balance set_rpy failed: %s", exc)
