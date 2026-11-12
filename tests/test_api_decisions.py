"""`GET /api/v1/decisions`: the ring, the limit, and the difference between empty and absent.

An empty list and a dead feed are different answers to the same question, so this route says 503
when nothing is publishing rather than letting a client render "the dog decided nothing" forever.
"""

from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.kernel.decisions import DecisionRecord, DecisionRing
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
    )
    return ControlPlane(DummyContext(), settings, CommandBus())


def fill(plane: ControlPlane, count: int, size: int = 200) -> None:
    ring = DecisionRing(size)
    for index in range(count):
        ring.append(
            DecisionRecord(
                ts=float(index),
                mode="patrol",
                state="alert",
                intent="forward",
                source="navigation",
            )
        )
    plane.context.set("decision_ring", ring)


def auth(plane: ControlPlane) -> dict[str, str]:
    return {"Authorization": f"Bearer {plane.tokens.ensure()}"}


def test_the_feed_is_oldest_first(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        fill(plane, 3)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/decisions", headers=auth(plane))
            assert response.status == 200
            body = await response.json()
        assert body["count"] == 3
        assert [record["ts"] for record in body["decisions"]] == [0.0, 1.0, 2.0]
        assert body["decisions"][-1]["schema_version"] == 1

    asyncio.run(scenario())


def test_limit_returns_the_newest_records(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        fill(plane, 5)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/decisions?limit=2", headers=auth(plane))
            body = await response.json()
        assert [record["ts"] for record in body["decisions"]] == [3.0, 4.0]

    asyncio.run(scenario())


def test_the_limit_is_capped_at_two_hundred(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        fill(plane, 200)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/decisions?limit=1000", headers=auth(plane))
            assert response.status == 200
            body = await response.json()
        assert body["count"] == 200

    asyncio.run(scenario())


def test_a_limit_below_one_still_returns_one(tmp_path) -> None:
    """Same rule as `/history`: a limit of zero asks for a sample, not for nothing."""

    async def scenario() -> None:
        plane = make_plane(tmp_path)
        fill(plane, 3)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/decisions?limit=0", headers=auth(plane))
            body = await response.json()
        assert body["count"] == 1

    asyncio.run(scenario())


def test_a_non_integer_limit_is_a_bad_request(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        fill(plane, 3)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/decisions?limit=abc", headers=auth(plane))
            assert response.status == 400
            assert (await response.json())["error"] == "bad_request"

    asyncio.run(scenario())


def test_no_ring_is_a_503_and_says_why(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/decisions", headers=auth(plane))
            assert response.status == 503
            body = await response.json()
        assert body["error"] == "unavailable"
        assert "decision_log" in body["detail"]

    asyncio.run(scenario())


def test_the_route_needs_a_token(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        fill(plane, 1)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/decisions")
            assert response.status == 401

    asyncio.run(scenario())
