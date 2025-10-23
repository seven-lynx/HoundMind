"""
ScanningCoordinator: cadence controller around ScanningService.

Decides when to scan based on context flags and config, calls scanning_service
accordingly, and updates obstacle scan data via callback.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Any, Dict


class ScanningCoordinator:
    def __init__(
        self,
        scanning_service: Any,
        should_scan: Callable[[], bool],
        on_scan: Callable[[Dict[str, float]], None],
        interval_s: float = 0.5,
        logger: Optional[Any] = None,
    ) -> None:
        self.scanning_service = scanning_service
        self.should_scan = should_scan
        self.on_scan = on_scan
        self.interval_s = max(0.1, float(interval_s))
        self.logger = logger
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="ScanningCoordinator", daemon=True)
        self._thread.start()
        if self.logger:
            self.logger.info("ScanningCoordinator started")

    def stop(self, timeout: float = 2.0) -> None:
        self._running = False
        t = self._thread
        if t is not None:
            t.join(timeout)
        if self.logger:
            self.logger.info("ScanningCoordinator stopped")

    def _loop(self) -> None:
        while self._running:
            try:
                if self.should_scan():
                    if self.logger:
                        self.logger.debug("Performing 3-way scan")
                    scan = self.scanning_service.scan_three_way(left_deg=50, right_deg=50, settle_s=0.3, samples=3)
                    self.on_scan(scan)
            except Exception as e:  # pragma: no cover
                if self.logger:
                    self.logger.debug(f"ScanningCoordinator error: {e}")
            time.sleep(self.interval_s)
