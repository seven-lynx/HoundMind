"""Detaching a session closes its socket (#404).

`DELETE /api/v1/sessions/{key}` has to be a real eviction: a registry-only removal would report
`connected: false` while the socket kept receiving state, which is the kind of lie a "who is
connected" route exists to prevent. The hub closes the socket; the socket's own cleanup detaches the
session, so there is one path and no second copy of the state.
"""

from __future__ import annotations

import asyncio

from houndmind_ai.services.sessions import SessionRegistry, fingerprint
from houndmind_ai.services.stream import EventHub, _Subscriber


class FakeWS:
    def __init__(self) -> None:
        self.closed: tuple[int, bytes] | None = None

    async def close(self, code: int = 0, message: bytes = b"") -> None:
        self.closed = (code, message)


def build(*tokens: str) -> tuple[EventHub, list[_Subscriber]]:
    hub = EventHub(authorizer=None, sessions=SessionRegistry(), snapshot=lambda: {})
    subs: list[_Subscriber] = []
    for token in tokens:
        sub = _Subscriber(FakeWS())
        sub.token = token
        hub._subs.add(sub)
        subs.append(sub)
    return hub, subs


def test_detaching_closes_only_the_sockets_that_belong_to_the_session() -> None:
    hub, (victim, bystander) = build("token-a", "token-b")

    closed = asyncio.run(hub.close_session(fingerprint("token-a")))

    assert closed == 1
    assert victim.ws.closed is not None
    assert victim.ws.closed[0] == 4001
    assert victim not in hub._subs
    assert bystander.ws.closed is None, "another client's stream is not touched"
    assert bystander in hub._subs


def test_detaching_a_key_with_no_socket_closes_nothing() -> None:
    hub, (only,) = build("token-a")

    assert asyncio.run(hub.close_session(fingerprint("nobody"))) == 0
    assert only.ws.closed is None
