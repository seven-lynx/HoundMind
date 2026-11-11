"""The route table against the contract, and the auth gate across every route.

`docs/CONTROL_API.md` is the source of truth for both clients. The first test is the one that
keeps that true: a route added in code without a contract row (or a contract row with no route)
fails here, which is cheaper than finding out from an Android app that silently stops working.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.services.api import API_PREFIX, ROUTES, ControlPlane, create_app
from houndmind_ai.services.auth import PAIRING_SCOPES
from houndmind_ai.services.settings import ApiSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "CONTROL_API.md"

# `/meta` and `/health` are the unauthenticated liveness surface, by contract. `/pair` is public
# too: it is the exchange that *produces* a token, and it is protected by the pairing code.
PUBLIC = {"/meta", "/health", "/pair"}


class DummyContext:
    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {
            "settings": settings or {},
            "module_statuses": {},
            "trace_id": "trace123",
        }

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
        pairing_enabled=True,
    )
    return ControlPlane(DummyContext(), settings, CommandBus())


def test_every_documented_route_exists_and_no_extra_route_is_served() -> None:
    documented: set[tuple[str, str]] = set()
    pattern = re.compile(r"\|\s*`(GET|POST|PATCH|PUT|DELETE)`\s*\|\s*`([^`]+)`\s*\|")
    for line in DOC.read_text(encoding="utf-8").splitlines():
        match = pattern.search(line)
        if match:
            # A query string in the contract (`?tail=200`) documents a parameter, not a path.
            documented.add((match.group(1), match.group(2).split("?")[0]))

    implemented = {(method, f"{API_PREFIX}{path}") for method, path, _scope, _handler in ROUTES}

    assert implemented == documented, (
        f"missing from code: {sorted(documented - implemented)}; "
        f"missing from the contract: {sorted(implemented - documented)}"
    )


def test_a_scope_is_declared_for_every_route_that_needs_one() -> None:
    """A route with no scope must be one of the two public ones, the camera and the WS."""
    innocent = PUBLIC | {"/events", "/pair", "/camera/stream", "/camera/snapshot"}
    for method, path, scope, _handler in ROUTES:
        if path in innocent:
            continue
        assert scope is not None, f"{method} {path} has no scope and is not public"


def test_an_anonymous_request_is_refused_everywhere_but_liveness(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            for method, path, _scope, _handler in ROUTES:
                if path in PUBLIC or path == "/events":
                    continue
                response = await client.request(method, f"{API_PREFIX}{path}")
                assert response.status == 401, f"{method} {path} answered {response.status}"
                assert (await response.json())["error"] == "unauthorized"

    asyncio.run(scenario())


def test_liveness_and_meta_need_no_token(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            health = await client.get(f"{API_PREFIX}/health")
            assert health.status == 200
            assert await health.json() == {"status": "ok"}

            meta = await client.get(f"{API_PREFIX}/meta")
            body = await meta.json()
            assert meta.status == 200
            assert body["api_version"] == 1
            assert "capabilities" in body

    asyncio.run(scenario())


def test_the_device_token_reaches_every_read_route(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        # The camera and the WebSocket are not plain JSON reads: one is a stream that is
        # honestly 503 without a producer, the other is an upgrade.
        skipped = ("/command", "/stop", "/mode", "/pair", "/events", "/camera/stream")
        # `/logs` is honestly 503 when no log file exists, which is the case in a test process.
        skipped += ("/camera/snapshot", "/logs")
        async with TestClient(TestServer(create_app(plane))) as client:
            for method, path, _scope, _handler in ROUTES:
                if method != "GET" or path in skipped:
                    continue
                response = await client.get(f"{API_PREFIX}{path}", headers=headers)
                assert response.status == 200, f"GET {path} answered {response.status}"

    asyncio.run(scenario())


def test_the_camera_says_why_there_is_no_picture(tmp_path) -> None:
    """A shipped install has vision off; the route must say so, not hang and not 500."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        token = plane.tokens.ensure()
        async with TestClient(TestServer(create_app(plane))) as client:
            for path in ("/camera/snapshot", "/camera/stream"):
                headers = {"Authorization": f"Bearer {token}"}
                response = await client.get(f"{API_PREFIX}{path}", headers=headers)
                assert response.status == 503, path
                assert (await response.json())["error"] == "unavailable"

            # A frame in the context is enough to serve one: the producer is a vision module.
            plane.context.set("vision_frame", b"\xff\xd8jpegdata")
            snapshot = await client.get(
                f"{API_PREFIX}/camera/snapshot",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert snapshot.status == 200
            assert await snapshot.read() == b"\xff\xd8jpegdata"

            # The query-string token path exists because `<img>` cannot send a header.
            via_query = await client.get(f"{API_PREFIX}/camera/snapshot?token={token}")
            assert via_query.status == 200

    asyncio.run(scenario())


def test_a_paired_client_is_forbidden_from_admin_and_allowed_to_read(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        client_token, principal = plane.authorizer.issue_client_token("Pixel 8")
        assert set(principal.scopes) == set(PAIRING_SCOPES)
        headers = {"Authorization": f"Bearer {client_token}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            allowed = await client.get(f"{API_PREFIX}/state", headers=headers)
            assert allowed.status == 200

            for path in ("/logs", "/support-bundle"):
                refused = await client.get(f"{API_PREFIX}{path}", headers=headers)
                assert refused.status == 403, path
                assert (await refused.json())["error"] == "forbidden"

    asyncio.run(scenario())


def test_the_config_route_redacts_secrets(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        plane.context.set(
            "settings",
            {
                "wifi": {"ssid": "home", "password": "hunter2"},
                "telemetry_dashboard": {"http": {"auth_token": "abc123", "port": 8092}},
            },
        )
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/config", headers=headers)
            body = await response.json()

        assert response.status == 200
        assert body["config"]["wifi"]["password"] == "***"
        assert body["config"]["telemetry_dashboard"]["http"]["auth_token"] == "***"
        assert body["config"]["wifi"]["ssid"] == "home"

    asyncio.run(scenario())


def test_a_live_config_write_rejects_keys_that_are_not_live(tmp_path) -> None:
    """A write that silently does nothing is how a documented setting becomes dead config."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        plane.context.set("settings", {"led": {"brightness": 0.7}})
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            ok = await client.patch(
                f"{API_PREFIX}/config", headers=headers, json={"led.brightness": 0.4}
            )
            assert ok.status == 200
            assert plane.context.get("settings")["led"]["brightness"] == 0.4

            refused = await client.patch(
                f"{API_PREFIX}/config", headers=headers, json={"logging.level": "DEBUG"}
            )
            assert refused.status == 400
            body = await refused.json()
            assert body["rejected"] == ["logging.level"]
            assert "live_keys" in body

    asyncio.run(scenario())


def test_pairing_end_to_end(tmp_path) -> None:
    """A code from `pair/open` buys exactly one token, with the documented scopes."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            opened = await client.post(f"{API_PREFIX}/pair/open", headers=headers)
            code = (await opened.json())["code"]

            paired = await client.post(
                f"{API_PREFIX}/pair", json={"code": code, "client_name": "Pixel 8"}
            )
            body = await paired.json()

            replay = await client.post(
                f"{API_PREFIX}/pair", json={"code": code, "client_name": "again"}
            )

            state = await client.get(
                f"{API_PREFIX}/state",
                headers={"Authorization": f"Bearer {body['device_token']}"},
            )

        assert opened.status == 200
        assert len(code) == 6 and code.isdigit()
        assert paired.status == 200
        assert set(body["scopes"]) == set(PAIRING_SCOPES)
        assert replay.status == 401, "a pairing code must not be reusable"
        assert state.status == 200, "the token the pairing returned has to work"

    asyncio.run(scenario())


def test_opening_a_pairing_window_needs_admin(tmp_path) -> None:
    """A paired phone cannot mint more tokens for other phones."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        client_token, _principal = plane.authorizer.issue_client_token("Pixel 8")
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/pair/open",
                headers={"Authorization": f"Bearer {client_token}"},
            )

        assert response.status == 403

    asyncio.run(scenario())


def test_an_unknown_path_is_a_404(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/nope")
            assert response.status == 404

    asyncio.run(scenario())


def test_logs_tails_the_configured_file(tmp_path) -> None:
    """Reading the tail must work without loading the whole file, and must honour `?tail=`."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        log_path = tmp_path / "houndmind.log"
        log_path.write_text("\n".join(f"line {index}" for index in range(50)) + "\n", "utf-8")
        plane.context.set(
            "settings",
            {"logging": {"enable_file": True, "log_file_name": str(log_path)}},
        )
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/logs?tail=2", headers=headers)
            body = await response.json()

            missing = tmp_path / "absent.log"
            plane.context.set(
                "settings",
                {"logging": {"enable_file": True, "log_file_name": str(missing)}},
            )
            absent = await client.get(f"{API_PREFIX}/logs", headers=headers)
            absent_body = await absent.json()

        assert response.status == 200
        assert body["lines"] == ["line 48", "line 49"]
        assert absent.status == 503
        assert absent_body["error"] == "unavailable"

    asyncio.run(scenario())