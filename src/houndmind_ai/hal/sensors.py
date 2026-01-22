from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable, Deque, Any, Tuple, cast

from houndmind_ai.core.module import Module

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
        }


class SensorService:
    def __init__(self, dog, settings: dict[str, object]) -> None:
        self._dog = dog
        self._settings = settings
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[SensorReading], None]] = []

        self._latest: SensorReading | None = None
        self._history: Deque[SensorReading] = deque(maxlen=self._history_size())

        self._last_touch = "N"
        self._last_touch_ts = 0.0
        self._last_distance: float | None = None
        self._last_distance_ts = 0.0
        self._ema_distance: float | None = None
        self._acc_lpf: tuple[float, float, float] | None = None
        self._gyro_lpf: tuple[float, float, float] | None = None

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

    def _loop(self) -> None:
        interval = 1.0 / max(1.0, _safe_float(self._settings.get("poll_hz", 10), 10.0))
        while not self._stop.is_set():
            start = time.time()
            reading = self._read_once()
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

    def _read_once(self) -> SensorReading:
        now = time.time()
        enable_ultrasonic = bool(self._settings.get("enable_ultrasonic", True))
        enable_touch = bool(self._settings.get("enable_touch", True))
        enable_sound = bool(self._settings.get("enable_sound", True))
        enable_imu = bool(self._settings.get("enable_imu", True))

        distance_cm = None
        distance_valid = False
        if enable_ultrasonic:
            distance_cm, distance_valid = self._read_distance(now)

        touch = "N"
        touch_valid = False
        if enable_touch:
            touch, touch_valid = self._read_touch(now)

        sound_detected = False
        sound_direction = None
        sound_valid = False
        if enable_sound:
            sound_detected, sound_direction, sound_valid = self._read_sound()

        acc = None
        gyro = None
        imu_valid = False
        if enable_imu:
            acc, gyro, imu_valid = self._read_imu()

        return SensorReading(
            distance_cm=distance_cm,
            touch=touch,
            sound_detected=sound_detected,
            sound_direction=sound_direction,
            acc=acc,
            gyro=gyro,
            timestamp=now,
            distance_valid=distance_valid,
            touch_valid=touch_valid,
            sound_valid=sound_valid,
            imu_valid=imu_valid,
        )

    def _read_distance(self, now: float) -> tuple[float | None, bool]:
        debounce_s = max(0.0, _safe_float(self._settings.get("distance_debounce_s", 0.0), 0.0))
        if debounce_s > 0 and self._last_distance is not None:
            if (now - self._last_distance_ts) < debounce_s:
                return self._last_distance, True
        samples = max(1, _safe_int(self._settings.get("distance_samples", 3), 3))
        delay = max(0.0, _safe_float(self._settings.get("distance_sample_delay_s", 0.03), 0.03))
        min_cm = _safe_float(self._settings.get("distance_min_cm", 2), 2.0)
        max_cm = _safe_float(self._settings.get("distance_max_cm", 200), 200.0)
        use_median = bool(self._settings.get("distance_use_median", True))
        outlier_z = _safe_float(self._settings.get("distance_outlier_reject_z", 0.0), 0.0)
        ema_alpha = _safe_float(self._settings.get("distance_ema_alpha", 0.0), 0.0)

        values: list[float] = []
        for _ in range(samples):
            try:
                if hasattr(self._dog, "read_distance"):
                    value = float(self._dog.read_distance())
                else:
                    value = float(self._dog.ultrasonic.read_distance())
            except Exception:  # noqa: BLE001
                logger.debug("Ultrasonic read failed", exc_info=True)
                value = None
            if value is None:
                if delay:
                    time.sleep(delay)
                continue
            if min_cm <= value <= max_cm:
                values.append(value)
            if delay:
                time.sleep(delay)
        if not values:
            return None, False
        if outlier_z > 0.0 and len(values) >= 3:
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = variance**0.5
            if std > 0:
                filtered = [v for v in values if abs(v - mean) <= outlier_z * std]
                if filtered:
                    values = filtered
        values.sort()
        result = values[len(values) // 2] if use_median else sum(values) / len(values)
        if 0.0 < ema_alpha <= 1.0:
            if self._ema_distance is None:
                self._ema_distance = result
            else:
                self._ema_distance = (
                    1 - ema_alpha
                ) * self._ema_distance + ema_alpha * result
            result = self._ema_distance
        self._last_distance = result
        self._last_distance_ts = now
        return result, True

    def _read_touch(self, now: float) -> tuple[str, bool]:
        debounce_s = max(0.0, _safe_float(self._settings.get("touch_debounce_s", 0.05), 0.05))
        try:
            raw = self._dog.dual_touch.read() or "N"
        except Exception:  # noqa: BLE001
            logger.debug("Touch read failed", exc_info=True)
            return self._last_touch, False
        if raw != self._last_touch:
            if (now - self._last_touch_ts) >= debounce_s:
                self._last_touch = raw
                self._last_touch_ts = now
        return self._last_touch, True

    def _read_sound(self) -> tuple[bool, int | None, bool]:
        only_on_detect = bool(self._settings.get("sound_direction_on_detect", True))
        try:
            detected = bool(self._dog.ears.isdetected())
        except Exception:  # noqa: BLE001
            logger.debug("Sound detect failed", exc_info=True)
            return False, None, False
        if not detected and only_on_detect:
            return False, None, True
        try:
            direction = int(self._dog.ears.read())
        except Exception:  # noqa: BLE001
            logger.debug("Sound direction read failed", exc_info=True)
            return detected, None, False
        return detected, direction, True

    def _read_imu(
        self,
    ) -> tuple[
        tuple[float, float, float] | None, tuple[float, float, float] | None, bool
    ]:
        try:
            acc_raw = self._dog.accData
            gyro_raw = self._dog.gyroData
            acc = cast(Tuple[float, float, float], (
                _safe_float(acc_raw[0], 0.0),
                _safe_float(acc_raw[1], 0.0),
                _safe_float(acc_raw[2], 0.0),
            ))
            gyro = cast(Tuple[float, float, float], (
                _safe_float(gyro_raw[0], 0.0),
                _safe_float(gyro_raw[1], 0.0),
                _safe_float(gyro_raw[2], 0.0),
            ))
        except Exception:  # noqa: BLE001
            logger.debug("IMU read failed", exc_info=True)
            return None, None, False
        alpha = _safe_float(self._settings.get("imu_lpf_alpha", 0.0), 0.0)
        if 0.0 < alpha <= 1.0:
            if self._acc_lpf is None:
                self._acc_lpf = cast(Tuple[float, float, float], acc)
            else:
                self._acc_lpf = cast(
                    Tuple[float, float, float],
                    tuple((1 - alpha) * prev + alpha * cur for prev, cur in zip(self._acc_lpf, acc)),
                )
            if self._gyro_lpf is None:
                self._gyro_lpf = cast(Tuple[float, float, float], gyro)
            else:
                self._gyro_lpf = cast(
                    Tuple[float, float, float],
                    tuple((1 - alpha) * prev + alpha * cur for prev, cur in zip(self._gyro_lpf, gyro)),
                )
            acc = self._acc_lpf
            gyro = self._gyro_lpf
        return acc, gyro, True


class SensorModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.dog = None
        self.service: SensorService | None = None
        self._context = None

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        from pidog import Pidog  # type: ignore

        dog = context.get("pidog")
        if dog is None:
            dog = Pidog()
            context.set("pidog", dog)
            context.set("pidog_owner", self.name)
        self.dog = dog
        self._context = context

        settings = (context.get("settings") or {}).get("sensors", {})
        self.service = SensorService(dog, settings)
        self.service.subscribe(self._publish_reading)
        context.set("sensor_service", self.service)
        self.service.start()

    def tick(self, context) -> None:
        if self.service is None:
            return
        latest = self.service.latest()
        if latest is not None:
            context.set("sensor_reading", latest)
            context.set("sensors", latest.to_dict())
            context.set("sensor_history", self.service.history())
            context.set(
                "sensor_health",
                {
                    "timestamp": latest.timestamp,
                    "age_s": max(0.0, time.time() - _safe_float(latest.timestamp, time.time())),
                    "distance_valid": latest.distance_valid,
                    "touch_valid": latest.touch_valid,
                    "sound_valid": latest.sound_valid,
                    "imu_valid": latest.imu_valid,
                },
            )

    def stop(self, context) -> None:
        if self.service:
            self.service.stop()
            self.service = None
        dog_owner = context.get("pidog_owner")
        if dog_owner == self.name and self.dog is not None:
            try:
                self.dog.close()
            except Exception:  # noqa: BLE001
                pass

    def _publish_reading(self, reading: SensorReading) -> None:
        if self._context is None:
            return
        self._context.set("sensor_reading", reading)
        self._context.set("sensors", reading.to_dict())
        self._context.set(
            "sensor_history", self.service.history() if self.service else []
        )
        self._context.set(
            "sensor_health",
            {
                "timestamp": reading.timestamp,
                "age_s": max(0.0, time.time() - _safe_float(reading.timestamp, time.time())),
                "distance_valid": reading.distance_valid,
                "touch_valid": reading.touch_valid,
                "sound_valid": reading.sound_valid,
                "imu_valid": reading.imu_valid,
            },
        )
