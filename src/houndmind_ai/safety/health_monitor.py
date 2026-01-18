from __future__ import annotations

import logging
import os
import time

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


def _read_cpu_temp_c() -> float | None:
    try:
        with open(
            "/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8"
        ) as handle:
            milli = int(handle.read().strip())
            return milli / 1000.0
    except Exception:
        return None


def _read_gpu_temp_c() -> float | None:
    for path in (
        "/sys/class/thermal/thermal_zone1/temp",
        "/sys/class/thermal/thermal_zone2/temp",
    ):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                milli = int(handle.read().strip())
                return milli / 1000.0
        except Exception:
            continue
    return None


def _read_load_1m() -> float | None:
    try:
        getloadavg = getattr(os, "getloadavg", None)
        if callable(getloadavg):
            return float(getloadavg()[0])
    except Exception:
        return None
    return None


def _read_mem_used_pct() -> float | None:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            data = handle.read().splitlines()
        mem_total = None
        mem_available = None
        for line in data:
            if line.startswith("MemTotal:"):
                mem_total = float(line.split()[1])
            elif line.startswith("MemAvailable:"):
                mem_available = float(line.split()[1])
        if mem_total and mem_available is not None:
            used = max(0.0, mem_total - mem_available)
            return (used / mem_total) * 100.0
    except Exception:
        return None
    return None


class HealthMonitorModule(Module):
    """Lightweight system health monitor (Pi 3 friendly).

    Samples CPU load/temp and memory usage at a low cadence, then
    sets a scan-interval override when the system is stressed.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_sample_ts = 0.0
        self._high_water = {
            "load_1m": None,
            "temp_c": None,
            "gpu_temp_c": None,
            "mem_used_pct": None,
        }

    def tick(self, context) -> None:
        settings = context.get("settings") or {}
        perf = settings.get("performance", {})
        navigation = settings.get("navigation", {})
        logging_settings = settings.get("logging", {})

        interval_s = float(perf.get("health_monitor_interval_s", 5.0))
        now = time.time()
        if now - self._last_sample_ts < interval_s:
            return
        self._last_sample_ts = now

        load_1m = _read_load_1m()
        temp_c = _read_cpu_temp_c()
        gpu_temp_c = _read_gpu_temp_c()
        mem_pct = _read_mem_used_pct()
        cores = max(1, os.cpu_count() or 1)

        load_warn_mult = float(perf.get("health_load_per_core_warn_multiplier", 1.5))
        temp_warn = float(perf.get("health_temp_warn_c", 70.0))
        gpu_temp_warn = float(perf.get("health_gpu_temp_warn_c", 75.0))
        mem_warn = float(perf.get("health_mem_used_warn_pct", 85.0))

        degraded = False
        degraded_reasons = []
        if load_1m is not None:
            load_per_core = load_1m / cores
            if load_per_core >= load_warn_mult:
                degraded = True
                degraded_reasons.append("load")
        if temp_c is not None and temp_c >= temp_warn:
            degraded = True
            degraded_reasons.append("temp")
        if gpu_temp_c is not None and gpu_temp_c >= gpu_temp_warn:
            degraded = True
            degraded_reasons.append("gpu_temp")
        if mem_pct is not None and mem_pct >= mem_warn:
            degraded = True
            degraded_reasons.append("memory")

        context.set(
            "health_status",
            {
                "timestamp": now,
                "load_1m": load_1m,
                "temp_c": temp_c,
                "gpu_temp_c": gpu_temp_c,
                "mem_used_pct": mem_pct,
                "cpu_cores": cores,
                "degraded": degraded,
                "degraded_reasons": degraded_reasons,
            },
        )
        context.set("health_degraded", degraded)

        # Track high-water marks for debugging and tuning.
        for key, value in (
            ("load_1m", load_1m),
            ("temp_c", temp_c),
            ("gpu_temp_c", gpu_temp_c),
            ("mem_used_pct", mem_pct),
        ):
            if value is None:
                continue
            prev = self._high_water.get(key)
            if prev is None or value > prev:
                self._high_water[key] = value
        context.set("health_high_water", self._high_water)

        status_enabled = bool(logging_settings.get("status_log_enabled", True))
        status_interval = float(logging_settings.get("status_log_interval_s", 10.0))
        last_status = float(context.get("health_status_last_log_ts") or 0.0)
        if status_enabled and now - last_status >= status_interval:
            context.set("health_status_last_log_ts", now)
            logger.info(
                "Health: load=%.2f temp=%sC mem=%s%% degraded=%s",
                load_1m if load_1m is not None else -1.0,
                f"{temp_c:.1f}" if temp_c is not None else "n/a",
                f"{mem_pct:.1f}" if mem_pct is not None else "n/a",
                degraded,
            )

        actions = perf.get("health_actions", ["throttle_scans"])
        if degraded and "throttle_scans" in actions:
            base_interval = float(navigation.get("scan_interval_s", 0.5))
            mult = float(perf.get("health_scan_interval_multiplier", 2.0))
            abs_delta = float(perf.get("health_scan_interval_abs_delta", 1.0))
            override = min(base_interval * mult, base_interval + abs_delta)
            context.set("scan_interval_override_s", override)
            logger.warning(
                "Health degraded: throttling scan interval to %.2fs", override
            )
        else:
            context.set("scan_interval_override_s", None)

        if degraded and "throttle_vision" in actions:
            vision_settings = settings.get("vision_pi4", {})
            base_interval = float(vision_settings.get("frame_interval_s", 0.2))
            mult = float(perf.get("health_vision_frame_interval_multiplier", 2.0))
            abs_delta = float(perf.get("health_vision_frame_interval_abs_delta", 0.2))
            override = min(base_interval * mult, base_interval + abs_delta)
            context.set("vision_frame_interval_override_s", override)
            logger.warning(
                "Health degraded: throttling vision frame interval to %.2fs", override
            )
        else:
            context.set("vision_frame_interval_override_s", None)

    def start(self, context) -> None:
        context.set("health_degraded", False)
        context.set("scan_interval_override_s", None)
        context.set("vision_frame_interval_override_s", None)
        context.set("health_status_last_log_ts", 0.0)

    def stop(self, context) -> None:
        context.set("health_degraded", False)
        context.set("scan_interval_override_s", None)
        context.set("vision_frame_interval_override_s", None)
        context.set("health_status_last_log_ts", 0.0)
