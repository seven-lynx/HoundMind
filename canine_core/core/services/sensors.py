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
            head_move = getattr(dog, "head_move", None)
            wait_done = getattr(dog, "wait_head_done", None)
            read_dist = getattr(dog, "read_distance", None)

            if callable(head_move):
                head_move([[-head_range, 0, 0]], speed=head_speed)
            if callable(wait_done):
                wait_done()
            _lv: object = read_dist() if callable(read_dist) else 1000.0
            if not isinstance(_lv, (int, float)):
                _lv = 1000.0
            left = float(_lv)

            if callable(head_move):
                head_move([[head_range, 0, 0]], speed=head_speed)
            if callable(wait_done):
                wait_done()
            _rv: object = read_dist() if callable(read_dist) else 1000.0
            if not isinstance(_rv, (int, float)):
                _rv = 1000.0
            right = float(_rv)

            if callable(head_move):
                head_move([[0, 0, 0]], speed=head_speed)
            if callable(wait_done):
                wait_done()
            _fv: object = read_dist() if callable(read_dist) else 1000.0
            if not isinstance(_fv, (int, float)):
                _fv = 1000.0
            fwd = float(_fv)
            return (fwd, left, right)
        except Exception:
            return (1000.0, 1000.0, 1000.0)
