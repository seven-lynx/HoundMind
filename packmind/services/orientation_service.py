from __future__ import annotations
import time
from typing import Optional

from packmind.core.context import AIContext
from packmind.core.types import SensorReading


class OrientationService:
    """
    Lightweight yaw integrator using gyroscope Z to maintain a heading estimate.

    - Updates AIContext.current_heading (degrees, 0-360 wrap)
    - Uses configurable bias and scale to adapt to hardware units
    - Call update_from_reading() with each SensorReading
    """

    def __init__(self, context: AIContext, config: Optional[object] = None) -> None:
        self._ctx = context
        self._config = config
        self._heading_deg: float = 0.0
        self._last_ts: Optional[float] = None
        # Configurable params (safe defaults)
        self._scale = 1.0  # units -> deg/s
        self._bias_z = 0.0  # constant offset in units
        try:
            if config is not None:
                self._scale = float(getattr(config, "ORIENTATION_GYRO_SCALE", self._scale))
                self._bias_z = float(getattr(config, "ORIENTATION_BIAS_Z", self._bias_z))
        except Exception:
            pass

    def reset(self, heading_deg: float = 0.0) -> None:
        self._heading_deg = float(heading_deg) % 360.0
        self._ctx.current_heading = self._heading_deg
        self._last_ts = None

    def update_from_reading(self, reading: SensorReading) -> None:
        """Integrate gyroscope Z into heading and update context."""
        try:
            gz_units = float(reading.gyroscope[2])
            ts = float(reading.timestamp or time.time())
        except Exception:
            return
        if self._last_ts is None:
            self._last_ts = ts
            return
        dt = max(0.0, ts - self._last_ts)
        self._last_ts = ts
        # Convert to deg/s using scale and subtract bias before scaling when appropriate
        gz_corrected = (gz_units - self._bias_z) * self._scale
        delta_deg = gz_corrected * dt
        self._heading_deg = (self._heading_deg + delta_deg) % 360.0
        # Publish to context
        self._ctx.current_heading = self._heading_deg

    def get_heading_deg(self) -> float:
        return float(self._heading_deg)
