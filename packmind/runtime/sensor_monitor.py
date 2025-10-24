"""
SensorMonitor: periodic polling loop for sensor readings.

Calls a provided read_once() to obtain SensorReading and forwards it to an
on_reading callback at a target rate.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional, Any


class SensorMonitor:
    def __init__(
        self,
        read_once: Callable[[], Any],
        on_reading: Callable[[Any], None],
        rate_hz: float = 20.0,
        backoff_on_error_s: float = 0.0,
        logger: Optional[Any] = None,
    ) -> None:
        self.read_once = read_once
        self.on_reading = on_reading
        self.period = 1.0 / max(1.0, float(rate_hz))
        self.backoff_on_error_s = max(0.0, float(backoff_on_error_s))
        self.logger = logger
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="SensorMonitor", daemon=True)
        self._thread.start()
        if self.logger:
            self.logger.info("SensorMonitor started")

    def stop(self, timeout: float = 2.0) -> None:
        self._running = False
        t = self._thread
        if t is not None:
            t.join(timeout)
        if self.logger:
            self.logger.info("SensorMonitor stopped")

    def _loop(self) -> None:
        next_t = time.time()
        while self._running:
            try:
                reading = self.read_once()
                self.on_reading(reading)
            except Exception as e:  # pragma: no cover
                if self.logger:
                    self.logger.debug(f"SensorMonitor error: {e}")
                if self.backoff_on_error_s > 0:
                    time.sleep(self.backoff_on_error_s)
            next_t += self.period
            sleep_d = max(0.0, next_t - time.time())
            time.sleep(sleep_d)
