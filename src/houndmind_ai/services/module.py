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
from houndmind_ai.services.settings import ApiSettings
from houndmind_ai.services.tls import TlsError, build_context

logger = logging.getLogger(__name__)

__all__ = ["ControlPlaneModule"]

_START_TIMEOUT_S = 10.0
_STOP_TIMEOUT_S = 5.0


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
            await runner.cleanup()
            logger.info("Control plane stopped")