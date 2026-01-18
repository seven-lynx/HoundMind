from __future__ import annotations

import logging
import time
from typing import Iterable

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class ServiceWatchdogModule(Module):
    """Background service watchdog for module restarts.

    Observes module heartbeats and last_error values, then requests
    restarts via RuntimeContext when a module appears stuck or failed.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_restart_ts: dict[str, float] = {}
        self._restart_counts: dict[str, int] = {}
        self._last_error_seen: dict[str, str | None] = {}
        self._last_snapshot_ts = 0.0

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("service_watchdog", {})
        if not settings.get("enabled", True):
            return

        now = time.time()
        module_timeout = float(settings.get("module_timeout_s", 6.0))
        cooldown = float(settings.get("restart_cooldown_s", 5.0))
        max_restarts = int(settings.get("max_restarts", 3))
        monitor_modules = (
            settings.get("monitor_modules") or context.get("module_names") or []
        )
        ignore_modules = set(settings.get("ignore_modules") or [])
        restart_on_error = bool(settings.get("restart_on_error", True))
        restart_on_stale = bool(settings.get("restart_on_stale", True))

        if now - self._last_snapshot_ts >= float(
            settings.get("status_interval_s", 1.0)
        ):
            self._last_snapshot_ts = now
            context.set(
                "service_watchdog_status",
                {
                    "timestamp": now,
                    "restart_counts": dict(self._restart_counts),
                },
            )

        status_map = context.get("module_statuses") or {}
        candidates = [
            str(name)
            for name in list(monitor_modules)
            if str(name) not in ignore_modules
        ]
        restart_list: list[str] = []
        reasons: dict[str, str] = {}

        for name in candidates:
            status = status_map.get(name)
            if not status:
                continue
            if not status.get("enabled", True):
                continue

            last_error = status.get("last_error")
            if restart_on_error and last_error:
                if self._last_error_seen.get(name) != last_error:
                    if self._eligible_restart(name, now, cooldown, max_restarts):
                        restart_list.append(name)
                        reasons[name] = "error"
                    self._last_error_seen[name] = str(last_error)

            if restart_on_stale:
                last_ts = (
                    context.get(f"module_heartbeat:{name}")
                    or status.get("last_heartbeat_ts")
                    or 0.0
                )
                if now - float(last_ts) > module_timeout:
                    if self._eligible_restart(name, now, cooldown, max_restarts):
                        restart_list.append(name)
                        reasons.setdefault(name, "stale")

        if restart_list:
            context.set("restart_modules", restart_list)
            context.set(
                "service_watchdog_restarts",
                {"timestamp": now, "modules": restart_list, "reasons": reasons},
            )
            logger.warning("Service watchdog restart requested: %s", reasons)

    def _eligible_restart(
        self, name: str, now: float, cooldown: float, max_restarts: int
    ) -> bool:
        last_ts = self._last_restart_ts.get(name, 0.0)
        if cooldown > 0 and (now - last_ts) < cooldown:
            return False
        count = self._restart_counts.get(name, 0)
        if count >= max_restarts:
            return False
        self._restart_counts[name] = count + 1
        self._last_restart_ts[name] = now
        return True

    def reset(self, names: Iterable[str] | None = None) -> None:
        if names is None:
            self._last_restart_ts.clear()
            self._restart_counts.clear()
            self._last_error_seen.clear()
            return
        for name in names:
            self._last_restart_ts.pop(str(name), None)
            self._restart_counts.pop(str(name), None)
            self._last_error_seen.pop(str(name), None)
