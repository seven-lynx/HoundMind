"""The telemetry stream: one state pump, N subscribers, honest backpressure.

Three frame classes with different rules:

- ``state`` is a **latest value**. A slow client skips frames rather than falling behind; a
  phone on a weak link should show the current distance, not a two-second-old queue.
- ``event`` and ``command_ack`` are **never dropped**. If a client cannot keep up with those,
  it is disconnected, because losing "command_vetoed" is how a user ends up shouting at a dog
  that is refusing to move for a reason nobody told them.
- ``log`` is **dropped, never disconnected** (#170). Log lines arrive in bursts, and a console
  that opened the Logs panel on a slow link should lose lines, not its telemetry. Only a client
  that asked for the channel in `hello` receives it, and only a token holding `admin` is granted
  it: `GET /api/v1/logs` is an `admin` route, and the live tail is the same data.

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
from pathlib import Path
from typing import Any

from aiohttp import web

from houndmind_ai.core.logging_setup import log_file_path
from houndmind_ai.services.auth import Authorizer
from houndmind_ai.services.sessions import SessionRegistry, fingerprint

logger = logging.getLogger(__name__)

__all__ = ["EventHub", "LogTail"]

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
    """One connection's three channels."""

    __slots__ = ("ws", "state", "events", "logs", "wake", "token", "wants_logs")

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self.ws = ws
        self.state: dict[str, object] | None = None
        self.events: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=_EVENT_QUEUE)
        # Latest log batch, not a queue: assignment is the drop policy, exactly like `state`. A client
        # that cannot keep up loses older lines and keeps its socket (#170).
        self.logs: list[str] | None = None
        self.wants_logs = False
        self.wake = asyncio.Event()
        self.token: str | None = None


