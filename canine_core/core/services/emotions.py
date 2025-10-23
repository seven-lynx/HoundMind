from __future__ import annotations
from typing import Any, Tuple, Optional


class EmotionService:
    """RGB emotion cues with sim-safety."""
    def __init__(self, hardware: Any, enabled: bool) -> None:
        self.hardware = hardware
        self.enabled = enabled

    def set_color(self, rgb_tuple: Tuple[int, int, int]) -> None:
        if not self.enabled:
            return
        rgb = getattr(self.hardware, "rgb", None)
        if rgb is None:
            return
        try:
            rgb.set_color(rgb_tuple)
        except Exception:
            pass

    def effect(self, name: str, cycles: int = 1) -> None:
        if not self.enabled:
            return
        rgb = getattr(self.hardware, "rgb", None)
        if rgb is None:
            return
        try:
            fx = getattr(rgb, name, None)
            if callable(fx):
                fx(cycles)
        except Exception:
            pass

    def update(self, color: Tuple[int, int, int], effect_name: Optional[str] = None, cycles: int = 1) -> None:
        """Convenience to set color and optionally play an effect."""
        self.set_color(color)
        if effect_name:
            self.effect(effect_name, cycles)
