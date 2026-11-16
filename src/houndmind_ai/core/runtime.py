from __future__ import annotations

import logging
import signal
import time
import uuid
from collections.abc import Callable
from datetime import datetime

from houndmind_ai.kernel.state import StateStore

from .config import Config
from .module import Module, ModuleError

logger = logging.getLogger(__name__)

# Signals that mean "stop, in order". `systemctl stop` sends SIGTERM; a closing SSH session sends
# SIGHUP. Both used to end the process without unwinding (#212).
_STOP_SIGNALS = ("SIGTERM", "SIGHUP")


class RuntimeContext:
    """The shared bus every module reads and writes.

    Backed by a `StateStore` rather than a bare dict: the sensor and scan services publish
    from daemon threads while the loop reads, so the mapping needs a lock (H-02). `get`/`set`
    keep the shape every module already uses.
    """

    __slots__ = ("store",)

    def __init__(self, store: StateStore | None = None) -> None:
        self.store = store if store is not None else StateStore()

    def set(self, key: str, value: object) -> None:
        self.store.set(key, value)

    def get(self, key: str, default: object | None = None) -> object | None:
        return self.store.get(key, default)

    def snapshot(self) -> dict[str, object]:
        """A copy for logging, telemetry and anything else that iterates."""
        return self.store.snapshot()

    def __contains__(self, key: object) -> bool:
        return key in self.store


