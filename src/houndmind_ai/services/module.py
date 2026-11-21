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
import contextlib
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
#
# A hang keeps its thread (#338), so the thread is no witness at all: the aiohttp loop can stop
# scheduling work while `is_alive()` stays true and every other signal stays green. The plane's loop
# therefore stamps `_stamp` from a task of its own (`_stamp_forever`), and `tick()` calls a stamp
# older than `_HANG_WINDOW_S` a hang. The window is generous on purpose - 40 missed stamps at 250 ms
# each - so a slow client or a GC pause is not a restart, while a wedged loop is still noticed
# inside one watch interval.
#
# A hang is not restarted (#384). A Python thread wedged inside its own loop cannot be killed from
# here, so `stop()` would spend its whole join timeout, the listener socket would stay bound, and
# `start()` would re-bind a port the old thread still holds - a restart whose only possible end is
# `cannot bind`, naming the wrong cause. So `tick()` disables the module on a hang with the remedy
# the operator actually has, and only a *death* spends the restart budget.
_STAMP_INTERVAL_S = 0.25
_HANG_WINDOW_S = 10.0
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
        # Written by the plane's own loop (`_stamp_forever`) and read here: a hang is the one
        # failure the thread cannot witness (#338).
        self._stamp: float | None = None
        self._unstamped_since: float | None = None

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
        # A stamp left behind by the last thread would read as a hang on the first tick.
        self._stamp = None
        self._unstamped_since = None
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
        """Notice a plane that died or hung after it started (#330, #338, #384).

        Nothing downstream can notice either failure: the runtime stamps `last_tick_ts` for every
        module it ticks, so the supervisor saw a healthy `api` whether or not the thread was alive,
        `/modules` said started, and systemd saw a live process. The thread is the only witness to a
        death; `_stamp`, refreshed by the plane's own loop, is the only witness to a hang, because a
        wedged loop keeps its thread.

        The two failures are not the same failure, so they do not share a recovery. A death is
        restarted through `restart_modules` - the key the watchdog writes, because the runtime owns
        `start()` and a module must not reach around it - and a plane that keeps dying is disabled
        with the count rather than looped forever. A hang cannot be restarted at all: the thread
        holding the socket will not run another byte of Python, so the re-bind can only fail. The
        module disables itself on the first hang, with the one remedy that works, instead of
        spending a restart budget on an attempt that cannot succeed.
        """
        thread = self._thread
        now = time.monotonic()
        if thread is not None and thread.is_alive():
            stamp = self._stamp
            if stamp is None:
                # Serving with no stamp yet. `start()` waits for the socket, not for the first
                # stamp, so this is a warm-up window - unless it never ends, which is the same
                # hang one step earlier.
                if self._unstamped_since is None:
                    self._unstamped_since = now
                waited = now - self._unstamped_since
                if waited <= _HANG_WINDOW_S:
                    context.set("api_alive", True)
                    return
                reason = f"the control plane loop has not stamped since start ({waited:.0f} s)"
            elif now - stamp <= _HANG_WINDOW_S:
                context.set("api_alive", True)
                self._unstamped_since = None
                if self._alive_since is None:
                    self._alive_since = now
                elif now - self._alive_since >= _HEALTHY_AFTER_S:
                    # Up long enough to be trusted again, so the restart budget resets.
                    self._restarts = 0
                return
            else:
                self._unstamped_since = None
                # Alive but not scheduling: only the stamp can say it, and it has stopped.
                reason = f"the control plane loop has not stamped for {now - stamp:.0f} s"
            # A hang, not a death, and a hang is terminal for this thread (#384). Nothing called
            # from here can make a wedged loop run the callback that would release the socket, so
            # the restart would spend `stop()`'s join timeout and then fail to bind. Say what the
            # operator can actually do instead of attempting it.
            context.set("api_alive", False)
            self.disable(f"{reason}; restart the service (systemctl restart houndmind)")
            logger.error("Control plane hung: %s", reason)
            return

        reason = self._error or "the control plane thread exited without an error"
        context.set("api_alive", False)
        self.status.last_error = reason
        if self._dead_since is None:
            # First sighting: say it once, then fall through to the first restart attempt.
            self._dead_since = now
            self._alive_since = None
            logger.error("Control plane lost: %s", reason)
        elif now - self._dead_since < _RESTART_COOLDOWN_S:
            return
        if self._restarts >= _MAX_SELF_RESTARTS:
            self.disable(f"the control plane was lost {self._restarts} times: {reason}")
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
            "Control plane lost (%s); asked the runtime to restart it (%d/%d)",
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
        heartbeat = asyncio.create_task(self._stamp_forever())
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
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            # Withdrawn before the port goes: a record that outlives its socket points a client at
            # nothing, which is worse than no record at all.
            if discovery is not None:
                discovery.stop()
            await runner.cleanup()
            logger.info("Control plane stopped")

    async def _stamp_forever(self) -> None:
        """Say the plane's loop is still scheduling work, once every `_STAMP_INTERVAL_S` (#338).

        A death shows up in `thread.is_alive()`; a hang does not, because a wedged loop keeps its
        thread. This task is the only clock the loop owns, so a value that stops moving is the
        evidence `tick()` acts on. `tick()` reads the attribute from another thread and a float
        assignment is atomic, so there is no lock here on purpose.
        """
        while True:
            self._stamp = time.monotonic()
            await asyncio.sleep(_STAMP_INTERVAL_S)

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