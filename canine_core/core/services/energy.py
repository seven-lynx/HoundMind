from __future__ import annotations
from typing import Optional


class EnergyService:
    """Lightweight energy model (0.0..1.0) with decay/recovery.

    Config keys used if present on cfg:
    - ENERGY_DECAY_RATE
    - ENERGY_INTERACTION_BOOST
    - ENERGY_REST_RECOVERY
    - ENERGY_LOW_THRESHOLD
    - ENERGY_HIGH_THRESHOLD
    """

    def __init__(self, cfg: object, logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._logger = logger
        self._e = 0.8  # start fairly high

    @property
    def level(self) -> float:
        return max(0.0, min(1.0, self._e))

    def tick_active(self) -> float:
        rate = float(getattr(self._cfg, "ENERGY_DECAY_RATE", 0.001))
        self._e -= rate
        self._e = max(0.0, self._e)
        return self._e

    def tick_rest(self) -> float:
        rec = float(getattr(self._cfg, "ENERGY_REST_RECOVERY", 0.002))
        self._e += rec
        self._e = min(1.0, self._e)
        return self._e

    def interact_boost(self) -> float:
        boost = float(getattr(self._cfg, "ENERGY_INTERACTION_BOOST", 0.05))
        self._e += boost
        self._e = min(1.0, self._e)
        return self._e

    def is_low(self) -> bool:
        thr = float(getattr(self._cfg, "ENERGY_LOW_THRESHOLD", 0.3))
        return self.level <= thr

    def is_high(self) -> bool:
        thr = float(getattr(self._cfg, "ENERGY_HIGH_THRESHOLD", 0.7))
        return self.level >= thr
