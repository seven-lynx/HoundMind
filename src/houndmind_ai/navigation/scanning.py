from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.commands import MOTION_ACTIONS, canonical_action

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
    """Head sweep + distance sampling through the HAL.

    `hal` is a `DogHAL`; the sweep is synchronous and blocking, which is the known H-01 defect
    and a Phase 3 problem, not something this refactor pretends to fix. What it does fix is that
    a scan no longer needs a vendor object: `hal/fake.py` drives this whole path in a test.
    """

    def __init__(self, hal, settings: dict[str, object]) -> None:
        self._hal = hal
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
        self._interval_override = max(0.0, _safe_float(interval_s, 0.0))

    def scan_three_way(self) -> ScanReading:
        left_deg = _safe_float(self._settings.get("scan_yaw_max_deg", 60), 60.0)
        right_deg = _safe_float(self._settings.get("scan_yaw_max_deg", 60), 60.0)
        settle_s = _safe_float(self._settings.get("scan_settle_s", 0.12), 0.12)
        samples = _safe_int(self._settings.get("scan_samples", 3), 3)
        between_reads_s = _safe_float(
            self._settings.get("scan_between_reads_s", 0.04), 0.04
        )
        speed = _safe_int(self._settings.get("head_scan_speed", 70), 70)

        result: dict[str, float] = {}
        try:
            self._head_move(0, speed)
            time.sleep(settle_s)
            result["forward"] = self._read_distance(samples, between_reads_s)

            self._head_move(-_safe_int(right_deg, 0), speed)
            time.sleep(settle_s)
            result["right"] = self._read_distance(samples, between_reads_s)

            self._head_move(_safe_int(left_deg, 0), speed)
            time.sleep(settle_s)
            result["left"] = self._read_distance(samples, between_reads_s)
        finally:
            try:
                self._head_move(0, speed)
            except Exception:  # noqa: BLE001
                pass

        return ScanReading(mode="three_way", data=result, timestamp=time.time())

    def sweep_scan(self, angles: list[int]) -> ScanReading:
        settle_s = _safe_float(self._settings.get("scan_settle_s", 0.12), 0.12)
        samples = _safe_int(self._settings.get("scan_samples", 3), 3)
        between_reads_s = _safe_float(
            self._settings.get("scan_between_reads_s", 0.04), 0.04
        )
        speed = _safe_int(self._settings.get("head_scan_speed", 70), 70)
        result: dict[int, float] = {}
        try:
            for yaw in angles:
                y = _safe_int(yaw, 0)
                self._head_move(y, speed)
                time.sleep(settle_s)
                result[y] = self._read_distance(samples, between_reads_s)
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
                max_len = max(1, _safe_int(self._settings.get("scan_history_size", 10), 10))
                if len(self._history) > max_len:
                    self._history = self._history[-max_len:]
                for cb in list(self._callbacks):
                    cb(reading)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scanning loop failed: %s", exc)
            elapsed = time.time() - start
            interval = _safe_float(self._settings.get("scan_interval_s", 0.5), 0.5)
            min_interval = _safe_float(self._settings.get("scan_interval_min_s", 0.2), 0.2)
            max_interval = _safe_float(self._settings.get("scan_interval_max_s", 2.0), 2.0)
            if self._interval_override is not None:
                interval = self._interval_override
            # Safe-mode override from settings.
            if self._settings.get("safe_mode_enabled", False):
                interval = max(
                    interval,
                    _safe_float(self._settings.get("safe_mode_scan_interval_s", interval), interval),
                )
            interval = min(max(interval, min_interval), max_interval)
            time.sleep(max(0.0, interval - elapsed))

    def build_angles(self) -> list[int]:
        yaw_max = _safe_int(self._settings.get("scan_yaw_max_deg", 60), 60)
        step = max(1, _safe_int(self._settings.get("scan_step_deg", 15), 15))
        angles = list(range(-yaw_max, yaw_max + 1, step))
        if not angles or angles[0] != -yaw_max or angles[-1] != yaw_max:
            angles = [-yaw_max, 0, yaw_max]
        return angles

    def _head_move(self, yaw: int, speed: int) -> None:
        if self._hal is None:
            return
        self._hal.action("head", {"yaw": int(yaw), "pitch": 0, "speed": speed, "wait": True})
        time.sleep(0.05)

    def _read_distance(self, samples: int, between_reads_s: float) -> float:
        if self._hal is None:
            return 0.0
        try:
            value = self._hal.sample_distance(max(1, samples), between_reads_s)
        except Exception:  # noqa: BLE001 - an unreadable distance is 0, as before
            value = None
        return 0.0 if value is None else float(value)


class ScanningModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.service: ScanningService | None = None
        self._context = None
        self._last_scan_ts = 0.0

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        hal = context.get("hal")
        if hal is None:
            self.disable("no HAL available")
            return
        self._context = context
        settings = (context.get("settings") or {}).get("navigation", {})
        perf = (context.get("settings") or {}).get("performance", {})
        merged = dict(settings)
        merged["safe_mode_enabled"] = perf.get("safe_mode_enabled", False)
        merged["safe_mode_scan_interval_s"] = perf.get(
            "safe_mode_scan_interval_s", merged.get("scan_interval_s", 0.5)
        )
        self.service = ScanningService(hal, merged)
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

    # Keep obstacle data fresh while the dog is actually walking. This used to sniff four
    # producer keys for movement words; the gateway's own output is the one place that knows a
    # motion is being executed, and it says so unambiguously.
    command = context.get("motion_command")
    if isinstance(command, dict):
        raw = command.get("canonical_action") or command.get("action")
        if raw and canonical_action(str(raw)) in MOTION_ACTIONS:
            return True

    return False
