from __future__ import annotations
from typing import Any


class MotionService:
    """Reusable movement helpers with sim-safety.

    Adds optional global speed scaling to help conserve power when battery is low.
    Only affects calls made via MotionService.act(); direct dog.do_action() calls
    in behaviors are unaffected.
    """
    def __init__(self, hardware: Any) -> None:
        self.hardware = hardware
        self._speed_scale: float = 1.0  # 0.0..1.0 typically; clamped in act()

    def set_speed_scale(self, scale: float) -> None:
        try:
            self._speed_scale = float(scale)
        except Exception:
            self._speed_scale = 1.0
        # clamp
        if not (0.0 < self._speed_scale <= 2.0):
            self._speed_scale = min(max(self._speed_scale, 0.05), 2.0)

    def get_speed_scale(self) -> float:
        return float(self._speed_scale)

    def act(self, action: str, **kwargs) -> None:
        dog = getattr(self.hardware, "dog", None)
        if dog is None:
            return
        try:
            # Apply speed scaling if a speed kwarg is present
            if "speed" in kwargs:
                try:
                    scaled = int(max(1, round(float(kwargs["speed"]) * self._speed_scale)))
                    kwargs["speed"] = scaled
                except Exception:
                    pass
            dog.do_action(action, **kwargs)
        except Exception:
            pass

    def wait(self) -> None:
        dog = getattr(self.hardware, "dog", None)
        if dog is None:
            return
        try:
            dog.wait_all_done()
        except Exception:
            pass
