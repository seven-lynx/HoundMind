"""What the dog does when it cannot be sure of the world: stop, and say why.

The module this replaces had two jobs and got both wrong. Its recovery default was *lie down*
(`recovery_behavior: null` fell through to `rest_behavior`, `recovery_action: null` to `lie`), so
a stale sensor posed the dog — a motion nobody asked for, caused by a fault. And its candidate
list was `context["module_names"]`, which is every registered module while only *started* modules
heartbeat, so on a device with the shipped config (safety, health, balance and sensor_health all
off) the stale list was never empty and it fired every five seconds (H-03, #12).

Two jobs remain, both honest:

- **Data the decision layer depends on goes stale** → refuse motion. The refusal is an ordinary
  `stop` intent from the watchdog source, judged by the same gateway as everything else, so it
  appears in the audit trail and in `motion_cancel` instead of being a side effect.
- **A module stops ticking** → ask the runtime to restart it, with exponential backoff, via
  `kernel/supervisor.py`. Never by reaching into hardware from here.

The staleness window for scans is derived from how long a scan actually takes, because the
shipped sweep takes ~2.6 s and `scan_stale_s` was 0.8: a perfectly healthy scan was "stale" by
definition (P3-4).
"""

from __future__ import annotations

import logging
import time

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.commands import MOTION_ACTIONS, Source
from houndmind_ai.kernel.supervisor import RestartPolicy, Supervisor, SupervisorReport

logger = logging.getLogger(__name__)


def _safe_float(val, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


class WatchdogModule(Module):
    """Refuses motion it cannot justify, and asks for restarts it can."""

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.supervisor: Supervisor | None = None
        self._last_report: SupervisorReport | None = None
        self._holding = False
        self._hold_reason: str | None = None

    def start(self, context) -> None:
        settings = (context.get("settings") or {}).get("watchdog", {})
        self.supervisor = Supervisor(
            RestartPolicy(
                base_delay_s=_safe_float(settings.get("restart_cooldown_s"), 1.0),
                factor=_safe_float(settings.get("restart_backoff_factor"), 2.0),
                max_delay_s=_safe_float(settings.get("restart_max_delay_s"), 60.0),
                max_restarts=int(_safe_float(settings.get("max_restarts"), 3)),
                healthy_after_s=_safe_float(settings.get("healthy_after_s"), 30.0),
            ),
            clock=time.time,
        )
        super().start(context)

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("watchdog", {})
        if not settings.get("enabled", True):
            return

        now = time.time()
        sensor_stale = self._sensor_stale(context, settings, now)
        scan_stale = self._scan_stale(context, settings, now)
        self._hold_motion(context, sensor_stale, scan_stale, now)
        self._restart_what_stopped(context, settings, now)

    # ---- data staleness ----------------------------------------------------

    @staticmethod
    def _sensor_stale(context, settings, now: float) -> bool:
        timeout = _safe_float(settings.get("sensor_timeout_s"), 2.0)
        reading = context.get("sensor_reading")
        if reading is None:
            return True
        return (now - _safe_float(getattr(reading, "timestamp", 0.0), 0.0)) > timeout

    @staticmethod
    def _scan_stale(context, settings, now: float) -> bool:
        floor_s = _safe_float(settings.get("scan_timeout_s"), 2.0)
        # A scan cannot be staler than it takes to run one. The measured duration comes from
        # `ScanningService`; when there is none yet, the floor stands alone.
        measured = _safe_float(context.get("scan_duration_s"), 0.0)
        timeout = max(floor_s, measured * 1.5)
        reading = context.get("scan_reading")
        if reading is None:
            return True
        return (now - _safe_float(getattr(reading, "timestamp", 0.0), 0.0)) > timeout

    def _hold_motion(self, context, sensor_stale: bool, scan_stale: bool, now: float) -> None:
        """Publish a `stop` while the dog is asked to move on data we cannot trust.

        Nothing is published when nothing is moving: a stale reading while the dog stands is not
        a reason to disturb it, and "recovery every five seconds" was the old bug.
        """
        board = context.get("intent_board")
        reason = "sensor" if sensor_stale else "scan" if scan_stale else None
        if board is None:
            return

        if reason is None:
            self._release(context, board)
            return

        # No timestamp is passed in: the board stamps and expires on its own clock, and this
        # module reasons in wall-clock time for heartbeats. Mixing the two would make every
        # intent look ancient (`time.time()` is ~1.7e9, `time.monotonic()` is not).
        moving = any(
            command.source is not Source.WATCHDOG and command.action in MOTION_ACTIONS
            for command in board.latest()
        )
        if not moving and not self._holding:
            # Nothing was moving and nothing is being held: a stale reading while the dog stands
            # is not a reason to disturb it, and "recovery every five seconds" was the old bug.
            return
        # Once holding, stay holding until the data is fresh again. Releasing because a
        # *producer's* intent expired mid-tick would flap the hold against a slow tick — and a
        # slow tick is exactly when the hold matters.

        self._holding = True
        board.publish("stop", Source.WATCHDOG)
        context.set(
            "watchdog_hold",
            {
                "timestamp": now,
                "reason": f"{reason} stale",
                "sensor_stale": sensor_stale,
                "scan_stale": scan_stale,
            },
        )
        # One line per transition, not per tick: at 5 Hz a per-tick warning is a log flood, and a
        # flooded log is how the original fault stayed invisible.
        if self._hold_reason != reason:
            self._hold_reason = reason
            logger.warning("Watchdog holding motion: %s data is stale", reason)

    def _release(self, context, board) -> None:
        if not self._holding:
            return
        self._holding = False
        self._hold_reason = None
        board.retract(Source.WATCHDOG)
        context.set("watchdog_hold", None)
        logger.info("Watchdog released the motion hold")

    # ---- module liveness ---------------------------------------------------

    def _restart_what_stopped(self, context, settings, now: float) -> None:
        if self.supervisor is None:
            return
        statuses = context.get("module_statuses") or {}
        if not statuses:
            return
        ignore = {str(name) for name in (settings.get("ignore_modules") or [])}
        ignore.add(self.name)
        monitored = {name: status for name, status in statuses.items() if name not in ignore}
        report = self.supervisor.decide(
            monitored,
            timeout_s=_safe_float(settings.get("module_timeout_s"), 4.0),
            now=now,
            monitor=settings.get("monitor_modules") or None,
        )
        self._last_report = report
        context.set("watchdog_status", {**report.as_dict(), "timestamp": now})

        if report.restart:
            # The runtime owns restarting modules; a watchdog that reaches into hardware itself
            # is how two things end up believing they own the bus.
            context.set("restart_modules", list(report.restart))
            logger.warning("Watchdog restart requested: %s", ", ".join(report.restart))
        for name in report.failed:
            logger.error("Watchdog gave up on %s: %s", name, report.reasons.get(name, "unknown"))

    def stop(self, context) -> None:
        board = context.get("intent_board")
        if board is not None and self._holding:
            board.retract(Source.WATCHDOG)
        self._holding = False
        super().stop(context)