"""The telemetry stream: one state pump, N subscribers, honest backpressure.

Two frame classes with different rules:

- ``state`` is a **latest value**. A slow client skips frames rather than falling behind; a
  phone on a weak link should show the current distance, not a two-second-old queue.
- ``event`` and ``command_ack`` are **never dropped**. If a client cannot keep up with those,
  it is disconnected, because losing "command_vetoed" is how a user ends up shouting at a dog
  that is refusing to move for a reason nobody told them.

The hub owns no policy: it asks for a state snapshot and hands the result to whoever is
listening. Link-loss and command submission live in `services/api.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable

from aiohttp import web

from houndmind_ai.services.auth import Authorizer
from houndmind_ai.services.sessions import SessionRegistry

logger = logging.getLogger(__name__)

__all__ = ["EventHub"]

# A client that cannot absorb this many non-droppable frames is not a slow client, it is a
# broken one, and the socket is closed rather than grown.
_EVENT_QUEUE = 64

# What "the decision changed" means. An explicit whitelist rather than "everything except `ts` and
# `inputs`": a field added to `DecisionRecord.to_dict()` later must not be able to start emitting
# an event every tick by accident. A new reading is not a new decision.
_DECISION_SIGNATURE_KEYS = ("mode", "state", "intent", "source", "vetoes")


def _decision_signature(decision: object) -> str | None:
    """A stable fingerprint of the choice this tick made, or None when there is no decision."""
    if not isinstance(decision, dict):
        return None
    picked = {key: decision.get(key) for key in _DECISION_SIGNATURE_KEYS}
    return json.dumps(picked, sort_keys=True, default=str)


# What "the routine moved" means: a new step, a new state, or the reason it stopped. `started_at` is
# deliberately absent — a fresh run already changes `id` and `index`, and a wall-clock float in a
# signature would let two identical frames look different.
_ROUTINE_SIGNATURE_KEYS = ("id", "state", "index", "action", "veto", "detail", "dry_run")


def _routine_signature(routines: object) -> str | None:
    """A stable fingerprint of the run's progress, or None when no routine is loaded."""
    if not isinstance(routines, dict):
        return None
    picked = {key: routines.get(key) for key in _ROUTINE_SIGNATURE_KEYS}
    return json.dumps(picked, sort_keys=True, default=str)


class _Subscriber:
    """One connection's two channels."""

    __slots__ = ("ws", "state", "events", "wake", "token")

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self.ws = ws
        self.state: dict[str, object] | None = None
        self.events: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=_EVENT_QUEUE)
        self.wake = asyncio.Event()
        self.token: str | None = None


