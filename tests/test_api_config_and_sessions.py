"""`POST /config/validate` and the session routes (#406, #404).

Two gaps this holds shut: a config change could only be tried by applying it, and "who is connected"
could only be answered with a support bundle. The validate route runs the PATCH's own loop and stops
before `persist_config`, so the two answers cannot drift; the sessions routes read the registry and
close a socket rather than pretending to.
"""

from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
from houndmind_ai.services.sessions import fingerprint
from houndmind_ai.services.settings import ApiSettings


class DummyContext:
    def __init__(self, settings: dict) -> None:
        self.data: dict = {"settings": settings, "module_statuses": {}, "trace_id": "trace123"}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value

    def __contains__(self, key) -> bool:
        return key in self.data


def make_plane(tmp_path, settings: dict | None = None) -> ControlPlane:
    plane_settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        pairing_enabled=True,
    )
    table = (
        settings
        if settings is not None
        else {"led": {"brightness": 1.0}, "behavior": {"action_cooldown_s": 2.0}}
    )
    return ControlPlane(DummyContext(table), plane_settings, CommandBus())


def test_a_valid_change_is_accepted_and_nothing_is_written(tmp_path) -> None:
    async def scenario() -> tuple[int, dict, dict]:
        plane = make_plane(tmp_path)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/config/validate",
                json={"led.brightness": 0.4},
                headers=headers,
            )
            body = await response.json()
        return response.status, body, plane.context.get("settings")

    status, body, settings = asyncio.run(scenario())

    assert status == 200
    assert body["ok"] is True
    assert body["would_apply"] == {"led.brightness": 0.4}
    assert body["persisted"] is False
    assert settings["led"]["brightness"] == 1.0, "validate applies nothing"


def test_a_value_the_schema_refuses_is_named_not_raised(tmp_path) -> None:
    async def scenario() -> tuple[int, dict]:
        plane = make_plane(tmp_path)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/config/validate",
                json={"behavior.action_cooldown_s": "soon"},
                headers=headers,
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 200, "the question was answered, so it is not an error"
    assert body["ok"] is False
    assert [entry["key"] for entry in body["invalid"]] == ["behavior.action_cooldown_s"]
    assert body["persisted"] is False


def test_a_key_that_is_not_live_is_rejected_without_writing(tmp_path) -> None:
    async def scenario() -> dict:
        plane = make_plane(tmp_path)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/config/validate", json={"wifi.ssid": "home"}, headers=headers
            )
            return await response.json()

    body = asyncio.run(scenario())

    assert body["ok"] is False
    assert body["rejected"] == ["wifi.ssid"]


def test_sessions_says_who_is_connected_without_the_token(tmp_path) -> None:
    async def scenario() -> tuple[dict, int]:
        plane = make_plane(tmp_path)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        plane.sessions.attach("bench-token", "bench phone", ["state:read", "move"])
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/sessions", headers=headers)
            return await response.json(), plane.sessions.max_clients

    body, limit = asyncio.run(scenario())

    assert body["limit"] == limit
    entry = next(item for item in body["sessions"] if item["name"] == "bench phone")
    assert entry["key"] == fingerprint("bench-token")
    assert entry["scopes"] == ["move", "state:read"]
    assert entry["connected"] is True
    assert "bench-token" not in str(body), "the token itself is never reported"


def test_detaching_a_key_with_no_socket_is_a_404(tmp_path) -> None:
    async def scenario() -> tuple[int, dict]:
        plane = make_plane(tmp_path)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.delete(
                f"{API_PREFIX}/sessions/{fingerprint('nobody')}", headers=headers
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 404
    assert body["error"] == "not_found"
