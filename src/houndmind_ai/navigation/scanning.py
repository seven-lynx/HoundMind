from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
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


# A sweep is measured in seconds: one head move and one settle per angle, several distance
# samples per angle. `scan_settle_s: 0.12`, `scan_samples: 3` and yaw +/-60 deg in 15 deg steps is
# ~2.6 s at the shipped config, so a fixed sub-second window called a healthy scan stale by
# definition (P3-4). This is the floor when no `watchdog.scan_timeout_s` is configured.
SCAN_STALE_FLOOR_S = 2.0


def scan_freshness_window_s(floor_s: Any, measured_s: Any) -> float:
    """One rule for "is this scan still usable": `max(floor, 1.5 x the measured sweep)`.

    `floor_s` is the configured floor (`watchdog.scan_timeout_s`); the module constant stands in
    when it is missing or not positive. The rule lives in one function on purpose: the watchdog
    and the navigator asked the same question with two different constants, so the guarded path
    in `obstacle_avoidance` was dead code and the fallback drove the dog on readings the watchdog
    would not move on (#22). `safety/watchdog.py` publishes the result as `scan_stale_after_s`
    so there is one number at runtime, not two calculations that happen to agree.
    """
    floor = _safe_float(floor_s, 0.0)
    if floor <= 0:
        floor = SCAN_STALE_FLOOR_S
    measured = _safe_float(measured_s, 0.0)
    return max(floor, measured * 1.5)


@dataclass
class ScanReading:
    mode: str
    data: dict[int, float] | dict[str, float]
    timestamp: float
    # Which bearings were actually measured. A failed sample still carries `0.0` in `data`, because
    # that is the payload clients already read and v1 stays intact, but `valid[bearing]` is False —
    # so "no echo" and "a wall at zero centimetres" are no longer the same JSON (#400). Empty when a
    # reading was built without the service, which is honest: nothing says a bearing was measured.
    valid: dict[int, bool] | dict[str, bool] = field(default_factory=dict)
    # False when the post-sweep re-centre failed. The readings are real, the head did not come back,
    # and a client that aims by head position has to see it (#398).
    head_centered: bool = True

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "mode": self.mode,
            "timestamp": self.timestamp,
            "head_centered": self.head_centered,
        }
        if self.mode == "sweep":
            payload["angles"] = {str(k): float(v) for k, v in self.data.items()}
        else:
            payload.update({str(k): float(v) for k, v in self.data.items()})
        if self.valid:
            payload["valid"] = {str(k): bool(v) for k, v in self.valid.items()}
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
        # The last fault per kind, so a broken head or a quiet echo logs once per transition
        # rather than once per sample (#398).
        self._faults: dict[str, str | None] = {}
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
        valid: dict[str, bool] = {}
        centered = True
        try:
            self._head_move(0, speed)
            time.sleep(settle_s)
            result["forward"], valid["forward"] = self._read_distance(samples, between_reads_s)

            self._head_move(-_safe_int(right_deg, 0), speed)
            time.sleep(settle_s)
            result["right"], valid["right"] = self._read_distance(samples, between_reads_s)

            self._head_move(_safe_int(left_deg, 0), speed)
            time.sleep(settle_s)
            result["left"], valid["left"] = self._read_distance(samples, between_reads_s)
        finally:
            centered = self._center_head(speed)

        self.last_duration_s = time.time() - started
        return ScanReading(
            mode="three_way",
            data=result,
            timestamp=time.time(),
            valid=valid,
            head_centered=centered,
        )

    def sweep_scan(self, angles: list[int]) -> ScanReading:
        started = time.time()
        settle_s = _safe_float(self._settings.get("scan_settle_s", 0.12), 0.12)
        samples = _safe_int(self._settings.get("scan_samples", 3), 3)
        between_reads_s = _safe_float(
            self._settings.get("scan_between_reads_s", 0.04), 0.04
        )
        speed = _safe_int(self._settings.get("head_scan_speed", 70), 70)
        result: dict[int, float] = {}
        valid: dict[int, bool] = {}
        centered = True
        try:
            for yaw in angles:
                y = _safe_int(yaw, 0)
                self._head_move(y, speed)
                time.sleep(settle_s)
                result[y], valid[y] = self._read_distance(samples, between_reads_s)
        finally:
            centered = self._center_head(speed)

        self.last_duration_s = time.time() - started
        return ScanReading(
            mode="sweep",
            data=result,
            timestamp=time.time(),
            valid=valid,
            head_centered=centered,
        )

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

    def _read_distance(self, samples: int, between_reads_s: float) -> tuple[float, bool]:
        """One bearing and whether it was measured (#400).

        `0.0` is still what a failed sample contributes to `data`, because that is the payload
        every client already parses; the second element is the fact the payload was missing, so
        "no echo" stops reading as "a wall at zero centimetres".
        """
        if self._hal is None:
            self._note_fault("distance", "no HAL")
            return 0.0, False
        try:
            value = self._hal.sample_distance(max(1, samples), between_reads_s)
        except Exception as exc:  # noqa: BLE001 - a vendor read may raise anything; the flag is the report
            self._note_fault("distance", f"{type(exc).__name__}: {exc}")
            return 0.0, False
        if value is None:
            self._note_fault("distance", "no echo")
            return 0.0, False
        self._note_fault("distance", None)
        return float(value), True

    def _center_head(self, speed: int) -> bool:
        """Bring the head back to straight ahead, and say whether it made it (#398)."""
        try:
            self._head_move(0, speed)
        except Exception as exc:  # noqa: BLE001 - the reading is still returned, and says so
            self._note_fault("head re-centre", f"{type(exc).__name__}: {exc}")
            return False
        self._note_fault("head re-centre", None)
        return True

    def _note_fault(self, kind: str, message: str | None) -> None:
        """Log a fault once per transition, never once per sample.

        A head or an echo that stays broken for a whole run is one warning, not one per tick, and
        the recovery is logged too, so the pair says when it started and when it stopped. A
        cleared fault is `None` (#398).
        """
        if self._faults.get(kind) == message:
            return
        if message is None:
            if kind in self._faults:
                logger.info("Scan %s recovered", kind)
        else:
            logger.warning("Scan %s failed: %s", kind, message)
        self._faults[kind] = message


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
        if not reading.head_centered:
            # The reading is real, the head did not come back: say so on the module as well as on
            # the reading, so `/api/v1/modules` cannot call a stuck head healthy (#398).
            self.status.last_error = "head re-centre failed"
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
