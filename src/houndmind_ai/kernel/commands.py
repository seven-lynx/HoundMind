"""Typed commands: the one vocabulary every motion producer speaks.

Replaces the legacy pattern where ``safety_action``, ``watchdog_action``,
``navigation_action`` and ``behavior_action`` were four context strings merged by a
hand-written precedence chain and deduplicated by string equality.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

__all__ = [
    "FORWARD_ACTIONS",
    "KNOWN_ACTIONS",
    "MOTION_ACTIONS",
    "Command",
    "CommandBus",
    "Source",
    "Verdict",
]


class Source(IntEnum):
    """Who asked for the motion. Higher wins.

    Ordered explicitly so precedence is declared once, here, instead of being rediscovered
    by the order of keys in a lookup chain.
    """

    BEHAVIOUR = 10
    NAVIGATION = 20
    CLIENT = 30
    WATCHDOG = 40
    SYSTEM = 50


MOTION_ACTIONS = frozenset({"forward", "backward", "turn_left", "turn_right"})
FORWARD_ACTIONS = frozenset({"forward"})
KNOWN_ACTIONS = MOTION_ACTIONS | frozenset(
    {
        "stop",
        "stand",
        "sit",
        "lie",
        "stretch",
        "wag_tail",
        "bark",
        "head",
    }
)

DEFAULT_TTL_MS = 300

# The modes a client may switch between (`POST /api/v1/mode`). They live here, next to the
# command vocabulary, because the gateway and the control plane must agree on the spelling:
# `rest` is the one mode that vetoes client motion, and two definitions of that string is how
# a safety rule quietly stops applying.
RUNTIME_MODES: tuple[str, ...] = ("idle", "patrol", "manual", "rest")
DEFAULT_MODE = "idle"


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass(frozen=True)
class Command:
    """A request to move. Immutable: renew it, do not mutate it."""

    action: str
    source: Source = Source.CLIENT
    params: dict[str, Any] = field(default_factory=dict)
    ttl_ms: int = DEFAULT_TTL_MS
    issued_at: float = 0.0
    id: str = field(default_factory=_new_id)

    def deadline(self) -> float:
        """Epoch/monotonic seconds after which this command must not run."""
        return self.issued_at + (max(0, self.ttl_ms) / 1000.0)

    def expired(self, now: float) -> bool:
        return now > self.deadline()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "action": self.action,
            "source": self.source.name.lower(),
            "params": dict(self.params),
            "ttl_ms": self.ttl_ms,
            "issued_at": self.issued_at,
        }


@dataclass(frozen=True)
class Verdict:
    """The interlock's answer. A refusal always carries a reason."""

    accepted: bool
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    veto: str | None = None
    detail: str | None = None
    retry_after_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "accepted": self.accepted,
            "action": self.action,
            "params": dict(self.params),
        }
        if not self.accepted:
            payload["veto"] = self.veto
            payload["detail"] = self.detail
            payload["retry_after_ms"] = self.retry_after_ms
        elif self.detail:
            payload["detail"] = self.detail
        return payload


class CommandBus:
    """The hand-off between the control plane and the actuator gateway.

    The two live on different threads by design: the control plane runs an asyncio loop so it
    can hold a hundred WebSocket clients, and the decision loop must never block on a socket.
    A bounded queue plus a per-command acknowledgement is the whole contract between them.

    Two properties are deliberate:

    - **Bounded.** ``submit`` never blocks. A client that spams commands gets a refusal it can
      read (429 with ``Retry-After``), not a latency spike on the servo bus.
    - **Acknowledged.** Every submitted command gets exactly one :class:`Verdict`, produced by
      the gateway after the interlock has seen it, so ``POST /command`` can answer 202 or 409
      truthfully instead of guessing.
    """

    # Acks for commands nobody is waiting on (a renewal that lost a race, say) would otherwise
    # accumulate forever. This cap is far above any realistic in-flight count.
    _ACK_CAP = 256

    def __init__(self, maxsize: int = 64) -> None:
        self._queue: queue.Queue[Command] = queue.Queue(maxsize=max(1, maxsize))
        self._lock = threading.Lock()
        self._acks: dict[str, Verdict] = {}
        self._waiters: dict[str, threading.Event] = {}
        self.dropped = 0
        self.submitted = 0

    # ---- producer side -----------------------------------------------------

    def submit(self, command: Command) -> bool:
        """Queue a command. False means the queue is full and nothing was queued."""
        try:
            self._queue.put_nowait(command)
        except queue.Full:
            self.dropped += 1
            return False
        self.submitted += 1
        return True

    def wait(self, command_id: str, timeout: float) -> Verdict | None:
        """Block until the gateway has judged ``command_id``, or return None on timeout.

        Called by the HTTP thread. A timeout is not a veto: it means the decision loop is not
        running, which the route reports as 503 rather than as an accepted command.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            verdict = self._acks.pop(command_id, None)
            if verdict is not None:
                return verdict
            event = threading.Event()
            self._waiters[command_id] = event
        try:
            if not event.wait(max(0.0, deadline - time.monotonic())):
                return None
            with self._lock:
                return self._acks.pop(command_id, None)
        finally:
            with self._lock:
                self._waiters.pop(command_id, None)
                # A verdict that arrived after the timeout must not be left behind.
                self._acks.pop(command_id, None)

    # ---- consumer side -----------------------------------------------------

    def drain(self) -> list[Command]:
        """Take everything queued. Called once per tick, by the gateway."""
        commands: list[Command] = []
        while True:
            try:
                commands.append(self._queue.get_nowait())
            except queue.Empty:
                return commands

    def acknowledge(self, command: Command | None, verdict: Verdict) -> None:
        """Publish the gateway's decision for a command (or for nothing, when None)."""
        if command is None:
            return
        with self._lock:
            self._acks[command.id] = verdict
            while len(self._acks) > self._ACK_CAP:
                self._acks.pop(next(iter(self._acks)))
            event = self._waiters.get(command.id)
            if event is not None:
                event.set()

    # ---- diagnostics -------------------------------------------------------

    @property
    def pending(self) -> int:
        """Commands submitted but not yet drained. A number that should stay small."""
        return self._queue.qsize()

    def __repr__(self) -> str:
        return f"CommandBus(submitted={self.submitted}, dropped={self.dropped}, pending={self.pending})"