class EventHub:
    """Fan-out for `/api/v1/events`."""

    def __init__(
        self,
        authorizer: Authorizer,
        sessions: SessionRegistry,
        snapshot: Callable[[], dict[str, object]],
        log_lines: Callable[[], list[str]] | None = None,
        state_hz: float = 10.0,
        link_loss_s: float = 6.0,
        on_link_loss: Callable[[str], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.authorizer = authorizer
        self.sessions = sessions
        self._snapshot = snapshot
        # New lines from the log file, or None when this plane has no log channel. Injected rather
        # than discovered: the hub reads no settings and opens no files of its own.
        self._log_lines = log_lines
        self.state_hz = max(1.0, state_hz)
        self.link_loss_s = max(1.0, link_loss_s)
        self._on_link_loss = on_link_loss
        self._clock = clock or time.monotonic
        self._subs: set[_Subscriber] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._pump: asyncio.Task[None] | None = None
        self._quiet: set[str] = set()

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
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

    async def close_session(self, key: str) -> int:
        """Close every socket a session holds, and say how many (#404).

        `DELETE /api/v1/sessions/{key}` has to be a real eviction: a registry-only removal would
        report `connected: false` while the socket kept its state stream. The socket's own cleanup
        detaches the session, so the registry follows without a second write path.
        """
        closed = 0
        for sub in list(self._subs):
            if sub.token is None or fingerprint(sub.token) != key:
                continue
            self._subs.discard(sub)
            with contextlib.suppress(Exception):
                await sub.ws.close(code=4001, message=b"detached by an admin")
            closed += 1
        return closed

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
                # The log channel (#170): read only when a subscriber actually asked for it, so a
                # plane with no Logs panel open does no file I/O at all. A burst past the handler's
                # line cap is truncated there, not queued here - the client loses old lines, which
                # is the whole point of a droppable class.
                if self._log_lines is not None and any(sub.wants_logs for sub in self._subs):
                    batch = self._log_lines()
                    if batch:
                        for sub in list(self._subs):
                            if sub.wants_logs:
                                sub.logs = batch  # newest batch wins; an older one is dropped
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
        """Queue an event for every subscriber. Safe to call from the event loop only.

        One publish path on purpose (#53). Every event this control plane sends is raised here, by
        the state pump, which runs on the aiohttp loop: a module that has something to say writes
        it into the context and the pump broadcasts the change. There was a second, threadsafe
        entry point once; it never had a caller, and an unused helper labelled "threadsafe" reads
        as the safe choice for a decision-loop producer. A producer that needs a frame puts a
        value in the context and lets the pump see it.

        """
        frame: dict[str, object] = {
            "type": "event",
            "data": {"name": name, "data": data or {}, "ts": self._clock()},
        }
        for sub in list(self._subs):
            self._offer(sub, frame)

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
                    authed = await self._hello(
                        ws,
                        sub,
                        str(payload.get("token") or ""),
                        bool(payload.get("logs")),
                    )
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

    async def _hello(
        self,
        ws: web.WebSocketResponse,
        sub: _Subscriber,
        token: str,
        wants_logs: bool = False,
    ) -> bool:
        try:
            principal = self.authorizer.authenticate_token(token)
            self.authorizer.require(principal, "state:read")
        except Exception as exc:  # noqa: BLE001 - AuthError, or anything the authorizer raises
            code = getattr(exc, "code", "unauthorized")
            await ws.send_json({"type": "error", "error": code})
            return False

        # The log channel is `admin`'s business, exactly as `GET /api/v1/logs` is (#170). A token
        # without it keeps the socket and simply does not get the channel: refusing the upgrade
        # would take the state stream away from a paired phone to punish it for asking.
        sub.wants_logs = bool(wants_logs) and "admin" in principal.scopes

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
                    # Whether the requested log channel was granted: the client asked for it in
                    # `hello`, and a token without `admin` is refused without losing its socket.
                    "logs": sub.wants_logs,
                },
            }
        )
        return True

    async def _send_loop(self, sub: _Subscriber) -> None:
        """Events first (they matter), then one log batch, then the latest state.

        One frame per turn keeps the promise of each class: an event can never be starved by a log
        burst, and a log burst can delay telemetry by at most one frame.
        """
        try:
            while not sub.ws.closed:
                frame: dict[str, object] | None
                try:
                    frame = sub.events.get_nowait()
                except asyncio.QueueEmpty:
                    if sub.logs is not None:
                        frame = {"type": "log", "data": {"lines": sub.logs}}
                        sub.logs = None
                    else:
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
class LogTail:
    """New lines appended to the configured log file, for the `log` frame class (#170).

    The file is the one `GET /api/v1/logs` reads, resolved by the same `log_file_path`, so the live
    tail cannot disagree with the polled history. `read_new` never raises: an unreadable, missing or
    rotated file means "nothing this tick", not a dead stream.

    The first call starts at the current end of the file. The client has already fetched the history;
    the live channel is for what happens next, and replaying the file on connect would duplicate it.
    """

    def __init__(
        self, context: Any, *, max_lines: int = 200, max_bytes: int = 64 * 1024
    ) -> None:
        self._context = context
        self._max_lines = max(1, max_lines)
        self._max_bytes = max(1, max_bytes)
        self._path: Path | None = None
        self._offset = 0
        self._identity: tuple[int, int] | None = None

    def read_new(self) -> list[str]:
        """Lines written since the last call, oldest first, at most `max_lines` of them."""
        getter = getattr(self._context, "get", None)
        settings = getter("settings") if callable(getter) else None
        path = log_file_path(settings)
        if path is None:
            return []
        try:
            stat = path.stat()
        except OSError:
            return []
        identity = (stat.st_dev, stat.st_ino)
        same_file = path == self._path and identity == self._identity
        if not same_file or stat.st_size < self._offset:
            # First call, a rotated file, or a truncation: start from the end and replay nothing.
            self._path = path
            self._identity = identity
            self._offset = stat.st_size
            return []
        if stat.st_size == self._offset:
            return []
        start = max(self._offset, stat.st_size - self._max_bytes)
        try:
            with path.open("rb") as handle:
                if self._offset:
                    # An inode can be **reused** by the file that replaced it - Linux handed the new
                    # log the same one in CI - so the identity above is not proof. Confirm instead
                    # that the last byte consumed is still the line break this reader left behind:
                    # one byte per tick, and it is what stops a rotated log being read from the
                    # middle as a fragment ("ted").
                    handle.seek(self._offset - 1)
                    if handle.read(1) != b"\n":
                        self._offset = stat.st_size
                        return []
                handle.seek(start)
                chunk = handle.read(stat.st_size - start)
        except OSError:
            return []
        cut = chunk.rfind(b"\n")
        if cut == -1:
            # Only a partial line has been written so far: the rest arrives on a later tick.
            return []
        complete = chunk[: cut + 1]
        # Advance past whole lines only. Publishing a half-written record and then re-reading its
        # tail as a fragment would put two broken lines in the panel for one record.
        self._offset = start + len(complete)
        lines = complete.decode("utf-8", errors="replace").splitlines()
        return lines[-self._max_lines :]
