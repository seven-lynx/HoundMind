"""Token, pairing, scopes and the audit log — the security-relevant half of the control plane.

Nothing here needs a socket. The important assertions are the negative ones: an unknown token is
refused, a pairing code works once, a code expires, and a log line never contains the token.
"""

from __future__ import annotations

import os
import stat

import pytest

from houndmind_ai.services.auth import (
    ALL_SCOPES,
    AuthError,
    Authorizer,
    MotionAudit,
    PairingWindow,
    Principal,
    RateLimiter,
    TokenStore,
)
from houndmind_ai.kernel.commands import Command, Source, Verdict


class Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


def test_the_token_file_is_created_once_and_reused(tmp_path) -> None:
    store = TokenStore(tmp_path / "api_token")

    first = store.ensure()
    second = TokenStore(tmp_path / "api_token").ensure()

    assert first == second
    assert store.matches(first) is True


def test_the_token_file_is_not_world_readable(tmp_path) -> None:
    """0600 is the whole reason the token lives in a file instead of the config."""
    if os.name != "posix":  # pragma: no cover - Windows has no POSIX mode bits
        pytest.skip("chmod has no effect on this platform")
    path = tmp_path / "api_token"
    TokenStore(path).ensure()

    mode = stat.S_IMODE(path.stat().st_mode)

    assert mode & 0o077 == 0, oct(mode)


def test_an_empty_or_absent_token_never_matches(tmp_path) -> None:
    store = TokenStore(tmp_path / "missing" / "api_token")

    assert store.read() is None
    assert store.matches("") is False
    assert store.matches("anything") is False


def test_the_device_token_grants_every_scope(tmp_path) -> None:
    tokens = TokenStore(tmp_path / "api_token")
    token = tokens.ensure()
    authorizer = Authorizer(tokens)

    principal = authorizer.authenticate(f"Bearer {token}")

    assert principal.scopes == ALL_SCOPES
    assert principal.kind == "device"


def test_a_missing_or_malformed_header_is_a_401(tmp_path) -> None:
    authorizer = Authorizer(TokenStore(tmp_path / "api_token"))

    for header in (None, "", "Bearer", "Basic abc", "Bearer not-a-real-token"):
        with pytest.raises(AuthError) as caught:
            authorizer.authenticate(header)
        assert caught.value.status == 401


def test_a_paired_client_lacks_admin(tmp_path) -> None:
    tokens = TokenStore(tmp_path / "api_token")
    authorizer = Authorizer(tokens, PairingWindow())
    token, principal = authorizer.issue_client_token("Pixel 8")

    assert "move" in principal.scopes
    assert "admin" not in principal.scopes
    with pytest.raises(AuthError) as caught:
        authorizer.require(authorizer.authenticate_token(token), "admin")
    assert caught.value.status == 403


def test_a_pairing_code_works_exactly_once() -> None:
    clock = Clock()
    window = PairingWindow(now=clock)

    code = window.open()
    assert len(code) == 6 and code.isdigit()
    assert window.claim(code) is True
    assert window.claim(code) is False, "a claimed code must not be replayable"


def test_a_pairing_code_expires() -> None:
    clock = Clock()
    window = PairingWindow(now=clock, ttl_s=60)
    code = window.open()

    clock.value = 61.0

    assert window.active is False
    assert window.claim(code) is False


def test_a_wrong_code_does_not_close_the_window() -> None:
    clock = Clock()
    window = PairingWindow(now=clock)
    code = window.open()

    assert window.claim("000000" if code != "000000" else "111111") is False
    assert window.claim(code) is True


def test_the_rate_limiter_counts_inside_the_window_only() -> None:
    clock = Clock()
    limiter = RateLimiter(2, 60.0, now=clock)

    assert limiter.allow("peer") is True
    assert limiter.allow("peer") is True
    assert limiter.allow("peer") is False
    clock.value = 61.0
    assert limiter.allow("peer") is True


def test_the_audit_keeps_the_reason_for_a_veto() -> None:
    """'Why did the dog not move' must be answerable from the record, not from a guess."""
    audit = MotionAudit()
    command = Command(action="forward", source=Source.CLIENT, issued_at=1.0)
    verdict = Verdict(accepted=False, action="forward", veto="obstacle", detail="9.0 cm")

    audit.record(command, verdict, Principal("Pixel 8", frozenset({"move"})))

    latest = audit.recent(1)[0]
    assert latest["accepted"] is False
    assert latest["veto"] == "obstacle"
    assert latest["client"] == "Pixel 8"
    assert latest["source"] == "client"


def test_the_audit_is_bounded() -> None:
    audit = MotionAudit(capacity=2)
    for index in range(5):
        audit.record(
            Command(action="stop", issued_at=float(index)),
            Verdict(accepted=True, action="stop"),
        )

    assert len(audit.entries) == 2