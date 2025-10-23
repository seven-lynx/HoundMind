from __future__ import annotations
import threading
import time
from typing import Callable, Optional, Tuple, cast

from packmind.core.context import AIContext
from packmind.core.types import SensorReading


class SensorService:
    """
    Polls PiDog hardware sensors at a fixed frequency and emits SensorReading.

    Usage:
      sensor = SensorService(context, on_reading=callback, frequency_hz=20.0)
      sensor.start(); ...; sensor.stop()

    The service guards hardware access so it can run on non-Pi hosts without crashing.
    """

    def __init__(self, context: AIContext, on_reading: Optional[Callable[[SensorReading], None]] = None, frequency_hz: float = 20.0) -> None:
        self._context = context
        self._on_reading = on_reading
        self._period = 1.0 / max(1e-6, frequency_hz)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                reading = self.read_once()
                if self._on_reading and reading:
                    self._on_reading(reading)
            except Exception:
                # Best-effort: do not crash the service on host PCs
                pass
            time.sleep(self._period)

    def read_once(self) -> SensorReading:
        """Safely read sensors from the dog; returns a SensorReading with sane defaults if unavailable."""
        dog = getattr(self._context, "dog", None)
        now = time.time()

        # Defaults for host PC without hardware
        distance = 200.0
        touch = "N"
        sound_detected = False
        sound_direction = -1
        acceleration = (0, 0, 0)
        gyroscope = (0, 0, 0)

        if dog is not None:
            try:
                # Ultrasonic
                if hasattr(dog, "ultrasonic") and hasattr(dog.ultrasonic, "read_distance"):
                    d = dog.ultrasonic.read_distance()
                    if isinstance(d, (int, float)) and d > 0:
                        distance = float(d)
                # Touch
                if hasattr(dog, "dual_touch") and hasattr(dog.dual_touch, "read"):
                    touch = dog.dual_touch.read() or "N"
                # Sound (ears)
                if hasattr(dog, "ears"):
                    ears = dog.ears
                    if hasattr(ears, "isdetected") and ears.isdetected():
                        sound_detected = True
                        if hasattr(ears, "read"):
                            sd = ears.read()
                            if isinstance(sd, int):
                                sound_direction = sd
                # IMU
                if hasattr(dog, "accData"):
                    acc = getattr(dog, "accData", (0, 0, 0))
                    acceleration = cast(Tuple[int, int, int], (int(acc[0]), int(acc[1]), int(acc[2])))
                if hasattr(dog, "gyroData"):
                    gyr = getattr(dog, "gyroData", (0, 0, 0))
                    gyroscope = cast(Tuple[int, int, int], (int(gyr[0]), int(gyr[1]), int(gyr[2])))
            except Exception:
                # Keep defaults on any hardware error
                pass

        return SensorReading(
            distance=distance,
            touch=touch,
            sound_detected=sound_detected,
            sound_direction=sound_direction,
            acceleration=acceleration,
            gyroscope=gyroscope,
            timestamp=now,
        )
