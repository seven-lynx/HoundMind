from __future__ import annotations
from typing import Any, Dict, Optional
import time


class TelemetryService:
    """Lightweight telemetry collector that logs periodic snapshots.

    Sim-safe: if no hardware readings available, logs minimal info.
    """

    def __init__(self, hardware: Any, logger: Any, interval_s: float = 10.0) -> None:
        self._hardware = hardware
        self._logger = logger
        self.interval_s = float(interval_s)
        self._last = 0.0

    def snapshot(self) -> Dict[str, Any]:
        dog = getattr(self._hardware, "dog", None)
        data: Dict[str, Any] = {"ts": time.time()}
        if dog is None:
            return data
        try:
            if hasattr(dog, "read_distance"):
                data["front_cm"] = float(dog.read_distance() or 0.0)
        except Exception:
            pass
        return data

    def maybe_log(self) -> None:
        now = time.time()
        if now - self._last < self.interval_s:
            return
        self._last = now
        try:
            snap = self.snapshot()
            self._logger.info(f"telemetry: {snap}")
        except Exception:
            pass
