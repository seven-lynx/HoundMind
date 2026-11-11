from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.commands import MOTION_ACTIONS, canonical_action
from houndmind_ai.kernel.scheduler import LatestJobWorker

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

    Blocking by nature: a sweep is nine head moves and 27 distance samples. It is therefore
    called from `ScanningModule`'s worker, never from the decision loop (H-01). `hal/fake.py`
    drives the whole path in a test, which is why a scan needs no vendor object.

    The service keeps the *result* (latest, history, duration) and nothing else: cadence belongs
    to the module, the thread belongs to `kernel/scheduler.py`.
    """

    def __init__(self, hal, settings: dict[str, object]) -> None:
        self._hal = hal
        self._settings = settings
        self._latest: ScanReading | None = None
        self._history: list[ScanReading] = []
        # How long the last scan actually took. The watchdog derives its staleness window from
        # this, because a sweep takes seconds and a fixed sub-second timeout called a healthy
        # scan stale forever (P3-4).
        self.last_duration_s = 0.0

    # ---- results -----------------------------------------------------------

    def latest(self) -> ScanReading | None:
        return self._latest

    def history(self) -> list[ScanReading]:
        return list(self._history)

    def record(self, reading: ScanReading) -> ScanReading:
        """Remember a finished scan, keeping `scan_history_size` entries."""
        self._latest = reading
        self._history.append(reading)
        max_len = max(1, _safe_int(self._settings.get("scan_history_size", 10), 10))
        if len(self._history) > max_len:
            self._history = self._history[-max_len:]
        return reading

    def scan_three_way(self) -> ScanReading:
        started = time.time()
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

        self.last_duration_s = time.time() - started
        return ScanReading(mode="three_way", data=result, timestamp=time.time())

    def sweep_scan(self, angles: list[int]) -> ScanReading:
        started = time.time()
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

        self.last_duration_s = time.time() - started
        return ScanReading(mode="sweep", data=result, timestamp=time.time())

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
    """Drives head scans on a worker, so the decision loop never waits for one (H-01)."""

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.service: ScanningService | None = None
        self.worker: LatestJobWorker | None = None
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
        context.set("scan_service", self.service)
        context.set("scan_in_flight", False)

        # One owned worker. Replacing the service's private daemon thread is the point: a thread
        # nobody can stop or observe is how a scan ends up running during shutdown.
        self.worker = LatestJobWorker("houndmind-scan")
        self.worker.start()
        context.set("scan_worker", self.worker)

    def tick(self, context) -> None:
        worker = self.worker
        if worker is None or self.service is None:
            return
        if not self._wanted(context):
            return
        # Still scanning: the result of a second scan submitted now would be superseded by the
        # one in flight, so there is nothing to gain by queueing it.
        if worker.busy:
            return
        now = time.time()
        if now - self._last_scan_ts < self._interval(context):
            return
        self._last_scan_ts = now
        context.set("scan_in_flight", True)
        worker.submit("scan", self._run_scan)

    def _wanted(self, context) -> bool:
        """Scan on a timer, or — with `scan_continuous: false` — only while the dog moves."""
        settings = (context.get("settings") or {}).get("navigation", {})
        if bool(settings.get("scan_continuous", True)):
            return True
        command = context.get("motion_command")
        if isinstance(command, dict):
            raw = command.get("canonical_action") or command.get("action")
            if raw and canonical_action(str(raw)) in MOTION_ACTIONS:
                return True
        return False

    def _interval(self, context) -> float:
        """Seconds between scans, honouring safe mode, the health override and quiet mode."""
        settings = (context.get("settings") or {}).get("navigation", {})
        interval = _safe_float(settings.get("scan_interval_s", 0.5), 0.5)
        min_interval = _safe_float(settings.get("scan_interval_min_s", 0.2), 0.2)
        max_interval = _safe_float(settings.get("scan_interval_max_s", 2.0), 2.0)

        override = context.get("scan_interval_override_s")
        if override is not None:
            interval = _safe_float(override, interval)

        perf = (context.get("settings") or {}).get("performance", {})
        if perf.get("safe_mode_enabled", False):
            interval = max(interval, _safe_float(perf.get("safe_mode_scan_interval_s"), interval))

        if context.get("quiet_mode_active"):
            quiet = (context.get("settings") or {}).get("quiet_mode", {})
            interval = max(interval, _safe_float(quiet.get("scan_interval_s"), interval))

        return min(max(interval, min_interval), max_interval)

    def _run_scan(self) -> None:
        """The blocking part, on the worker thread. Publishes when it is done."""
        context = self._context
        service = self.service
        if context is None or service is None:
            return
        try:
            settings = (context.get("settings") or {}).get("navigation", {})
            if str(settings.get("scan_mode", "sweep")) == "three_way":
                reading = service.scan_three_way()
            else:
                reading = service.sweep_scan(service.build_angles())
            service.record(reading)
            self._publish_reading(reading)
        finally:
            context.set("scan_in_flight", False)

    def stop(self, context) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        context.set("scan_worker", None)
        context.set("scan_in_flight", False)
        self.service = None
        self._context = None

    def _publish_reading(self, reading: ScanReading) -> None:
        if self._context is None:
            return
        self._context.set("scan_reading", reading)
        self._context.set("scan_latest", reading.to_dict())
        if self.service is not None:
            self._context.set("scan_duration_s", self.service.last_duration_s)
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
