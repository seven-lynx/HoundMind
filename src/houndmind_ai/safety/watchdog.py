from __future__ import annotations

import logging
import time
from typing import Iterable

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class WatchdogModule(Module):
    """Watchdog that triggers recovery when sensor/scan data goes stale."""

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_trigger_ts = 0.0
        self._restart_counts: dict[str, int] = {}
        self._last_restart_ts: dict[str, float] = {}

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("watchdog", {})
        if not settings.get("enabled", True):
            return

        now = time.time()
        sensor_timeout = float(settings.get("sensor_timeout_s", 2.0))
        scan_timeout = float(settings.get("scan_timeout_s", 2.0))
        module_timeout = float(settings.get("module_timeout_s", 4.0))
        cooldown = float(settings.get("restart_cooldown_s", 5.0))

        sensor_reading = context.get("sensor_reading")
        scan_reading = context.get("scan_reading")

        sensor_ts = (
            float(getattr(sensor_reading, "timestamp", 0.0)) if sensor_reading else 0.0
        )
        scan_ts = (
            float(getattr(scan_reading, "timestamp", 0.0)) if scan_reading else 0.0
        )

        sensor_stale = sensor_reading is None or (now - sensor_ts) > sensor_timeout
        scan_stale = scan_reading is None or (now - scan_ts) > scan_timeout

        module_names = (
            settings.get("monitor_modules") or context.get("module_names") or []
        )
        stale_modules: list[str] = []
        for name in list(module_names):
            last_ts = context.get(f"module_heartbeat:{name}") or 0.0
            if now - float(last_ts) > module_timeout:
                stale_modules.append(str(name))

        if not sensor_stale and not scan_stale and not stale_modules:
            context.set("watchdog_action", None)
            context.set("behavior_override", None)
            return

        if now - self._last_trigger_ts < cooldown:
            return

        self._last_trigger_ts = now
        recovery_mode = str(settings.get("recovery_mode", "behavior"))
        recovery_action = settings.get("recovery_action") or "lie"
        recovery_behavior = settings.get("recovery_behavior") or "rest_behavior"

        if recovery_mode == "behavior":
            context.set("behavior_override", recovery_behavior)
            context.set("watchdog_action", None)
        else:
            context.set("watchdog_action", recovery_action)
            context.set("behavior_override", None)

        restart_modules = settings.get("restart_modules", [])
        if stale_modules:
            restart_modules = list(set(list(restart_modules) + stale_modules))
        restart_list = list(self._eligible_restarts(restart_modules, settings))
        if restart_list:
            context.set("restart_modules", restart_list)

        logger.warning(
            "Watchdog recovery: sensor_stale=%s scan_stale=%s stale_modules=%s mode=%s restarts=%s",
            sensor_stale,
            scan_stale,
            stale_modules,
            recovery_mode,
            restart_list,
        )

    def _eligible_restarts(
        self, names: Iterable[str], settings: dict[str, object]
    ) -> list[str]:
        max_restarts = int(settings.get("max_restarts", 3))
        module_cooldown = float(settings.get("restart_module_cooldown_s", 10.0))
        eligible: list[str] = []
        for name in names:
            last_ts = self._last_restart_ts.get(str(name), 0.0)
            if module_cooldown > 0 and (time.time() - last_ts) < module_cooldown:
                continue
            count = self._restart_counts.get(name, 0)
            if count >= max_restarts:
                continue
            self._restart_counts[name] = count + 1
            self._last_restart_ts[str(name)] = time.time()
            eligible.append(str(name))
        return eligible
