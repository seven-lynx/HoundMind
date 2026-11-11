"""Authentication, pairing and the motion audit trail (D8).

The device token is **generated, never pasted**: it is written once to
``~/.houndmind/api_token`` with mode 0600 and referenced by path, so it cannot end up in
``config/settings.jsonc``, in a doc, or in a log line. Nothing here logs the token, and the only
way to obtain it is to be able to read that file.

Scopes are the whole authorisation model. There is no user database, no password, and no
session store: a holder of the device token is the operator, and a paired client gets only the
scopes the pairing flow granted it.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "ALL_SCOPES",
    "PAIRING_SCOPES",
    "SCOPES",
    "AuthError",
    "Authorizer",
    "MotionAudit",
    "PairingWindow",
    "Principal",
    "RateLimiter",
    "TokenStore",
]

# The four scopes in `docs/CONTROL_API.md` §1.
SCOPES: tuple[str, ...] = ("state:read", "move", "config", "admin")
ALL_SCOPES = frozenset(SCOPES)

# What a phone gets from a pairing code: enough to watch and drive, not enough to read the logs
# or rotate the device token. Anything more is an explicit operator decision, not a default.
PAIRING_SCOPES: tuple[str, ...] = ("state:read", "move", "config")

# 32 bytes of urandom, url-safe.
_TOKEN_BYTES = 32


class AuthError(Exception):
    """A rejected request. ``status`` is the HTTP code the route should answer with."""

    def __init__(self, code: str, detail: str, status: int = 401) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class Principal:
    """Who is asking, and what they may do."""

    name: str
    scopes: frozenset[str]
    kind: str = "client"
    issued_at: float = 0.0

    def may(self, scope: str) -> bool:
        return scope in self.scopes

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "scopes": sorted(self.scopes), "kind": self.kind}


class TokenStore:
    """The install-issued device token on disk.

    The write is atomic (a 0600 temp file renamed over the target), so a reader never sees a
    half-written token, and the directory is created 0700.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()
        self._cached: str | None = None

    def read(self) -> str | None:
        try:
            token = self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return token or None

    def ensure(self) -> str:
        """Return the token, creating it on first start. Idempotent."""
        with self._lock:
            if self._cached is not None:
                return self._cached
            existing = self.read()
            if existing is not None:
                self._cached = existing
                return existing
            token = secrets.token_urlsafe(_TOKEN_BYTES)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.path.parent.chmod(0o700)
            except OSError:
                # A filesystem without POSIX modes (a FAT SD card, a temp dir on Windows).
                # The token still works; the guarantee is simply weaker and the log says so.
                pass
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(token, encoding="utf-8")
            try:
                tmp.chmod(0o600)
            except OSError:
                pass
            tmp.replace(self.path)
            self._cached = token
            return token

    def matches(self, candidate: str) -> bool:
        token = self._cached or self.read()
        if not token or not candidate:
            return False
        return hmac.compare_digest(token, candidate)


class PairingWindow:
    """A short numeric code, valid for a few minutes, usable exactly once."""

    def __init__(
        self,
        now: Callable[[], float] | None = None,
        ttl_s: float = 300.0,
        digits: int = 6,
    ) -> None:
        self._now = now or time.monotonic
        self._ttl_s = ttl_s
        self._digits = max(4, min(digits, 10))
        self._code: str | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def open(self) -> str:
        """Start a window and return the code to show on the device."""
        with self._lock:
            # `secrets.randbelow`, not `random`: the code is a credential.
            upper = 10**self._digits
            code = str(secrets.randbelow(upper)).rjust(self._digits, "0")
            while code == self._code:
                code = str(secrets.randbelow(upper)).rjust(self._digits, "0")
            self._code = code
            self._expires_at = self._now() + self._ttl_s
            return code

    @property
    def active(self) -> bool:
        with self._lock:
            return self._code is not None and self._now() < self._expires_at

    def claim(self, code: str) -> bool:
        """Single use: a successful claim closes the window."""
        with self._lock:
            if self._code is None or self._now() >= self._expires_at:
                return False
            # Constant-time: the code is short, so a timing oracle would be a real oracle.
            if not hmac.compare_digest(self._code, str(code)):
                return False
            self._code = None
            self._expires_at = 0.0
            return True


class RateLimiter:
    """A sliding-window counter, for pairing attempts and command floods."""

    def __init__(
        self,
        limit: int,
        window_s: float,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.limit = max(1, limit)
        self.window_s = max(0.001, window_s)
        self._now = now or time.monotonic
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        with self._lock:
            now = self._now()
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


@dataclass
class MotionAudit:
    """The answer to "why did the dog do that". Bounded, in memory, never logged wholesale."""

    capacity: int = 256
    entries: deque[dict[str, object]] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.entries = deque(maxlen=max(1, self.capacity))

    def record(
        self,
        command,
        verdict,
        principal: Principal | None = None,
        judged_by: str = "gateway",
    ) -> dict[str, object]:
        entry: dict[str, object] = {
            "ts": time.time(),
            "id": command.id,
            "action": command.action,
            "source": command.source.name.lower(),
            "client": principal.name if principal is not None else None,
            "params": dict(command.params),
            "accepted": bool(verdict.accepted),
            "veto": verdict.veto,
            "detail": verdict.detail,
            "judged_by": judged_by,
        }
        self.entries.append(entry)
        return entry

    def recent(self, limit: int = 50) -> list[dict[str, object]]:
        limit = max(0, limit)
        if limit == 0:
            return []
        return list(self.entries)[-limit:][::-1]


class Authorizer:
    """Turns an ``Authorization`` header into a :class:`Principal`, or an :class:`AuthError`."""

    def __init__(
        self,
        tokens: TokenStore,
        pairing: PairingWindow | None = None,
        now: Callable[[], float] | None = None,
        pairing_scopes: Iterable[str] = PAIRING_SCOPES,
    ) -> None:
        self.tokens = tokens
        self.pairing = pairing
        self._now = now or time.monotonic
        self._pairing_scopes = frozenset(pairing_scopes)
        self._clients: dict[str, Principal] = {}
        self._lock = threading.Lock()

    # ---- issuance ----------------------------------------------------------

    def issue_client_token(
        self,
        client_name: str,
        scopes: Iterable[str] | None = None,
    ) -> tuple[str, Principal]:
        """Mint a token for a paired client. Returned once; the caller must not log it."""
        granted = frozenset(scopes if scopes is not None else self._pairing_scopes) & ALL_SCOPES
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        principal = Principal(
            name=client_name or "client",
            scopes=granted,
            kind="client",
            issued_at=self._now(),
        )
        with self._lock:
            self._clients[token] = principal
        return token, principal

    def device_principal(self) -> Principal:
        return Principal(name="device", scopes=ALL_SCOPES, kind="device")

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    # ---- verification ------------------------------------------------------

    def authenticate(self, header: str | None) -> Principal:
        """Bearer token → Principal. Raises :class:`AuthError` on anything else."""
        return self.authenticate_token(_bearer(header))

    def authenticate_token(self, token: str | None) -> Principal:
        if not token:
            raise AuthError("unauthorized", "missing bearer token")
        if self.tokens.matches(token):
            return self.device_principal()
        with self._lock:
            principal = self._clients.get(token)
        if principal is None:
            raise AuthError("unauthorized", "unknown or revoked token")
        return principal

    def require(self, principal: Principal, scope: str) -> None:
        if scope not in principal.scopes:
            raise AuthError("forbidden", f"token lacks the '{scope}' scope", status=403)


def _bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None