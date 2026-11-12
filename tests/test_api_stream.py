"""The WebSocket half of the control plane: auth, telemetry, ping, and supersession.

The REST tests can pass while the stream is completely broken, so these cover the surface a phone
actually holds open: a token that is checked before anything is disclosed, `state` frames at the
configured rate, a ping that is answered, and the rule that one token drives one socket.
"""

from __future__ import annotations

import asyncio

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.kernel.decisions import DecisionRecord
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
from houndmind_ai.services.settings import ApiSettings


class DummyContext:
    def __init__(self) -> None:
        self.data: dict = {"settings": {}, "module_statuses": {}, "trace_id": "trace123"}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def __contains__(self, key):
        return key in self.data


def make_plane(tmp_path) -> ControlPlane:
    settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        state_hz=20.0,
    )
    return ControlPlane(DummyContext(), settings, CommandBus())


async def until(ws, kind: str, timeout: float = 5.0) -> dict:
    """Read frames until one of `kind` arrives. A missing frame fails with the type, not a hang."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        assert remaining > 0, f"no '{kind}' frame arrived in {timeout}s"
        frame = await asyncio.wait_for(ws.receive_json(), timeout=remaining)
        if frame.get("type") == kind:
            return frame


def test_a_bad_token_gets_one_error_and_no_data(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": "not-the-token"})

            frame = await until(ws, "error")

            assert frame["error"] == "unauthorized"
            assert "trace123" not in str(frame), "a rejected socket must learn nothing"

    asyncio.run(scenario())


def test_nothing_is_answered_before_hello(tmp_path) -> None:
    """An unauthenticated socket gets no frames at all: it is closed, not argued with."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "state", "data": {}})

            frame = await asyncio.wait_for(ws.receive(), timeout=5.0)

        assert frame.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED), frame.type

    asyncio.run(scenario())


def test_a_good_token_gets_welcome_state_and_a_pong(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        token = plane.tokens.ensure()
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": token})

            welcome = await until(ws, "welcome")
            state = await until(ws, "state")
            await ws.send_json({"type": "ping"})
            pong = await until(ws, "pong")

        assert "state:read" in welcome["data"]["scopes"]
        assert "sensors" in state["data"], "the snapshot must be the documented one"
        assert "distance_valid" in state["data"]["sensors"]
        assert "ts" in pong

    asyncio.run(scenario())


def test_an_event_reaches_a_subscriber(tmp_path) -> None:
    """`command_vetoed` and friends are the reason a user knows why the dog refused."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        token = plane.tokens.ensure()
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": token})
            await until(ws, "state")

            plane.hub.publish_event("mode_changed", {"mode": "manual"})
            event = await until(ws, "event")

        assert event["data"]["name"] == "mode_changed"
        assert event["data"]["data"]["mode"] == "manual"

    asyncio.run(scenario())


def test_a_second_socket_with_the_same_token_evicts_the_first(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        token = plane.tokens.ensure()
        async with TestClient(TestServer(create_app(plane))) as client:
            first = await client.ws_connect(f"{API_PREFIX}/events")
            await first.send_json({"type": "hello", "token": token})
            await until(first, "welcome")

            second = await client.ws_connect(f"{API_PREFIX}/events")
            await second.send_json({"type": "hello", "token": token})

            evicted = await until(first, "error")
            await until(second, "welcome")

        assert evicted["error"] == "superseded"

    asyncio.run(scenario())


async def until_event(ws, name: str, timeout: float = 5.0) -> dict:
    """Read until the named `event` arrives, skipping state frames and other events."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        assert remaining > 0, f"no '{name}' event arrived in {timeout}s"
        frame = await asyncio.wait_for(ws.receive_json(), timeout=remaining)
        if frame.get("type") == "event" and frame.get("data", {}).get("name") == name:
            return frame


def event_names(frames: list[dict]) -> list[str]:
    return [frame["data"]["name"] for frame in frames if frame.get("type") == "event"]


def test_a_new_choice_is_published_as_a_decision_event(tmp_path) -> None:
    """The pump is the only producer, so the event has to come from it, not from a module."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": plane.tokens.ensure()})
            await until(ws, "welcome")

            plane.context.set(
                "decision_record",
                DecisionRecord(ts=1.0, mode="patrol", intent="forward", source="navigation"),
            )
            event = await until_event(ws, "decision")
            await ws.close()

        assert event["data"]["data"]["intent"] == "forward"
        assert event["data"]["data"]["ts"] == 1.0

    asyncio.run(scenario())


def test_a_new_reading_does_not_emit_a_second_decision_event(tmp_path) -> None:
    """A moved sensor is not a decision. Ten events a second would break the never-drop rule."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            ws = await client.ws_connect(f"{API_PREFIX}/events")
            await ws.send_json({"type": "hello", "token": plane.tokens.ensure()})
            await until(ws, "welcome")

            plane.context.set(
                "decision_record",
                DecisionRecord(ts=1.0, mode="patrol", intent="forward", source="navigation"),
            )
            await until_event(ws, "decision")

            # Same choice, next tick, a different reading.
            plane.context.set(
                "decision_record",
                DecisionRecord(
                    ts=2.0,
                    mode="patrol",
                    intent="forward",
                    source="navigation",
                    inputs={"distance_cm": 20.0, "distance_valid": True},
                ),
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 0.4
            frames: list[dict] = []
            while loop.time() < deadline:
                frames.append(await asyncio.wait_for(ws.receive_json(), timeout=1.0))
            await ws.close()

        assert "decision" not in event_names(frames)
        assert any(frame.get("type") == "state" for frame in frames), "the pump kept running"

    asyncio.run(scenario())