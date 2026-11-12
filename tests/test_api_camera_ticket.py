"""Camera tickets: a `<img>` still needs a URL, and the device token must not be that URL (`#18`).

`tests/test_api_routes.py` proves the routes are declared, scoped and refuse anonymous callers, and
that the ticket path serves a frame. This file is about the ticket itself: it is single-use, it
expires, it buys one read and nothing else, and the credential it replaced is refused by name.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
from houndmind_ai.services.auth import StreamTickets
from houndmind_ai.services.settings import ApiSettings

JPEG = b"\xff\xd8jpegdata"


class DummyContext:
    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {"settings": settings or {}, "vision_frame_jpeg": JPEG}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


class Clock:
    """The plane's clock, owned by the test: nothing here sleeps through a ticket's lifetime."""

    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


def plane_for(tmp_path: Path, clock: Clock | None = None) -> ControlPlane:
    settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        pairing_enabled=False,
    )
    return ControlPlane(DummyContext(), settings, CommandBus(), clock=clock or Clock())


def auth(plane: ControlPlane) -> dict[str, str]:
    return {"Authorization": f"Bearer {plane.tokens.ensure()}"}


def test_a_ticket_is_single_use(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            minted = await client.post(f"{API_PREFIX}/camera/ticket", headers=auth(plane))
            body = await minted.json()
            assert minted.status == 200
            assert body["expires_in"] == 60.0
            assert minted.headers.get("Cache-Control") == "no-store"

            first = await client.get(f"{API_PREFIX}/camera/snapshot?ticket={body['ticket']}")
            assert first.status == 200

            # Spent, not reusable: a URL that leaks from here buys nothing a second time.
            again = await client.get(f"{API_PREFIX}/camera/snapshot?ticket={body['ticket']}")
            assert again.status == 401

    asyncio.run(scenario())


def test_a_ticket_expires(tmp_path) -> None:
    async def scenario() -> None:
        clock = Clock()
        plane = plane_for(tmp_path, clock)
        async with TestClient(TestServer(create_app(plane))) as client:
            minted = await client.post(f"{API_PREFIX}/camera/ticket", headers=auth(plane))
            ticket = (await minted.json())["ticket"]

            clock.now += 61.0
            late = await client.get(f"{API_PREFIX}/camera/snapshot?ticket={ticket}")
            assert late.status == 401

    asyncio.run(scenario())


def test_a_ticket_buys_one_read_and_not_a_credential(tmp_path) -> None:
    """The point of a ticket over a second token: it cannot be turned into `move` or `config`."""

    async def scenario() -> None:
        plane = plane_for(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            minted = await client.post(f"{API_PREFIX}/camera/ticket", headers=auth(plane))
            ticket = (await minted.json())["ticket"]

            as_header = await client.get(
                f"{API_PREFIX}/state", headers={"Authorization": f"Bearer {ticket}"}
            )
            assert as_header.status == 401

            # Nor does it reach a route that authenticates itself and then asks for a scope.
            config = await client.get(f"{API_PREFIX}/config?ticket={ticket}")
            assert config.status == 401

    asyncio.run(scenario())


def test_the_device_token_in_a_url_is_refused_by_name(tmp_path) -> None:
    """The 401 has to be actionable: a client that kept the old URL is told what to use."""

    async def scenario() -> None:
        plane = plane_for(tmp_path)
        token = plane.tokens.ensure()
        async with TestClient(TestServer(create_app(plane))) as client:
            for path in ("/camera/stream", "/camera/snapshot"):
                refused = await client.get(f"{API_PREFIX}{path}?token={token}")
                assert refused.status == 401, path
                assert "camera/ticket" in (await refused.json())["detail"]

            # No credential at all is a different message: the caller has to know which it is.
            silent = await client.get(f"{API_PREFIX}/camera/snapshot")
            assert silent.status == 401
            assert "missing camera ticket" in (await silent.json())["detail"]

    asyncio.run(scenario())


def test_a_header_still_works_without_a_ticket(tmp_path) -> None:
    """A client that can set headers is not forced through the ticket dance."""

    async def scenario() -> None:
        plane = plane_for(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/camera/snapshot", headers=auth(plane))
            assert response.status == 200

    asyncio.run(scenario())


def test_tickets_are_bounded() -> None:
    """A client that asks for tickets forever must not grow the store without limit."""

    store = StreamTickets(now=Clock(), max_tickets=2)
    first, ttl = store.issue()
    assert ttl == 60.0
    store.issue()
    store.issue()  # evicts the oldest

    assert store.count == 2
    assert store.claim(first) is False, "an evicted ticket must not still be claimable"

    store.clear()
    assert store.count == 0

