from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
import time
import math


class TelemetryService:
    """Lightweight telemetry collector that logs periodic snapshots.

    Sim-safe: if no hardware readings available, logs minimal info.
    """

    def __init__(self, hardware: Any, logger: Any, interval_s: float = 10.0,
                 imu: Any | None = None, battery: Any | None = None) -> None:
        self._hardware = hardware
        self._logger = logger
        self.interval_s = float(interval_s)
        self._last = 0.0
        self._imu = imu
        self._battery = battery

    def snapshot(self) -> Dict[str, Any]:
        dog = getattr(self._hardware, "dog", None)
        data: Dict[str, Any] = {"ts": time.time()}
        if dog is None:
            return data
        try:
            if hasattr(dog, "read_distance"):
                data["front_cm"] = float(dog.read_distance() or 0.0)
        except Exception:
            pass
        # Battery percentage if available via BatteryService
        try:
            if self._battery is not None:
                pct = self._battery.read_percentage()
                if pct is not None:
                    data["battery_pct"] = float(pct)
        except Exception:
            pass
        # IMU tilt estimate (degrees from vertical) if accel available
        try:
            if self._imu is not None and hasattr(self._imu, "read_accel"):
                acc = self._imu.read_accel()
                if acc is not None:
                    ax, ay, az = acc  # type: ignore[misc]
                    g = math.sqrt(ax * ax + ay * ay + az * az)
                    if g > 1e-6:
                        vertical_ratio = min(1.0, max(0.0, abs(az) / g))
                        data["tilt_deg"] = float(math.degrees(math.acos(vertical_ratio)))
        except Exception:
            pass
        # Head orientation if available
        try:
            if hasattr(dog, "head_current_angles"):
                angles = dog.head_current_angles  # [yaw, roll, pitch]
                if isinstance(angles, (list, tuple)) and len(angles) >= 3:
                    data["head_yaw"] = float(angles[0])
                    data["head_roll"] = float(angles[1])
                    data["head_pitch"] = float(angles[2])
        except Exception:
            pass
        return data

    def maybe_log(self) -> None:
        now = time.time()
        if now - self._last < self.interval_s:
            return
        self._last = now
        try:
            snap = self.snapshot()
            self._logger.info(f"telemetry: {snap}")
        except Exception:
            pass
