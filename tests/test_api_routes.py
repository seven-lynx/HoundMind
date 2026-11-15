"""The route table against the contract, and the auth gate across every route.

`docs/CONTROL_API.md` is the source of truth for both clients. The first test is the one that
keeps that true: a route added in code without a contract row (or a contract row with no route)
fails here, which is cheaper than finding out from an Android app that silently stops working.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import zipfile
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.calibration.workflow import CalibrationModule
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import LEG_SERVO_NAMES
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.services import api as api_module
from houndmind_ai.services.api import (
    ANY_SCOPE,
    API_PREFIX,
    HANDLER_SCOPE,
    ROUTES,
    ControlPlane,
    create_app,
)
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
    """`None` has exactly one meaning: the route is public on purpose (#39).

    The camera rows used to declare `None` while their handlers enforced `state:read`, so the
    table read "video is unauthenticated" and `None` meant two things at once. They now declare
    `HANDLER_SCOPE`; this test fails if any route goes back to being ambiguous.
    """
    public = PUBLIC | {"/events"}
    for method, path, scope, _handler in ROUTES:
        if path in public:
            assert scope is None, f"{method} {path} is public but declares {scope!r}"
            continue
        assert scope is not None, f"{method} {path} has no scope and is not public"

    camera = {path: scope for _m, path, scope, _h in ROUTES if path.startswith("/camera/")}
    assert camera["/camera/stream"] == HANDLER_SCOPE
    assert camera["/camera/snapshot"] == HANDLER_SCOPE

    whoami = {path: scope for _m, path, scope, _h in ROUTES if path == "/whoami"}
    assert whoami == {"/whoami": ANY_SCOPE}, (
        "the route that reports scopes must not require one: a `move`-only token is the caller "
        "that needs the answer (#168)"
    )


def test_whoami_answers_any_token_with_its_own_scopes(tmp_path) -> None:
    """#168: a client learns what its token cannot do before a request fails, not after.

    The token here holds `move` only, so `/state` refuses it - which is exactly why `/whoami` has to
    answer it. The payload mirrors the WebSocket `welcome` frame (`device`/`scopes`), so a panel parses
    one shape whether identity arrived over HTTP or the socket.
    """
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        token, _principal = plane.authorizer.issue_client_token("Pen", scopes=["move"])
        headers = {"Authorization": f"Bearer {token}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            anonymous = await client.get(f"{API_PREFIX}/whoami")
            assert anonymous.status == 401
            assert (await anonymous.json())["error"] == "unauthorized"

            identity = await client.get(f"{API_PREFIX}/whoami", headers=headers)
            body = await identity.json()

            assert identity.status == 200
            assert body == {"device": "Pen", "scopes": ["move"], "kind": "client"}
            assert identity.headers["Cache-Control"] == "no-store"

            # The same token is refused the read route: the answer has to exist for this caller.
            refused = await client.get(f"{API_PREFIX}/state", headers=headers)
            assert refused.status == 403

    asyncio.run(scenario())


def test_a_camera_handler_that_stops_asking_itself_is_caught(tmp_path, monkeypatch) -> None:
    """The camera scope is enforced in the handler, so removing the guard must not be silent.

    `_camera_principal` is the only place either camera route learns it needs `state:read`.
    Planted here, a refusal proves the handler consults it: with the call deleted the route
    would reach the camera service and answer 200 (a frame is in the context) instead.
    """

    def refuse(_plane, _request):
        raise api_module.AuthError("unauthorized", "planted refusal")

    async def scenario() -> list[tuple[int, str]]:
        monkeypatch.setattr(api_module, "_camera_principal", refuse)
        plane = make_plane(tmp_path)
        plane.context.set("vision_frame_jpeg", b"\xff\xd8jpegdata")
        async with TestClient(TestServer(create_app(plane))) as client:
            answers: list[tuple[int, str]] = []
            for path in ("/camera/snapshot", "/camera/stream"):
                response = await client.get(f"{API_PREFIX}{path}")
                answers.append((response.status, (await response.json())["detail"]))
            return answers

    assert asyncio.run(scenario()) == [(401, "planted refusal"), (401, "planted refusal")]


def test_an_anonymous_request_is_refused_everywhere_but_liveness(tmp_path) -> None:
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            for method, path, _scope, _handler in ROUTES:
                if path in PUBLIC or path == "/events":
                    continue
                # A route template is not a URL: `{id}` has to be filled in before it can be
                # called, and aiohttp's dynamic segment does not match a literal `{id}`.
                target = re.sub(r"\{[^}]+\}", "x", path)
                response = await client.request(method, f"{API_PREFIX}{target}")
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
        # `/decisions` is honestly 503 when nothing is publishing the ring (no runtime here).
        skipped += ("/decisions",)
        # `/routines` is honestly 503 when no routine runner is loaded (no runtime here either).
        skipped += ("/routines",)
        # `/places` is honestly 503 when no place navigator has published its store (same reason).
        skipped += ("/places",)
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
            # The producer publishes encoded bytes under its own key, because the raw array
            # `vision_frame` is what the detection modules read.
            plane.context.set("vision_frame_jpeg", b"\xff\xd8jpegdata")
            snapshot = await client.get(
                f"{API_PREFIX}/camera/snapshot",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert snapshot.status == 200
            assert await snapshot.read() == b"\xff\xd8jpegdata"

            # The query-string path exists because `<img>` cannot send a header — and it takes a
            # ticket now, not the device token (`#18`).
            minted = await client.post(
                f"{API_PREFIX}/camera/ticket", headers={"Authorization": f"Bearer {token}"}
            )
            assert minted.status == 200
            ticket = (await minted.json())["ticket"]
            via_ticket = await client.get(f"{API_PREFIX}/camera/snapshot?ticket={ticket}")
            assert via_ticket.status == 200
            assert await via_ticket.read() == b"\xff\xd8jpegdata"

            # The credential that drives the dog is refused in a URL, and says what to use instead.
            via_query = await client.get(f"{API_PREFIX}/camera/snapshot?token={token}")
            assert via_query.status == 401
            assert "camera/ticket" in (await via_query.json())["detail"]

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
                "api": {"port": 8420, "token_path": "~/.houndmind/api_token"},
            },
        )
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/config", headers=headers)
            body = await response.json()

        assert response.status == 200
        assert body["config"]["wifi"]["password"] == "***"
        assert body["config"]["api"]["token_path"] == "***"
        assert body["config"]["wifi"]["ssid"] == "home"
        assert body["config"]["api"]["port"] == 8420

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


def test_a_live_config_write_must_match_the_schema(tmp_path) -> None:
    """A string in a numeric key answered 200 and then failed its module on every tick (#123)."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        plane.context.set("settings", {"led": {"brightness": 0.7}})
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.patch(
                f"{API_PREFIX}/config", headers=headers, json={"led.brightness": "high"}
            )
            body = await response.json()

        assert response.status == 400, body
        assert body["invalid"][0]["key"] == "led.brightness"
        assert body["invalid"][0]["problems"][0]["path"] == "config.settings.led.brightness"
        assert plane.context.get("settings")["led"]["brightness"] == 0.7

    asyncio.run(scenario())


def test_a_live_config_write_says_it_is_not_persisted(tmp_path) -> None:
    """The change lives in this process only: a restart reloads `config/settings.jsonc` (#128)."""
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        plane.context.set("settings", {"led": {"brightness": 0.7}})
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.patch(
                f"{API_PREFIX}/config", headers=headers, json={"led.brightness": 0.4}
            )
            body = await response.json()

        assert response.status == 200, body
        assert body["persisted"] is False
        assert plane.context.get("settings")["led"]["brightness"] == 0.4

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


def test_the_support_bundle_carries_state_and_no_secret(tmp_path) -> None:
    """The bundle is the maintainer's whole view of the device; it must not carry credentials.

    This used to be covered through the telemetry dashboard, which bundled via
    `tools.collect_support_bundle`. The dashboard is gone with the rest of the legacy servers and
    the route now ships `ControlPlane.support_bundle`; the device-side collector is still in
    `src/tools/` and is what the bundle's README points at for file logs (#23).
    """
    async def scenario() -> None:
        plane = make_plane(tmp_path)
        plane.context.set(
            "settings", {"api": {"port": 8420, "token_path": "~/.houndmind/api_token"}}
        )
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/support-bundle", headers=headers)
            body = await response.read()

        assert response.status == 200
        assert response.content_type == "application/zip"

        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = set(archive.namelist())
            config = json.loads(archive.read("config.json"))
            modules = json.loads(archive.read("modules.json"))
            readme = archive.read("README.txt").decode("utf-8")

        assert {"meta.json", "state.json", "modules.json", "config.json"} <= names
        assert config["api"]["token_path"] == "***"
        assert "modules" in modules
        # The README ships inside the zip a user attaches to a bug report, so it must name a
        # command that exists: it used to promise `houndmind doctor`, which never did (#23).
        assert "houndmind doctor" not in readme
        assert "tools.collect_support_bundle" in readme
        assert "/api/v1/logs" in readme

    asyncio.run(scenario())


def test_the_calibration_run_route_is_read_only(tmp_path) -> None:
    """The route #17 reserved never became a servo sweep: it reads, and proves it (#17).

    `FakeDogHAL` records every `apply_offsets` call, so "the trim was read and not written" is an
    assertion rather than a comment.
    """

    async def scenario() -> None:
        plane = make_plane(tmp_path)
        hal = FakeDogHAL()
        hal.set_offsets({name: 1.0 for name in LEG_SERVO_NAMES})
        plane.context.set("hal", hal)
        plane.context.set(
            "settings",
            {"calibration": {"persist_path": str(tmp_path / "calibration.json")}},
        )
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        module = CalibrationModule("calibration")

        async def tick_once() -> None:
            # The runtime ticks the module on its own thread; the test stands in for one tick.
            await asyncio.sleep(0.02)
            module.tick(plane.context)

        async with TestClient(TestServer(create_app(plane))) as client:
            ticker = asyncio.create_task(tick_once())
            response = await client.post(
                f"{API_PREFIX}/calibration/run",
                json={"request": "servo_zero"},
                headers=headers,
            )
            await ticker
            body = await response.json()

        assert response.status == 202
        assert body["request"] == "servo_zero"
        assert body["result"]["status"] == "ok"
        assert body["result"]["servo_zero_offsets"] == hal.read_offsets()
        assert hal.offsets_applied == [], "the run route must never write an offset"

    asyncio.run(scenario())


def test_the_calibration_run_route_refuses_anything_that_is_not_a_read(tmp_path) -> None:
    """The allow-list is the safety property: an unknown name is refused before anything runs."""

    async def scenario() -> None:
        plane = make_plane(tmp_path)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/calibration/run",
                json={"request": "sweep_every_servo"},
                headers=headers,
            )
            body = await response.json()

        assert response.status == 400
        assert body["error"] == "unknown_request"
        assert "servo_zero" in body["requests"]
        assert "sweep_every_servo" not in body["requests"]
        assert plane.context.get("calibration_request") is None, "nothing was asked to run"
        assert plane.context.get("calibration_result") is None

    asyncio.run(scenario())


def test_a_calibration_run_with_no_ticking_runtime_is_a_503(tmp_path, monkeypatch) -> None:
    # The real wait is one second; the assertion is about the answer, not about how long it takes.
    monkeypatch.setattr(api_module, "_CALIBRATION_ACK_TIMEOUT_S", 0.05)

    async def scenario() -> None:
        plane = make_plane(tmp_path)
        plane.context.set("calibration_result", None)
        headers = {"Authorization": f"Bearer {plane.tokens.ensure()}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/calibration/run",
                json={"request": "servo_zero"},
                headers=headers,
            )
            body = await response.json()

        assert response.status == 503
        assert body["error"] == "unavailable"
        assert body["request_id"]

    asyncio.run(scenario())


def test_the_web_app_serves_versioned_assets_and_revalidates(tmp_path, monkeypatch) -> None:
    """An upgrade has to reach a browser that has been here before (#102).

    The version is stamped into the asset URL as `GET /` is served, so the copy a browser kept is a
    different URL after an upgrade; `no-cache` is the belt that makes even an unversioned request ask
    the server. `_asset_version` is patched because a working tree has no installed distribution
    metadata — the fallback the helper documents, and the reason a test may not read it live.

    The **document** revalidates too, and that half was missing long enough to bite: an old
    `index.html` kept by heuristic freshness ran a new `app.js` against ids it no longer had, and
    every button on the connect screen silently stopped working.
    """

    async def scenario() -> tuple[int, str, int, str, str]:
        plane = make_plane(tmp_path)
        monkeypatch.setattr(api_module, "_asset_version", lambda: "9.9.9")
        async with TestClient(TestServer(create_app(plane))) as client:
            index = await client.get("/")
            html = await index.text()
            script = await client.get("/static/app.js")
            cache = script.headers.get("Cache-Control", "")
            document_cache = index.headers.get("Cache-Control", "")
            return index.status, html, script.status, cache, document_cache

    status, html, script_status, cache, document_cache = asyncio.run(scenario())

    assert status == 200
    assert "/static/app.js?v=9.9.9" in html, "the script URL must carry the version"
    assert "/static/style.css?v=9.9.9" in html, "the stylesheet URL must carry the version"
    assert script_status == 200
    assert "no-cache" in cache, f"assets must revalidate, got Cache-Control={cache!r}"
    assert "no-cache" in document_cache, (
        f"the document must revalidate too, else a stale index.html runs new JavaScript,"
        f" got Cache-Control={document_cache!r}"
    )