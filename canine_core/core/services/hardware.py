from __future__ import annotations
from typing import Any
try:
    from pidog import Pidog
    from pidog.b9_rgb import RGB
except Exception:
    Pidog = None
    RGB = None

class HardwareService:
    def __init__(self) -> None:
        self.dog: Any = None
        self.rgb: Any = None

    def init(self) -> None:
        if Pidog is None:
            raise RuntimeError("Pidog library not available on this host")
        self.dog = Pidog()
        self.rgb = RGB(self.dog)

    def close(self) -> None:
        if self.dog:
            try:
                self.dog.close()
            except Exception:
                pass
