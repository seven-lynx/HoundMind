"""
HealthMonitor: collect lightweight system health metrics and notify a callback.

- start()/stop() manage an internal sampling thread
- Samples include cpu_load, cpu_temp_c (if available), mem_used_pct
- Designed to run without extra deps; optionally uses psutil if installed
"""
from __future__ import annotations

import threading
import time
import os
from typing import Optional, Callable, Dict, Any

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore


def _read_cpu_temp_c() -> Optional[float]:
    # Try Linux sysfs thermal
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r", encoding="utf-8") as f:
            milli = int(f.read().strip())
            return milli / 1000.0
    except Exception:
        pass
    # Try psutil sensors_temperatures
    try:
        if psutil and hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()  # type: ignore[attr-defined]
            for lst in temps.values():
                for entry in lst:
                    if getattr(entry, "current", None) is not None:
                        return float(entry.current)
    except Exception:
        pass
    return None


def _read_load_1m() -> Optional[float]:
    try:
        getloadavg = getattr(os, "getloadavg", None)
        if getloadavg:  # type: ignore[truthy-function]
            return float(getloadavg()[0])  # type: ignore[misc]
    except Exception:
        pass
    # psutil fallback
    try:
        if psutil:
            # Convert cpu_percent to a pseudo-load per core basis
            pct = psutil.cpu_percent(interval=None)
            cores = max(1, os.cpu_count() or 1)
            # map 100% of all cores => load = cores
            return (pct / 100.0) * cores
    except Exception:
        pass
    return None


def _read_mem_used_pct() -> Optional[float]:
    try:
        if psutil:
            return float(psutil.virtual_memory().percent)
    except Exception:
        pass
    return None


class HealthMonitor:
    def __init__(self, interval_s: float = 5.0, on_sample: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self.interval_s = max(1.0, float(interval_s))
        self.on_sample = on_sample
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="HealthMonitor", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._running = False
        t = self._thread
        if t is not None:
            t.join(timeout)

    def _loop(self) -> None:
        while self._running:
            try:
                sample = self.sample()
                if self.on_sample:
                    self.on_sample(sample)
            except Exception:
                pass
            time.sleep(self.interval_s)

    def sample(self) -> Dict[str, Any]:
        load_1m = _read_load_1m()
        temp_c = _read_cpu_temp_c()
        mem_pct = _read_mem_used_pct()
        return {
            "timestamp": time.time(),
            "load_1m": load_1m,
            "cpu_temp_c": temp_c,
            "mem_used_pct": mem_pct,
            "cpu_cores": os.cpu_count() or 1,
        }
