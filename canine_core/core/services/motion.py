from __future__ import annotations
from typing import Any


class MotionService:
    """Reusable movement helpers with sim-safety."""
    def __init__(self, hardware: Any) -> None:
        self.hardware = hardware

    def act(self, action: str, **kwargs) -> None:
        dog = getattr(self.hardware, "dog", None)
        if dog is None:
            return
        try:
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
