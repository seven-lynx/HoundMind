from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


@dataclass
class ScanReading:
    mode: str
    data: dict[int, float] | dict[str, float]
    timestamp: float

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": self.mode,
            "timestamp": self.timestamp,
        }
        if self.mode == "sweep":
            payload["angles"] = {str(k): float(v) for k, v in self.data.items()}
        else:
            payload.update({str(k): float(v) for k, v in self.data.items()})
        return payload


class ScanningService:
    def __init__(self, dog, settings: dict[str, object]) -> None:
        self._dog = dog
        self._settings = settings
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._callbacks: list[Callable[[ScanReading], None]] = []
        self._latest: ScanReading | None = None
        self._history: list[ScanReading] = []
        self._interval_override: float | None = None

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

    def subscribe(self, callback: Callable[[ScanReading], None]) -> None:
        self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[ScanReading], None]) -> None:
        self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    def latest(self) -> ScanReading | None:
        return self._latest

    def history(self) -> list[ScanReading]:
        return list(self._history)

    def set_interval_override(self, interval_s: float | None) -> None:
        if interval_s is None:
            self._interval_override = None
            return
        self._interval_override = max(0.0, float(interval_s))

    def scan_three_way(self) -> ScanReading:
        left_deg = float(self._settings.get("scan_yaw_max_deg", 60))
        right_deg = float(self._settings.get("scan_yaw_max_deg", 60))
        settle_s = float(self._settings.get("scan_settle_s", 0.12))
        samples = int(self._settings.get("scan_samples", 3))
        between_reads_s = float(self._settings.get("scan_between_reads_s", 0.04))
        speed = int(self._settings.get("head_scan_speed", 70))

        result: dict[str, float] = {}
        try:
            self._head_move(0, speed)
            time.sleep(settle_s)
            result["forward"] = self._read_distance(samples, between_reads_s)

            self._head_move(-int(right_deg), speed)
            time.sleep(settle_s)
            result["right"] = self._read_distance(samples, between_reads_s)

            self._head_move(int(left_deg), speed)
            time.sleep(settle_s)
            result["left"] = self._read_distance(samples, between_reads_s)
        finally:
            try:
                self._head_move(0, speed)
            except Exception:  # noqa: BLE001
                pass

        return ScanReading(mode="three_way", data=result, timestamp=time.time())

    def sweep_scan(self, angles: list[int]) -> ScanReading:
        settle_s = float(self._settings.get("scan_settle_s", 0.12))
        samples = int(self._settings.get("scan_samples", 3))
        between_reads_s = float(self._settings.get("scan_between_reads_s", 0.04))
        speed = int(self._settings.get("head_scan_speed", 70))
        result: dict[int, float] = {}
        try:
            for yaw in angles:
                self._head_move(int(yaw), speed)
                time.sleep(settle_s)
                result[int(yaw)] = self._read_distance(samples, between_reads_s)
        finally:
            try:
                self._head_move(0, speed)
            except Exception:  # noqa: BLE001
                pass

        return ScanReading(mode="sweep", data=result, timestamp=time.time())

    def _loop(self) -> None:
        scan_mode = str(self._settings.get("scan_mode", "sweep"))
        while not self._stop.is_set():
            start = time.time()
            try:
                if scan_mode == "three_way":
                    reading = self.scan_three_way()
                else:
                    angles = self.build_angles()
                    reading = self.sweep_scan(angles)
                self._latest = reading
                self._history.append(reading)
                max_len = max(1, int(self._settings.get("scan_history_size", 10)))
                if len(self._history) > max_len:
                    self._history = self._history[-max_len:]
                for cb in list(self._callbacks):
                    cb(reading)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scanning loop failed: %s", exc)
            elapsed = time.time() - start
            interval = float(self._settings.get("scan_interval_s", 0.5))
            min_interval = float(self._settings.get("scan_interval_min_s", 0.2))
            max_interval = float(self._settings.get("scan_interval_max_s", 2.0))
            if self._interval_override is not None:
                interval = self._interval_override
            # Safe-mode override from settings.
            if self._settings.get("safe_mode_enabled", False):
                interval = max(
                    interval,
                    float(self._settings.get("safe_mode_scan_interval_s", interval)),
                )
            interval = min(max(interval, min_interval), max_interval)
            time.sleep(max(0.0, interval - elapsed))

    def build_angles(self) -> list[int]:
        yaw_max = int(self._settings.get("scan_yaw_max_deg", 60))
        step = max(1, int(self._settings.get("scan_step_deg", 15)))
        angles = list(range(-yaw_max, yaw_max + 1, step))
        if not angles or angles[0] != -yaw_max or angles[-1] != yaw_max:
            angles = [-yaw_max, 0, yaw_max]
        return angles

    def _head_move(self, yaw: int, speed: int) -> None:
        self._dog.head_move([[int(yaw), 0, 0]], speed=speed)
        if hasattr(self._dog, "wait_head_done"):
            self._dog.wait_head_done()
        time.sleep(0.05)

    def _read_distance(self, samples: int, between_reads_s: float) -> float:
        values: list[float] = []
        for _ in range(max(1, samples)):
            if hasattr(self._dog, "read_distance"):
                value = self._dog.read_distance()
            else:
                value = self._dog.ultrasonic.read_distance()
            try:
                val = float(value)
            except Exception:
                val = 0.0
            if val > 0:
                values.append(val)
            if between_reads_s:
                time.sleep(between_reads_s)
        if not values:
            return 0.0
        values.sort()
        return values[len(values) // 2]


class ScanningModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.service: ScanningService | None = None
        self._context = None
        self._last_scan_ts = 0.0

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        self._context = context
        dog = context.get("pidog")
        if dog is None:
            from pidog import Pidog  # type: ignore

            dog = Pidog()
            context.set("pidog", dog)
            context.set("pidog_owner", self.name)
        settings = (context.get("settings") or {}).get("navigation", {})
        perf = (context.get("settings") or {}).get("performance", {})
        merged = dict(settings)
        merged["safe_mode_enabled"] = perf.get("safe_mode_enabled", False)
        merged["safe_mode_scan_interval_s"] = perf.get(
            "safe_mode_scan_interval_s", merged.get("scan_interval_s", 0.5)
        )
        self.service = ScanningService(dog, merged)
        self.service.subscribe(self._publish_reading)
        context.set("scan_service", self.service)

        if settings.get("scan_continuous", True):
            self.service.start()

    def tick(self, context) -> None:
        if self.service is None:
            return
        if settings_continuous(context):
            override = context.get("scan_interval_override_s")
            quiet = (context.get("settings") or {}).get("quiet_mode", {})
            if context.get("quiet_mode_active"):
                quiet_interval = quiet.get("scan_interval_s")
                try:
                    quiet_interval = (
                        float(quiet_interval) if quiet_interval is not None else None
                    )
                except Exception:
                    quiet_interval = None
                if quiet_interval is not None:
                    override_val = float(override) if override is not None else 0.0
                    override = max(override_val, quiet_interval)
            try:
                self.service.set_interval_override(override)
            except Exception:  # noqa: BLE001
                pass
            return
        settings = (context.get("settings") or {}).get("navigation", {})
        interval = float(settings.get("scan_interval_s", 0.5))
        min_interval = float(settings.get("scan_interval_min_s", 0.2))
        max_interval = float(settings.get("scan_interval_max_s", 2.0))
        interval = min(max(interval, min_interval), max_interval)
        perf = (context.get("settings") or {}).get("performance", {})
        if perf.get("safe_mode_enabled", False):
            interval = max(
                interval, float(perf.get("safe_mode_scan_interval_s", interval))
            )
        quiet = (context.get("settings") or {}).get("quiet_mode", {})
        if context.get("quiet_mode_active"):
            try:
                quiet_interval = float(quiet.get("scan_interval_s", interval))
            except Exception:
                quiet_interval = interval
            interval = max(interval, quiet_interval)
        now = time.time()
        if now - self._last_scan_ts < interval:
            return
        self._last_scan_ts = now

        scan_mode = str(settings.get("scan_mode", "sweep"))
        try:
            if scan_mode == "three_way":
                reading = self.service.scan_three_way()
            else:
                reading = self.service.sweep_scan(self.service.build_angles())
            context.set("scan_reading", reading)
            context.set("scan_latest", reading.to_dict())
        except Exception:  # noqa: BLE001
            pass

    def stop(self, context) -> None:
        if self.service:
            self.service.stop()
            self.service = None

    def _publish_reading(self, reading: ScanReading) -> None:
        if self._context is None:
            return
        self._context.set("scan_reading", reading)
        self._context.set("scan_latest", reading.to_dict())
        history = self.service.history() if self.service else []
        self._context.set("scan_history", [entry.to_dict() for entry in history])
        # Emit scan quality summary for tuning.
        distances = []
        data = reading.data or {}
        try:
            for val in data.values():
                dist = float(val)
                if dist > 0:
                    distances.append(dist)
        except Exception:  # noqa: BLE001
            distances = []
        total = len(data) if isinstance(data, dict) else 0
        valid = len(distances)
        quality = {
            "timestamp": reading.timestamp,
            "valid_ratio": (valid / total) if total > 0 else 0.0,
            "min_distance_cm": min(distances) if distances else None,
            "max_distance_cm": max(distances) if distances else None,
        }
        self._context.set("scan_quality", quality)


def settings_continuous(context) -> bool:
    settings = (context.get("settings") or {}).get("navigation", {})
    # Honor configured continuous scan flag first.
    if bool(settings.get("scan_continuous", True)):
        return True

    # If movement/navigation actions are currently active, enforce continuous
    # scanning to keep obstacle data fresh while walking/turning.
    for key in ("safety_action", "watchdog_action", "navigation_action", "behavior_action"):
        action = context.get(key)
        if not action:
            continue
        try:
            a = str(action).lower()
        except Exception:
            continue
        # Treat basic locomotion or turn actions as movement.
        if any(tok in a for tok in ("forward", "backward", "left", "right", "turn", "walk", "step")):
            return True

    return False
