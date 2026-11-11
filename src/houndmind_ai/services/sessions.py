"""Who is connected, and what they asked for (M-13).

The legacy runtime had a `trace_id` per process and nothing else, so no client could answer
"what did I ask, and what happened". A session is the missing half: it ties a connection to the
commands it issued, without ever storing the token itself.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

__all__ = ["ClientSession", "SessionRegistry", "fingerprint"]


def fingerprint(token: str) -> str:
    """A stable, non-reversible label for a token. The token itself is never stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


@dataclass
class ClientSession:
    key: str
    name: str
    scopes: frozenset[str]
    connected_at: float
    last_seen: float
    commands: int = 0
    connections: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "scopes": sorted(self.scopes),
            "connected_s": max(0.0, self.last_seen - self.connected_at),
            "commands": self.commands,
            "connected": self.connections > 0,
        }


@dataclass
class SessionRegistry:
    """Bounded, in-memory, keyed by token fingerprint."""

    now: Callable[[], float] = time.monotonic
    max_clients: int = 8
    _sessions: dict[str, ClientSession] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def attach(
        self,
        token: str,
        name: str,
        scopes: Iterable[str],
    ) -> tuple[ClientSession, ClientSession | None]:
        """Register a connection. Returns the session and the one it evicted, if any.

        A second socket with the same token supersedes the first: two live clients driving one
        dog is not a feature, it is a race.
        """
        key = fingerprint(token)
        now = self.now()
        with self._lock:
            session = self._sessions.get(key)
            evicted: ClientSession | None = None
            if session is not None and session.connections > 0:
                evicted = ClientSession(
                    key=session.key,
                    name=session.name,
                    scopes=session.scopes,
                    connected_at=session.connected_at,
                    last_seen=session.last_seen,
                    commands=session.commands,
                    connections=session.connections,
                )
                session.connections = 1
                session.last_seen = now
            elif session is not None:
                session.connections = 1
                session.last_seen = now
                session.scopes = frozenset(scopes)
            else:
                session = ClientSession(
                    key=key,
                    name=name or "client",
                    scopes=frozenset(scopes),
                    connected_at=now,
                    last_seen=now,
                )
                self._sessions[key] = session
                self._evict_if_needed()
            return session, evicted

    def detach(self, token: str) -> None:
        key = fingerprint(token)
        with self._lock:
            session = self._sessions.get(key)
            if session is not None and session.connections > 0:
                session.connections -= 1

    def touch(self, token: str) -> ClientSession | None:
        key = fingerprint(token)
        with self._lock:
            session = self._sessions.get(key)
            if session is not None:
                session.last_seen = self.now()
            return session

    def record_command(self, token: str | None) -> None:
        if token is None:
            return
        key = fingerprint(token)
        with self._lock:
            session = self._sessions.get(key)
            if session is not None:
                session.commands += 1

    def get(self, token: str) -> ClientSession | None:
        with self._lock:
            return self._sessions.get(fingerprint(token))

    def stale(self, timeout_s: float) -> list[ClientSession]:
        """Connected clients that have gone quiet. The link-loss check reads this."""
        now = self.now()
        with self._lock:
            return [
                session
                for session in self._sessions.values()
                if session.connections > 0 and (now - session.last_seen) > timeout_s
            ]

    def active(self) -> list[dict[str, object]]:
        with self._lock:
            return [session.to_dict() for session in self._sessions.values()]

    def count(self) -> int:
        with self._lock:
            return sum(1 for session in self._sessions.values() if session.connections > 0)

    def _evict_if_needed(self) -> None:
        """Drop the least recently seen idle session when the cap is reached."""
        while len(self._sessions) > max(1, self.max_clients):
            idle = [s for s in self._sessions.values() if s.connections == 0]
            victim = min(idle or self._sessions.values(), key=lambda s: s.last_seen)
            self._sessions.pop(victim.key, None)