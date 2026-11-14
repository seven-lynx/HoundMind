"""The sensor service and its module.

The vendor reads and their signal conditioning moved to `hal/vendor.py`; what is left here is
cadence (one poll per `sensors.poll_hz`), a bounded history, and fan-out to subscribers. That
is the part with the threading hazard in it — the service publishes from a daemon thread while
the loop reads — and it is now testable against `hal/fake.py` with no hardware.

`SensorReading` stays as the shape the runtime publishes: several modules read `.acc`, `.gyro`
and `.sound_detected` off it, and changing the context payload is a separate job from moving
the vendor boundary.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.hal.iface import DogHAL, SensorSnapshot

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


@dataclass
class SensorReading:
    distance_cm: float | None
    touch: str
    sound_detected: bool
    sound_direction: int | None
    acc: tuple[float, float, float] | None
    gyro: tuple[float, float, float] | None
    timestamp: float
    distance_valid: bool
    touch_valid: bool
    sound_valid: bool
    imu_valid: bool
    # Defaulted so every existing construction still builds: the battery feed is optional, and a
    # reading that does not carry one must not claim 0 V (`hal/fake.py` has modelled the fields
    # since the fake was written; nothing on a real dog filled them until #119).
    battery_v: float | None = None
    battery_valid: bool = False

    @staticmethod
    def from_snapshot(snapshot: SensorSnapshot) -> SensorReading:
        """Adapt a HAL snapshot to the shape the runtime publishes."""
        return SensorReading(
            distance_cm=snapshot.distance_cm,
            touch=snapshot.touch,
            sound_detected=snapshot.sound_detected,
            sound_direction=snapshot.sound_direction,
            acc=snapshot.acc,
            gyro=snapshot.gyro,
            timestamp=snapshot.ts,
            distance_valid=snapshot.distance_valid,
            touch_valid=snapshot.touch_valid,
            sound_valid=snapshot.sound_valid,
            imu_valid=snapshot.imu_valid,
            battery_v=snapshot.battery_v,
            battery_valid=snapshot.battery_valid,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "distance": self.distance_cm,
            "touch": self.touch,
            "sound_detected": self.sound_detected,
            "sound_direction": self.sound_direction,
            "acc": self.acc,
            "gyro": self.gyro,
            "timestamp": self.timestamp,
            "distance_valid": self.distance_valid,
            "touch_valid": self.touch_valid,
            "sound_valid": self.sound_valid,
            "imu_valid": self.imu_valid,
            "battery_v": self.battery_v,
            "battery_valid": self.battery_valid,
        }
class SensorService:
    """Polls a `DogHAL` on a thread and hands each reading to its subscribers.

    `hal` may be None (a runtime with no hardware): the service then never polls, which keeps
    the "no dog attached" path a no-op instead of an exception.
    """

    def __init__(self, hal: DogHAL | None, settings: dict[str, object]) -> None:
        self._hal = hal
        self._settings = settings
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[SensorReading], None]] = []

        self._latest: SensorReading | None = None
        self._history: deque[SensorReading] = deque(maxlen=self._history_size())

    def start(self) -> None:
        if self._hal is None or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    def subscribe(self, callback: Callable[[SensorReading], None]) -> None:
        self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[SensorReading], None]) -> None:
        self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    def latest(self) -> SensorReading | None:
        with self._lock:
            return self._latest

    def history(self) -> list[SensorReading]:
        with self._lock:
            return list(self._history)

    def read_once(self) -> SensorReading | None:
        """One poll. Public so a test can drive the service without starting its thread."""
        if self._hal is None:
            return None
        try:
            snapshot = self._hal.read()
        except Exception:  # noqa: BLE001 - a failed read must not kill the loop
            logger.debug("HAL read failed", exc_info=True)
            return None
        return SensorReading.from_snapshot(snapshot)

    def _loop(self) -> None:
        interval = 1.0 / max(1.0, _safe_float(self._settings.get("poll_hz", 10), 10.0))
        while not self._stop.is_set():
            start = time.time()
            reading = self.read_once()
            if reading:
                with self._lock:
                    self._latest = reading
                    if self._history.maxlen != self._history_size():
                        self._history = deque(
                            self._history, maxlen=self._history_size()
                        )
                    self._history.append(reading)
                for cb in list(self._callbacks):
                    try:
                        cb(reading)
                    except Exception:  # noqa: BLE001
                        logger.debug("Sensor callback failed", exc_info=True)
            elapsed = time.time() - start
            time.sleep(max(0.0, interval - elapsed))

    def _history_size(self) -> int:
        return max(1, _safe_int(self._settings.get("history_size", 10), 10))


class SensorModule(Module):
    """Publishes `sensor_reading`, `sensors`, `sensor_history` and `sensor_health`."""

    def __init__(
        self,
        name: str,
        enabled: bool = True,
        required: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.service: SensorService | None = None
        self._context: Any = None
        self._clock = clock or time.time

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        hal = context.get("hal")
        if hal is None:
            self.disable("no HAL available")
            return

        self._context = context
        settings = (context.get("settings") or {}).get("sensors", {})
        self.service = SensorService(hal, settings)
        self.service.subscribe(self._publish_reading)
        context.set("sensor_service", self.service)
        self.service.start()

    def tick(self, context) -> None:
        if self.service is None:
            return
        latest = self.service.latest()
        if latest is not None:
            self._publish(context, latest)

    def stop(self, context) -> None:
        if self.service:
            self.service.stop()
            self.service = None
        self._context = None

    def _publish_reading(self, reading: SensorReading) -> None:
        """Subscriber callback: runs on the sensor thread, so it uses the stored context."""
        context = self._context
        if context is not None:
            self._publish(context, reading)

    def _publish(self, context, reading: SensorReading) -> None:
        now = self._clock()
        context.set("sensor_reading", reading)
        context.set("sensors", reading.to_dict())
        # One producer for the key the interlock and `behavior/fsm.py` both threshold on. Published
        # only while it is valid, so a feed that drops out leaves the last good value in place rather
        # than overwriting it with a None the two consumers would have to special-case (#119).
        if reading.battery_valid and reading.battery_v is not None:
            context.set("battery_voltage", reading.battery_v)
        context.set("sensor_history", self.service.history() if self.service else [])
        context.set(
            "sensor_health",
            {
                "timestamp": reading.timestamp,
                "age_s": max(0.0, now - _safe_float(reading.timestamp, now)),
                "distance_valid": reading.distance_valid,
                "touch_valid": reading.touch_valid,
                "sound_valid": reading.sound_valid,
                "imu_valid": reading.imu_valid,
                "battery_valid": reading.battery_valid,
            },
        )