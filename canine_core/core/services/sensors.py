from __future__ import annotations
from typing import Any, Tuple


class SensorService:
    """Thin wrapper around hardware sensors with sim-safe defaults.

    Distances are returned in centimeters (cm).
    """

    def __init__(self, hardware: Any) -> None:
        self.hardware = hardware

    def read_distances(self, head_range: int = 45, head_speed: int = 70) -> Tuple[float, float, float]:
        """Return forward, left, right distances in centimeters (cm).
        Falls back to large distances if hardware isn't available or fails.
        """
        dog = getattr(self.hardware, "dog", None)
        if dog is None:
            return (1000.0, 1000.0, 1000.0)
        try:
            dog.head_move([[-head_range, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            left = float(dog.read_distance() or 1000.0)
            dog.head_move([[head_range, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            right = float(dog.read_distance() or 1000.0)
            dog.head_move([[0, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            fwd = float(dog.read_distance() or 1000.0)
            return (fwd, left, right)
        except Exception:
            return (1000.0, 1000.0, 1000.0)
