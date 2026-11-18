"""The module that owns the control plane's process resources (D13).

The decision loop is synchronous and must never block on a socket, so the control plane runs an
asyncio loop on its own daemon thread with exactly one owner: this module. Bind failures, a
missing `aiohttp`, and a slow shutdown are all reported as module state rather than as an
exception that takes the runtime down with it.

`aiohttp` is imported **inside** `start()`. The lesson of B-09 is that a module-scope import of an
optional-to-this-install package is enough to stop the whole process before it reads a config.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.services.discovery import MdnsAdvertiser
from houndmind_ai.services.settings import ApiSettings
from houndmind_ai.services.tls import TlsError, build_context

logger = logging.getLogger(__name__)

__all__ = ["ControlPlaneModule"]

_START_TIMEOUT_S = 10.0
_STOP_TIMEOUT_S = 5.0
# A plane that dies *after* it started used to look healthy (#330): the runtime stamps
# `last_tick_ts` for every module it ticks, so the supervisor saw a fresh heartbeat whether or not
# anything was still listening, `/modules` said started, and systemd saw a live process. The thread
# is the only witness, so this module asks the runtime for a restart itself - through the same
# `restart_modules` key the watchdog writes, because the runtime owns `start()`.
_RESTART_COOLDOWN_S = 5.0
_HEALTHY_AFTER_S = 30.0
_MAX_SELF_RESTARTS = 3


class ControlPlaneModule(Module):
    """Runs `services/api.py` on a thread and publishes the snapshot it serves."""

    def __init__(
        self,
        name: str = "api",
        enabled: bool = True,
        required: bool = False,
        bus: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        # `kwargs` are tolerated: `main.build_registry` passes whatever the config section held,
        # and an unknown key must not stop the runtime from constructing.
        self.bus = bus
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._plane: Any = None
        # Liveness bookkeeping for `tick()` (see `_RESTART_COOLDOWN_S`). `_restarts` is deliberately
        # *not* reset by `start()`: a plane that dies immediately after every restart must run out
        # of budget instead of looping forever.
        self._dead_since: float | None = None
        self._alive_since: float | None = None
        self._restarts = 0

    # ---- lifecycle ---------------------------------------------------------

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        settings = ApiSettings.from_settings(context.get("settings"))
        bus = self.bus if self.bus is not None else context.get("command_bus")
        if bus is None:
            self.disable("no command bus; nothing could drive the dog anyway")
            return
        try:
            # Import check first: a missing wheel must degrade, not crash.
            import houndmind_ai.services.api  # noqa: F401
        except ImportError as exc:
            self.disable(f"missing dependency: {exc.name or 'aiohttp'}")
            return

        self._ready.clear()
        self._error = None
        self._dead_since = None
        self._alive_since = None
        self._thread = threading.Thread(
            target=self._run,
            args=(context, settings, bus),
            name="houndmind-api",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(_START_TIMEOUT_S):
            self.disable("the control plane did not start within 10 s")
            return
        if self._error:
            self.disable(self._error)

    def tick(self, context) -> None:
        """Notice a plane that died after it started, and ask the runtime to bring it back (#330).

        Nothing downstream can notice: the runtime stamps `last_tick_ts` for every module it ticks,
        so the supervisor saw a healthy `api` whether or not the thread was alive, `/modules` said
        started, and systemd saw a live process. The thread is the only witness, so the check lives
        here and the recovery goes through `restart_modules` - the same context key the watchdog
        writes - because the runtime owns `start()` and a module must not reach around it.

        A plane that keeps dying is disabled with the count in the reason rather than restarted
        forever: a silent restart loop is the failure this issue was about.
        """
        thread = self._thread
        now = time.monotonic()
        if thread is not None and thread.is_alive():
            context.set("api_alive", True)
            if self._alive_since is None:
                self._alive_since = now
            elif now - self._alive_since >= _HEALTHY_AFTER_S:
                # Up long enough to be trusted again, so the restart budget resets.
                self._restarts = 0
            return

        context.set("api_alive", False)
        reason = self._error or "the control plane thread exited without an error"
        self.status.last_error = reason
        if self._dead_since is None:
            # First sighting: say it once, then fall through to the first restart attempt.
            self._dead_since = now
            self._alive_since = None
            logger.error("Control plane thread is gone: %s", reason)
        elif now - self._dead_since < _RESTART_COOLDOWN_S:
            return
        if self._restarts >= _MAX_SELF_RESTARTS:
            self.disable(f"the control plane died {self._restarts} times: {reason}")
            return
        self._restarts += 1
        self._dead_since = now
        requested = context.get("restart_modules") or []
        if isinstance(requested, str):
            requested = [requested]
        names = [str(name) for name in requested] if isinstance(requested, list) else []
        if self.name not in names:
            names.append(self.name)
        context.set("restart_modules", names)
        logger.warning(
            "Control plane dead (%s); asked the runtime to restart it (%d/%d)",
            reason,
            self._restarts,
            _MAX_SELF_RESTARTS,
        )

    def stop(self, context) -> None:
        loop, stop_event = self._loop, self._stop_event
        if loop is not None and stop_event is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop_event.set)
        thread = self._thread
        if thread is not None:
            thread.join(_STOP_TIMEOUT_S)
            if thread.is_alive():
                # Changing a live aiohttp port is not possible; be honest rather than hang.
                logger.warning("Control plane thread did not stop within %.0f s", _STOP_TIMEOUT_S)
        self._thread = None
        self._loop = None
        self._stop_event = None
        self.status.started = False

    # ---- the thread --------------------------------------------------------

    def _run(self, context, settings: ApiSettings, bus) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._serve(context, settings, bus))
        except Exception as exc:  # noqa: BLE001 - reported, not raised into the runtime
            self._error = f"control plane failed: {exc}"
            self._ready.set()
            logger.exception("Control plane thread failed")
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:  # noqa: BLE001
                logger.debug("Async generator shutdown failed", exc_info=True)
            asyncio.set_event_loop(None)
            loop.close()

    async def _serve(self, context, settings: ApiSettings, bus) -> None:
        from aiohttp import web

        from houndmind_ai.services.api import ControlPlane, create_app

        plane = ControlPlane(context, settings, bus, clock=time.monotonic)
        self._plane = plane
        # Built before the runner: a TLS failure is a configuration problem, and reporting it
        # costs no socket. `None` means plaintext, which is what aiohttp wants for that too.
        try:
            ssl_context = build_context(settings)
        except TlsError as exc:
            self._error = str(exc)
            self._ready.set()
            return
        runner = web.AppRunner(create_app(plane), access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, settings.host, settings.port, ssl_context=ssl_context)
        try:
            await site.start()
        except OSError as exc:
            # A port already in use is a configuration problem the operator can fix.
            self._error = f"cannot bind {settings.host}:{settings.port}: {exc}"
            self._ready.set()
            await runner.cleanup()
            return
        self._stop_event = asyncio.Event()
        discovery = self._start_advertising(settings, plane)
        self._ready.set()
        logger.info(
            "Control plane listening on %s://%s:%s (token: %s)",
            "https" if ssl_context is not None else "http",
            settings.host,
            settings.port,
            plane.tokens.path,
        )
        try:
            await self._stop_event.wait()
        finally:
            # Withdrawn before the port goes: a record that outlives its socket points a client at
            # nothing, which is worse than no record at all.
            if discovery is not None:
                discovery.stop()
            await runner.cleanup()
            logger.info("Control plane stopped")

    @staticmethod
    def _start_advertising(settings: ApiSettings, plane) -> MdnsAdvertiser | None:
        """Publish the service record, or log once and carry on (#38).

        Built from `plane.meta()` on purpose: the advertisement is public information, and taking
        the values from the same payload is what keeps the two from disagreeing about what is
        public. A failure here never reaches the caller - discovery is a convenience.
        """
        if not settings.discovery_enabled:
            return None
        meta = plane.meta()
        advertiser = MdnsAdvertiser(
            port=settings.port,
            service_name=settings.discovery_name,
            txt={
                "api_version": str(meta.get("api_version", "")),
                "min_client": str(meta.get("min_client", "")),
                "scheme": str(meta.get("scheme", "")),
            },
        )
        return advertiser if advertiser.start() else None