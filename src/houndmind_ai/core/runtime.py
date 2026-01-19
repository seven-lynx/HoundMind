from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from datetime import datetime

from .config import Config
from .module import Module, ModuleError

logger = logging.getLogger(__name__)


@dataclass
class RuntimeContext:
    data: dict[str, object] = field(default_factory=dict)

    def set(self, key: str, value: object) -> None:
        self.data[key] = value

    def get(self, key: str, default: object | None = None) -> object | None:
        return self.data.get(key, default)


class HoundMindRuntime:
    def __init__(self, config: Config, modules: list[Module]) -> None:
        self.config = config
        self.modules = modules
        self.context = RuntimeContext()
        # Make configuration available to every module.
        self.context.set("config", config)
        self.context.set("settings", config.settings)
        self.context.set("module_names", [module.name for module in modules])

    def start(self) -> None:
        for module in self.modules:
            if not module.status.enabled:
                continue
            try:
                module.start(self.context)
                module.status.started = True
                logger.info("Started module: %s", module.name)
            except Exception as exc:  # noqa: BLE001 - capture hardware failures
                if module.status.required:
                    raise ModuleError(f"Required module failed: {module.name}") from exc
                module.disable(str(exc))

    def stop(self) -> None:
        for module in self.modules:
            if module.status.started:
                try:
                    module.stop(self.context)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to stop module %s: %s", module.name, exc)

    def tick(self) -> None:
        self.context.set("watchdog_heartbeat_ts", time.time())
        self._update_quiet_mode()
        for module in self.modules:
            if module.status.started:
                try:
                    module.tick(self.context)
                    # Record module heartbeat and health timing.
                    now = time.time()
                    module.status.last_tick_ts = now
                    module.status.last_heartbeat_ts = now
                    self.context.set(f"module_heartbeat:{module.name}", now)
                except Exception as exc:  # noqa: BLE001
                    # Track module errors for status reporting.
                    module.status.last_error = str(exc)
                    self.context.set(f"module_error:{module.name}", str(exc))
                    logger.warning("Module tick failed: %s (%s)", module.name, exc)
        # Publish a module status snapshot for diagnostics and dashboards.
        self.context.set(
            "module_statuses",
            {module.name: module.status.to_dict() for module in self.modules},
        )
        self._handle_restarts()

    def _update_quiet_mode(self) -> None:
        settings = self.config.settings or {}
        quiet = settings.get("quiet_mode", {})
        enabled = bool(quiet.get("enabled", False))
        if not enabled:
            self.context.set("quiet_mode_active", False)
            return
        try:
            start_hour = int(quiet.get("start_hour", 22))
            end_hour = int(quiet.get("end_hour", 7))
        except Exception:
            start_hour = 22
            end_hour = 7
        hour = datetime.now().hour
        if start_hour == end_hour:
            active = True
        elif start_hour < end_hour:
            active = start_hour <= hour < end_hour
        else:
            # Overnight window (e.g., 22 -> 7)
            active = hour >= start_hour or hour < end_hour
        self.context.set("quiet_mode_active", active)

    def _handle_restarts(self) -> None:
        restart_modules = self.context.get("restart_modules")
        if not restart_modules:
            return
        if isinstance(restart_modules, str):
            restart_modules = [restart_modules]
        if isinstance(restart_modules, list):
            self.context.set("restart_modules", [])
            for name in restart_modules:
                self._restart_module(str(name))

    def _restart_module(self, name: str) -> None:
        for module in self.modules:
            if module.name != name:
                continue
            try:
                if module.status.started:
                    module.stop(self.context)
                    module.status.started = False
                if module.status.enabled:
                    module.start(self.context)
                    module.status.started = True
                logger.warning("Restarted module: %s", name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to restart module %s: %s", name, exc)

    def run(self) -> None:
        self.start()
        loop_hz = max(1, self.config.loop.tick_hz)
        delay = 1.0 / loop_hz
        cycles = 0
        last_tick_start: float | None = None
        ema_tick_s: float | None = None
        ema_interval_s: float | None = None
        try:
            while True:
                start = time.time()
                self.context.set("tick_ts", start)
                self.tick()
                elapsed = time.time() - start
                settings = self.config.settings or {}
                perf = settings.get("performance", {})
                alpha = float(perf.get("runtime_ema_alpha", 0.2))
                interval = None
                tick_hz_actual = None
                if last_tick_start is not None:
                    interval = start - last_tick_start
                    if interval > 0:
                        tick_hz_actual = 1.0 / interval
                        ema_interval_s = (
                            interval
                            if ema_interval_s is None
                            else ((1.0 - alpha) * ema_interval_s + alpha * interval)
                        )
                ema_tick_s = (
                    elapsed
                    if ema_tick_s is None
                    else ((1.0 - alpha) * ema_tick_s + alpha * elapsed)
                )
                self.context.set(
                    "runtime_performance",
                    {
                        "timestamp": start,
                        "tick_hz_target": loop_hz,
                        "tick_hz_actual": tick_hz_actual,
                        "tick_duration_s": elapsed,
                        "tick_duration_avg_s": ema_tick_s,
                        "tick_interval_s": interval,
                        "tick_interval_avg_s": ema_interval_s,
                        "tick_overrun_s": max(0.0, elapsed - delay),
                        "loop_delay_s": delay,
                    },
                )
                warn_threshold = float(perf.get("runtime_tick_warn_s", delay * 1.5))
                if elapsed > warn_threshold:
                    logger.warning("Runtime tick overrun: %.3fs", elapsed)
                cycles += 1
                if (
                    self.config.loop.max_cycles is not None
                    and cycles >= self.config.loop.max_cycles
                ):
                    break
                # Sleep only the remaining budget to reduce drift.
                time.sleep(max(0.0, delay - elapsed))
                last_tick_start = start
        except KeyboardInterrupt:
            logger.warning("Runtime interrupted by user")
        finally:
            self.stop()


def build_default_modules(config: Config) -> list[Module]:
    from houndmind_ai.safety.sensor_health import SensorHealthModule
    # ... import other modules as needed ...
    modules = []
    # ...existing module instantiation logic...
    # Add sensor health module (disabled by default)
    modules.append(SensorHealthModule("sensor_health", enabled=config.settings.get("sensor_health", {}).get("enabled", False)))
    return modules
