from __future__ import annotations
from typing import Any, Optional, Callable


class SafetyService:
    """Basic safety supervisor.

    - Monitors tilt via IMUService when available
    - Can publish emergency events and command safe pose
    - Sim-safe; does nothing if hardware missing
    """

    def __init__(self, hardware: Any, imu: Any | None, publish: Optional[Callable[[str, dict], None]] = None,
                 max_tilt_deg: float = 45.0, emergency_pose: str = "crouch") -> None:
        self._hardware = hardware
        self._imu = imu
        self._publish = publish or (lambda *_a, **_k: None)
        self.max_tilt_deg = float(max_tilt_deg)
        self.emergency_pose = emergency_pose

    def periodic_check(self) -> None:
        if self._imu is None:
            return
        try:
            tilted = self._imu.is_tilt_excessive(self.max_tilt_deg)
        except Exception:
            tilted = None
        if tilted:
            self._publish("safety_emergency_tilt", {"max_tilt_deg": self.max_tilt_deg})
            self.safe_pose()

    def safe_pose(self) -> None:
        dog = getattr(self._hardware, "dog", None)
        if dog is None:
            return
        try:
            dog.do_action(self.emergency_pose, speed=80)
            dog.wait_all_done()
        except Exception:
            pass