class EventHub:
    """Fan-out for `/api/v1/events`."""

    def __init__(
        self,
        authorizer: Authorizer,
        sessions: SessionRegistry,
        snapshot: Callable[[], dict[str, object]],
        state_hz: float = 10.0,
        link_loss_s: float = 6.0,
        on_link_loss: Callable[[str], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.authorizer = authorizer
        self.sessions = sessions
        self._snapshot = snapshot
        self.state_hz = max(1.0, state_hz)
        self.link_loss_s = max(1.0, link_loss_s)
        self._on_link_loss = on_link_loss
        self._clock = clock or time.monotonic
        self._subs: set[_Subscriber] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._pump: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._quiet: set[str] = set()

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._pump is None:
            self._pump = asyncio.create_task(self._pump_states(), name="houndmind-state-pump")

    async def stop(self) -> None:
        tasks: list[asyncio.Task[None]] = list(self._tasks)
        if self._pump is not None:
            tasks.append(self._pump)
            self._pump = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for sub in list(self._subs):
            with contextlib.suppress(Exception):
                await sub.ws.close()
        self._subs.clear()

    # ---- publishing --------------------------------------------------------

    async def _pump_states(self) -> None:
        interval = 1.0 / self.state_hz
        last_decision: str | None = None
        last_routine: str | None = None
        while True:
            try:
                snapshot = self._snapshot()
                frame: dict[str, object] = {"type": "state", "data": snapshot}
                for sub in list(self._subs):
                    sub.state = frame  # latest value: assignment *is* the queue policy
                    sub.wake.set()
                # The `decision` event fires on a change of *choice*, not on a tick (C7). `event`
                # is the non-droppable channel, so a per-tick event would turn a six-second stall
                # into a disconnect - and `state` already carries the current decision.
                decision = snapshot.get("decision")
                signature = _decision_signature(decision)
                if isinstance(decision, dict) and signature != last_decision:
                    last_decision = signature
                    self.publish_event("decision", decision)
                # Same rule for a routine: the runner re-publishes `routine_run` every tick, so
                # only a new step, state or veto is a frame. A finished run keeps its block, which
                # is how a client learns it ended without polling.
                routines = snapshot.get("routines")
                routine_signature = _routine_signature(routines)
                if isinstance(routines, dict) and routine_signature != last_routine:
                    last_routine = routine_signature
                    self.publish_event("routine", routines)
                self._check_link_loss()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad tick must not kill the stream
                logger.exception("State pump failed")
            await asyncio.sleep(interval)

    def publish_event(self, name: str, data: dict[str, object] | None = None) -> None:
        """Queue an event for every subscriber. Safe to call from the event loop."""
        frame: dict[str, object] = {
            "type": "event",
            "data": {"name": name, "data": data or {}, "ts": self._clock()},
        }
        for sub in list(self._subs):
            self._offer(sub, frame)

    def publish_event_threadsafe(self, name: str, data: dict[str, object] | None = None) -> None:
        """Queue an event from another thread (the decision loop)."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(self.publish_event, name, data)

    def _offer(self, sub: _Subscriber, frame: dict[str, object]) -> None:
        try:
            sub.events.put_nowait(frame)
        except asyncio.QueueFull:
            # The non-droppable channel is full: the client is not reading. Closing is honest.
            logger.warning("WebSocket client too slow; closing the stream")
            with contextlib.suppress(RuntimeError):
                # `close()` is a coroutine; scheduling it keeps this method synchronous.
                asyncio.get_running_loop().create_task(sub.ws.close())
            self._subs.discard(sub)
            return
        sub.wake.set()

    # ---- link loss ---------------------------------------------------------

    def _check_link_loss(self) -> None:
        """A client that stopped pinging loses its command: the deadman for clients."""
        if self._on_link_loss is None:
            return
        quiet = {session.key for session in self.sessions.stale(self.link_loss_s)}
        for key in quiet - self._quiet:
            logger.warning("Client %s went quiet; stopping its command", key)
            with contextlib.suppress(Exception):
                self._on_link_loss(key)
            self.publish_event("command_expired", {"client": key, "reason": "link_loss"})
        self._quiet = quiet

    # ---- the route ---------------------------------------------------------

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30.0, max_msg_size=8192)
        await ws.prepare(request)
        sub = _Subscriber(ws)
        authed = False
        try:
            async for message in ws:
                if message.type is not web.WSMsgType.TEXT:
                    continue
                try:
                    payload = message.json()
                except ValueError:
                    await ws.send_json({"type": "error", "error": "bad_request"})
                    continue
                if not isinstance(payload, dict):
                    await ws.send_json({"type": "error", "error": "bad_request"})
                    continue

                kind = payload.get("type")
                if kind == "hello":
                    authed = await self._hello(ws, sub, str(payload.get("token") or ""))
                    if not authed:
                        break
                    self._subs.add(sub)
                    self._tasks.add(
                        asyncio.create_task(self._send_loop(sub), name="houndmind-ws-sender")
                    )
                elif not authed:
                    # Nothing before `hello` is answered: an unauthenticated socket can make
                    # noise, but it learns nothing about the dog.
                    break
                elif kind == "ping":
                    self.sessions.touch(sub.token or "")
                    await ws.send_json({"type": "pong", "ts": self._clock()})
                else:
                    await ws.send_json(
                        {
                            "type": "error",
                            "error": "bad_request",
                            "detail": f"unknown type {kind!r}",
                        }
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a broken socket is not a process failure
            logger.debug("WebSocket closed with an error", exc_info=True)
        finally:
            self._subs.discard(sub)
            if sub.token:
                self.sessions.detach(sub.token)
            with contextlib.suppress(Exception):
                await ws.close()
        return ws

    async def _hello(self, ws: web.WebSocketResponse, sub: _Subscriber, token: str) -> bool:
        try:
            principal = self.authorizer.authenticate_token(token)
            self.authorizer.require(principal, "state:read")
        except Exception as exc:  # noqa: BLE001 - AuthError, or anything the authorizer raises
            code = getattr(exc, "code", "unauthorized")
            await ws.send_json({"type": "error", "error": code})
            return False

        # One socket per token, as the contract says: the new connection evicts the old one and
        # says so, because two live clients driving one dog is not a feature, it is a race.
        for other in list(self._subs):
            if other.token == token and other is not sub:
                self._subs.discard(other)
                with contextlib.suppress(Exception):
                    await other.ws.send_json(
                        {
                            "type": "error",
                            "error": "superseded",
                            "detail": "another connection with this token took over",
                        }
                    )
                    await other.ws.close()

        sub.token = token
        session, _evicted = self.sessions.attach(token, principal.name, principal.scopes)
        await ws.send_json(
            {
                "type": "welcome",
                "data": {
                    "scopes": sorted(principal.scopes),
                    "device": principal.name,
                    "session": session.to_dict(),
                },
            }
        )
        return True

    async def _send_loop(self, sub: _Subscriber) -> None:
        """Events first (they matter), then the latest state when nothing else is pending."""
        try:
            while not sub.ws.closed:
                frame: dict[str, object] | None
                try:
                    frame = sub.events.get_nowait()
                except asyncio.QueueEmpty:
                    frame = sub.state
                    sub.state = None
                if frame is None:
                    sub.wake.clear()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(sub.wake.wait(), timeout=1.0)
                    continue
                await sub.ws.send_json(frame)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the socket died; the reader loop cleans up
            logger.debug("WebSocket send failed", exc_info=True)
        finally:
            self._subs.discard(sub)