from __future__ import annotations
import time
from typing import Any, Callable, List, Tuple


class ScanningCoordinator:
    """Head sweep helper that publishes scan_start/scan_end and samples distances.

    Sim-safe: if hardware isn't available, operations are no-ops and returns empty samples.
    """

    def __init__(self, hardware: Any, sensors: Any, publish: Callable[[str, dict], None]) -> None:
        self._hardware = hardware
        self._sensors = sensors
        self._publish = publish

    def sweep_samples(self, yaw_max_deg: int = 30, step_deg: int = 15, settle_s: float = 0.12,
                      between_reads_s: float = 0.04, head_speed: int = 60) -> List[Tuple[int, float]]:
        """Perform a simple left-to-right sweep and return [(yaw_deg, distance_cm), ...]."""
        self._publish("scan_start", {"yaw_max_deg": yaw_max_deg, "step_deg": step_deg})
        dog = getattr(self._hardware, "dog", None)
        out: List[Tuple[int, float]] = []
        if dog is None:
            self._publish("scan_end", {"count": 0})
            return out
        try:
            # Move to left limit
            left = -abs(int(yaw_max_deg))
            right = abs(int(yaw_max_deg))
            step = max(1, int(step_deg))
            dog.head_move([[left, 0, 0]], speed=int(head_speed))
            dog.wait_head_done()
            time.sleep(settle_s)
            # Sweep across
            for yaw in range(left, right + 1, step):
                dog.head_move([[yaw, 0, 0]], speed=int(head_speed))
                dog.wait_head_done()
                time.sleep(between_reads_s)
                try:
                    d = float(dog.read_distance() or 1000.0)
                except Exception:
                    d = 1000.0
                out.append((yaw, d))
            # Return to center
            dog.head_move([[0, 0, 0]], speed=int(head_speed))
            dog.wait_head_done()
        except Exception:
            # On any error, try to finish gracefully
            try:
                dog.head_move([[0, 0, 0]], speed=int(head_speed))
                dog.wait_head_done()
            except Exception:
                pass
        self._publish("scan_end", {"count": len(out)})
        return out
