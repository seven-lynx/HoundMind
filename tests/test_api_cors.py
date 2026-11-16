"""Cross-origin reads are opt-in, one origin at a time (#202).

A console on another origin could not read this plane at all: `fetch` was blocked at the response
while the WebSocket connected, so the failure mode was a half-broken page rather than an error. The
fix is an allowlist - an operator names the console's origin, and the token stays the boundary. `*`
is never honoured, because it would let any page on the LAN read whichever dog it holds a token for.
"""

from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.services.api import ControlPlane, create_app
from houndmind_ai.services.settings import ApiSettings

CONSOLE = "http://console.local"


class DummyContext:
    def __init__(self) -> None:
        self.data: dict = {"settings": {}, "module_statuses": {}, "trace_id": "trace123"}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value

    def __contains__(self, key) -> bool:
        return key in self.data


def plane_for(tmp_path, origins: tuple[str, ...]) -> ControlPlane:
    settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        pairing_enabled=False,
        cors_origins=origins,
    )
    return ControlPlane(DummyContext(), settings, CommandBus())


def test_a_plain_install_answers_no_cross_origin_read(tmp_path) -> None:
    """The shipped default: nothing changes for an install that has one console."""

    async def scenario() -> None:
        async with TestClient(TestServer(create_app(plane_for(tmp_path, ())))) as client:
            read = await client.get("/api/v1/health", headers={"Origin": CONSOLE})
            preflight = await client.options("/api/v1/state", headers={"Origin": CONSOLE})

        assert "Access-Control-Allow-Origin" not in read.headers
        # No middleware hook: the router answers for itself, exactly as before #202.
        assert preflight.status == 405

    asyncio.run(scenario())


def test_a_listed_origin_can_read_the_response(tmp_path) -> None:
    async def scenario() -> None:
        async with TestClient(TestServer(create_app(plane_for(tmp_path, (CONSOLE,))))) as client:
            response = await client.get("/api/v1/health", headers={"Origin": CONSOLE})

        assert response.status == 200
        assert response.headers["Access-Control-Allow-Origin"] == CONSOLE
        assert response.headers["Vary"] == "Origin"

    asyncio.run(scenario())


def test_an_unlisted_origin_is_not_echoed_even_when_the_list_is_not_empty(tmp_path) -> None:
    async def scenario() -> None:
        async with TestClient(TestServer(create_app(plane_for(tmp_path, (CONSOLE,))))) as client:
            response = await client.get(
                "/api/v1/health", headers={"Origin": "http://somebody-else.local"}
            )

        assert "Access-Control-Allow-Origin" not in response.headers
        # `Vary` still goes out: a cache must not reuse one origin's answer for another.
        assert response.headers["Vary"] == "Origin"

    asyncio.run(scenario())


def test_a_preflight_is_answered_without_a_token(tmp_path) -> None:
    """A browser sends `OPTIONS` with no `Authorization`, so the route check could never pass."""

    async def scenario() -> None:
        async with TestClient(TestServer(create_app(plane_for(tmp_path, (CONSOLE,))))) as client:
            response = await client.options(
                "/api/v1/state",
                headers={
                    "Origin": CONSOLE,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )

        assert response.status == 204
        assert response.headers["Access-Control-Allow-Origin"] == CONSOLE
        assert "Authorization" in response.headers["Access-Control-Allow-Headers"]
        assert "GET" in response.headers["Access-Control-Allow-Methods"]

    asyncio.run(scenario())


def test_the_wildcard_is_dropped_rather_than_honoured() -> None:
    settings = ApiSettings.from_settings(
        {"api": {"cors_origins": ["*", " http://console.local/ ", 7, ""]}}
    )

    assert settings.cors_origins == (CONSOLE,)


def test_slashes_and_duplicates_do_not_create_two_entries() -> None:
    settings = ApiSettings.from_settings(
        {"api": {"cors_origins": [CONSOLE + "/", CONSOLE, CONSOLE]}}
    )

    assert settings.cors_origins == (CONSOLE,)
