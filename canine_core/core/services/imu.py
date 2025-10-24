from __future__ import annotations
from typing import Any, Optional, Tuple


class IMUService:
    """Thin wrapper for IMU readings if available from the hardware.

    Provides orientation estimates and simple tilt checks. Sim-safe.
    """

    def __init__(self, hardware: Any) -> None:
        self._hardware = hardware

    def read_accel(self) -> Optional[Tuple[float, float, float]]:
        dog = getattr(self._hardware, "dog", None)
        if dog is None:
            return None
        try:
            if hasattr(dog, "imu_accel"):
                ax, ay, az = dog.imu_accel()
                return (float(ax), float(ay), float(az))
        except Exception:
            return None
        return None

    def read_gyro(self) -> Optional[Tuple[float, float, float]]:
        dog = getattr(self._hardware, "dog", None)
        if dog is None:
            return None
        try:
            if hasattr(dog, "imu_gyro"):
                gx, gy, gz = dog.imu_gyro()
                return (float(gx), float(gy), float(gz))
        except Exception:
            return None
        return None

    def is_tilt_excessive(self, max_tilt_deg: float = 45.0) -> Optional[bool]:
        # Placeholder: without fused orientation, approximate via accel Z
        acc = self.read_accel()
        if acc is None:
            return None
        ax, ay, az = acc
        # If az (gravity on Z) is very small, consider it tilted
        try:
            g = (ax**2 + ay**2 + az**2) ** 0.5
            if g <= 1e-6:
                return None
            vertical_ratio = abs(az) / g
            # Tilt angle from vertical: acos(vertical_ratio) in degrees
            import math
            tilt_deg = math.degrees(math.acos(max(0.0, min(1.0, vertical_ratio))))
            return tilt_deg >= float(max_tilt_deg)
        except Exception:
            return None
