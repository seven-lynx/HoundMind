from __future__ import annotations
from typing import Any, Optional, Callable


class BalanceService:
    """IMU-based stability assessment.

    Categorizes into: stable, slight, unstable, critical based on tilt.
    Publishes optional events when states change.
    """

    def __init__(self, imu: Any | None, publish: Optional[Callable[[str, dict], None]] = None,
                 max_tilt_deg: float = 45.0) -> None:
        self._imu = imu
        self._publish = publish or (lambda *_a, **_k: None)
        self.max_tilt_deg = float(max_tilt_deg)
        self._last_state: Optional[str] = None

    def current_tilt_deg(self) -> Optional[float]:
        if self._imu is None:
            return None
        try:
            acc = self._imu.read_accel()
            if acc is None:
                return None
            ax, ay, az = acc
            import math
            g = (ax**2 + ay**2 + az**2) ** 0.5
            if g <= 1e-6:
                return None
            vertical_ratio = abs(az) / g
            tilt_deg = math.degrees(math.acos(max(0.0, min(1.0, vertical_ratio))))
            return float(tilt_deg)
        except Exception:
            return None

    def assess(self) -> Optional[str]:
        tilt = self.current_tilt_deg()
        if tilt is None:
            return None
        # Simple thresholds
        if tilt < 10:
            state = "stable"
        elif tilt < 20:
            state = "slight"
        elif tilt < self.max_tilt_deg:
            state = "unstable"
        else:
            state = "critical"
        if state != self._last_state:
            self._publish("balance_state", {"state": state, "tilt_deg": tilt})
            self._last_state = state
        return state
