from __future__ import annotations
from typing import Any, Optional


class SensorsFacade:
    """Sim-safe wrappers for additional sensors (sound direction, touch).

    - Sound direction (ears): isdetected() and read() bearing in degrees
    - Dual touch: read() -> one of {"N","L","R","LS","RS"}
    """

    def __init__(self, hardware: Any) -> None:
        self._hardware = hardware

    # --- Sound direction (ears) ---
    def sound_detected(self) -> Optional[bool]:
        ears = getattr(self._hardware, "dog", None)
        if ears is None:
            return None
        try:
            ears = getattr(ears, "ears", None)
            if ears is None or not hasattr(ears, "isdetected"):
                return None
            return bool(ears.isdetected())
        except Exception:
            return None

    def sound_direction_deg(self) -> Optional[int]:
        ears_owner = getattr(self._hardware, "dog", None)
        if ears_owner is None:
            return None
        try:
            ears = getattr(ears_owner, "ears", None)
            if ears is None or not hasattr(ears, "read"):
                return None
            return int(ears.read())
        except Exception:
            return None

    # --- Dual touch ---
    def touch_read(self) -> Optional[str]:
        dog = getattr(self._hardware, "dog", None)
        if dog is None:
            return None
        try:
            dt = getattr(dog, "dual_touch", None)
            if dt is None or not hasattr(dt, "read"):
                return None
            return str(dt.read())
        except Exception:
            return None