class HoundMindRuntime:
    def __init__(self, config: Config, modules: list[Module]) -> None:
        self.config = config
        self.modules = modules
        self.context = RuntimeContext()
        # Make configuration available to every module.
        self.context.set("config", config)
        self.context.set("settings", config.settings)
        self.context.set("module_names", [module.name for module in modules])
        # Generate a per-runtime trace id for correlating logs and telemetry.
        trace_id = uuid.uuid4().hex
        self.context.set("trace_id", trace_id)
        # Set from a signal handler, so the loop ends on a tick boundary and `stop()` still runs
        # (#212). A raised exception would not do: `tick()` catches `Exception` per module, so a
        # stop raised mid-tick would be logged as that module's failure and the loop would carry on.
        self._stop_requested = False
        self._stop_reason: str | None = None

    # ---- stopping ----------------------------------------------------------

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def request_stop(self, reason: str) -> None:
        """Finish the tick in progress, then shut down.

        Safe from a signal handler and from any thread: it assigns two attributes and the loop
        re-reads the flag at the top of every iteration. The first reason wins, because the second
        signal is usually the impatience of whoever sent the first one.
        """
        if not self._stop_requested:
            self._stop_reason = reason
        self._stop_requested = True

    def _install_stop_signals(self) -> Callable[[], None]:
        """Route SIGTERM and SIGHUP to `request_stop`, and hand back the undo (#212).

        Python terminates on SIGTERM without unwinding, so `finally: self.stop()` never ran: the
        HAL was never closed and the servos were never relaxed. That matters the moment the
        runtime is supervised, because `systemctl stop` sends SIGTERM by default.

        Handlers can only be installed from the main thread. Anywhere else this leaves the process
        untouched - an embedding own its own signal policy - and the returned function is a no-op.
        """
        previous: list[tuple[int, object]] = []

        def make_handler(name: str) -> Callable[[int, object], None]:
            def handler(signum: int, _frame: object) -> None:
                self.request_stop(f"{name} received")

            return handler

        for name in _STOP_SIGNALS:
            signum = getattr(signal, name, None)
            if signum is None:
                continue
            try:
                old = signal.getsignal(signum)
                signal.signal(signum, make_handler(name))
            except (ValueError, OSError):
                # Not the main thread, or a platform that will not take this signal.
                logger.debug("Cannot install a %s handler here", name)
                break
            previous.append((signum, old))

        def restore() -> None:
            for signum, old in previous:
                try:
                    signal.signal(signum, old)  # type: ignore[arg-type]
                except (ValueError, OSError, TypeError):
                    logger.debug("Could not restore the handler for signal %s", signum)

        return restore

    def start(self) -> None:
        for module in self.modules:
            if not module.status.enabled:
                continue
            try:
                module.start(self.context)
                # A module may disable itself inside `start` — no HAL, no camera, a missing
                # dependency. Marking it started anyway would put it in the tick loop and in
                # `module_statuses` as "enabled=False, started=True", and log a "Started" line
                # for something that just gave up.
                if module.status.enabled:
                    module.status.started = True
                    logger.info("Started module: %s", module.name)
            except Exception as exc:  # noqa: BLE001 - capture hardware failures
                logger.exception("Failed to start module: %s", module.name)
                if module.status.required:
                    raise ModuleError(f"Required module failed: {module.name}") from exc
                module.disable(str(exc))

    def stop(self) -> None:
        for module in self.modules:
            if module.status.started:
                try:
                    module.stop(self.context)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to stop module %s", module.name)

    def tick(self) -> None:
        self.context.set("watchdog_heartbeat_ts", time.time())
        self._update_quiet_mode()
        per_module_durations: dict[str, float] = {}
        for module in self.modules:
            if module.status.started:
                try:
                    m_start = time.time()
                    module.tick(self.context)
                    m_elapsed = time.time() - m_start
                    # Record module heartbeat, timing and health.
                    now = time.time()
                    module.status.last_tick_ts = now
                    module.status.last_heartbeat_ts = now
                    module.status.last_tick_duration_s = m_elapsed
                    per_module_durations[module.name] = m_elapsed
                    self.context.set(f"module_heartbeat:{module.name}", now)
                    self.context.set(f"module_tick_duration:{module.name}", m_elapsed)
                    # Log a warning if a module's tick consumed the whole loop budget.
                    loop_hz = max(1, self.config.loop.tick_hz)
                    budget = 1.0 / loop_hz
                    if m_elapsed > budget:
                        logger.warning(
                            "Module tick overrun: %s took %.3fs (budget %.3fs)",
                            module.name,
                            m_elapsed,
                            budget,
                        )
                except Exception as exc:  # noqa: BLE001
                    # Track module errors for status reporting.
                    module.status.last_error = str(exc)
                    self.context.set(f"module_error:{module.name}", str(exc))
                    logger.exception("Module tick failed: %s", module.name)
        # Publish per-module tick durations for diagnostics
        if per_module_durations:
            self.context.set("module_tick_durations", per_module_durations)
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
                if not module.status.enabled:
                    # It disabled itself while being restarted (no HAL, no camera, missing
                    # wheel). Marking it started anyway would put a module that just gave up
                    # back in the tick list and hide the reason it gave up.
                    logger.warning(
                        "Module %s did not come back: %s",
                        name,
                        module.status.disabled_reason or "disabled",
                    )
                    return
                module.start(self.context)
                if module.status.enabled:
                    module.status.started = True
                    logger.warning("Restarted module: %s", name)
                else:
                    logger.warning(
                        "Module %s gave up during restart: %s",
                        name,
                        module.status.disabled_reason or "disabled",
                    )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to restart module %s", name)
            return

    def run(self) -> None:
        """Run the loop until something asks it to stop, then shut down either way.

        The handlers go in here rather than in `main()` so every entry point gets them -
        `tools/smoke_test.py` builds a runtime directly, and a SIGTERM to that run has the same
        reason to close the HAL gracefully (#212).
        """
        restore_signals = self._install_stop_signals()
        try:
            self._run_loop()
        finally:
            restore_signals()

    def _run_loop(self) -> None:
        self.start()
        loop_hz = max(1, self.config.loop.tick_hz)
        delay = 1.0 / loop_hz
        cycles = 0
        last_tick_start: float | None = None
        ema_tick_s: float | None = None
        ema_interval_s: float | None = None
        try:
            while not self._stop_requested:
                start = time.time()
                self.context.set("tick_ts", start)
                # `CONTEXT_FIELDS` whitelists this into every JSON record, and it was the one field
                # only a test ever set — so no production line could be matched to a tick (#126).
                self.context.set("runtime_tick", cycles)
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
            if self._stop_requested:
                logger.warning("Runtime stopping: %s", self._stop_reason or "stop requested")
            self.stop()


# NOTE: `build_default_modules` was a placeholder that duplicated module
# construction logic. Module building is centralized in `main.build_modules`.
# The old placeholder has been removed to avoid accidental, out-of-sync
# module lists. If a canonical default builder is needed in the future,
# implement it in a single place (for example `main.build_modules`) and
# import/use it explicitly.
