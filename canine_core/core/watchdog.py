from __future__ import annotations
import time
from typing import Optional


class BehaviorWatchdog:
    """Simple behavior watchdog tracking dwell time and error count.

    - If max_dwell_s is exceeded or max_errors reached, should_stop() returns True.
    """

    def __init__(self, max_dwell_s: float = 60.0, max_errors: int = 1, logger: Optional[object] = None) -> None:
        self.max_dwell_s = float(max_dwell_s)
        self.max_errors = int(max_errors)
        self._logger = logger
        self._start_ts: float = 0.0
        self._errors: int = 0
        self._name: str = ""

    def start(self, behavior_name: str) -> None:
        self._name = behavior_name
        self._errors = 0
        self._start_ts = time.time()

    def record_error(self, where: str, exc: Exception | None = None) -> None:
        self._errors += 1
        if self._logger is not None:
            try:
                msg = f"Watchdog error in {self._name}.{where} (#{self._errors}/{self.max_errors}): {exc}"
                warn = getattr(self._logger, "warning", None)
                if callable(warn):
                    warn(msg)
            except Exception:
                pass

    @property
    def elapsed_s(self) -> float:
        if self._start_ts <= 0.0:
            return 0.0
        return max(0.0, time.time() - self._start_ts)

    def should_stop(self) -> bool:
        if self.max_errors > 0 and self._errors >= self.max_errors:
            return True
        if self.max_dwell_s > 0.0 and self.elapsed_s >= self.max_dwell_s:
            return True
        return False
