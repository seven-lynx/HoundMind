"""
SafetyWatchdog: lightweight heartbeat-based safety helper.

- heartbeat(): mark liveness; orchestrator should call this periodically
- emergency_stop(dog): stop actuators immediately and optionally log

This is intentionally simple and self-contained; orchestration decides when to
invoke emergency_stop based on faults (timeouts, sensor spikes, etc.).
"""
from __future__ import annotations

import time
from typing import Optional, Any


class SafetyWatchdog:
    def __init__(self, timeout_s: float = 3.0, logger: Optional[Any] = None) -> None:
        self.timeout_s = max(0.5, float(timeout_s))
        self.logger = logger
        self._last_beat = time.time()
        self._armed = False

    def heartbeat(self) -> None:
        self._last_beat = time.time()

    def is_timed_out(self) -> bool:
        return (time.time() - self._last_beat) > self.timeout_s

    def arm_emergency(self) -> None:
        self._armed = True
        if self.logger:
            self.logger.warning("SafetyWatchdog: emergency armed")

    def disarm_emergency(self) -> None:
        self._armed = False
        if self.logger:
            self.logger.info("SafetyWatchdog: emergency disarmed")

    def emergency_stop(self, dog: Any) -> None:
        try:
            if self._armed and dog:
                try:
                    dog.body_stop()
                except Exception:
                    # Fallback if body_stop isn't available
                    dog.stop_and_lie()
                if self.logger:
                    self.logger.error("SafetyWatchdog: emergency_stop invoked")
        finally:
            # Always disarm after attempting stop
            self._armed = False
