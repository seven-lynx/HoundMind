"""The routine routes: what loaded, what was refused, and what a start does.

`tests/test_api_routes.py` already proves that every route here is declared in the contract, carries
a scope and refuses an anonymous caller. This file covers the answers themselves — 200 with the
runner's own report, 202 for a start, and the four refusals a client has to be able to show a human.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.behavior.routine_runner import RoutineRun
from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.kernel.routine_store import RoutineStore
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
from houndmind_ai.services.settings import ApiSettings


class DummyContext:
    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {"settings": settings or {}, "module_statuses": {}}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def __contains__(self, key):
        return key in self.data


def plane_for(
    tmp_path: Path,
    routines: dict[str, list[dict]] | None = None,
    broken: bool = False,
) -> ControlPlane:
    """A control plane whose context carries a real `StoreReport`.

    The report comes from the real store over real files, so the routes are exercised against the
    shape the runner publishes rather than a hand-written dict that could drift from it.
    """
    directory = tmp_path / "routines"
    directory.mkdir(exist_ok=True)
    for routine_id, steps in (routines or {}).items():
        (directory / f"{routine_id}.json").write_text(
            json.dumps({"id": routine_id, "steps": steps}), encoding="utf-8"
        )
    if broken:
        (directory / "broken.json").write_text("{", encoding="utf-8")

    settings = load_config().settings
    context = DummyContext(settings)
    context.set("routine_report", RoutineStore(directory).load(repertoire_from_settings(settings)))
    api_settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        pairing_enabled=False,
    )
    return ControlPlane(context, api_settings, CommandBus())


def auth(plane: ControlPlane) -> dict[str, str]:
    return {"Authorization": f"Bearer {plane.tokens.ensure()}"}


CALM = [{"action": "sit"}, {"action": "wag_tail"}]


def test_the_list_answers_with_what_the_runner_loaded(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM}, broken=True)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/routines", headers=auth(plane))
            body = await response.json()

        assert response.status == 200
        assert body["directory"].endswith("routines")
        assert [routine["id"] for routine in body["routines"]] == ["calm"]
        assert body["routines"][0]["steps"][0] == {"action": "sit", "params": {}}
        # A refused file is listed with its reason, not hidden: the user has to fix that file.
        assert list(body["refusals"]) == ["broken.json"]
        assert body["refusals"]["broken.json"][0]["path"] == "routine"
        assert body["current"] is None

    asyncio.run(scenario())


def test_the_list_reports_the_run_in_progress(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        plane.context.set(
            "routine_run",
            RoutineRun(routine_id="calm", name="calm", total=2, index=1, action="wag_tail"),
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            body = await (await client.get(f"{API_PREFIX}/routines", headers=auth(plane))).json()

        assert body["current"]["id"] == "calm"
        assert body["current"]["state"] == "running"
        assert body["current"]["index"] == 1

    asyncio.run(scenario())


def test_without_a_runner_both_routes_say_so(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        plane.context.set("routine_report", None)
        async with TestClient(TestServer(create_app(plane))) as client:
            listed = await client.get(f"{API_PREFIX}/routines", headers=auth(plane))
            listed_body = await listed.json()
            started = await client.post(
                f"{API_PREFIX}/routines/calm/run", headers=auth(plane), json={}
            )
            started_body = await started.json()

        assert listed.status == 503
        assert started.status == 503
        assert listed_body["error"] == "unavailable"
        assert started_body["error"] == "unavailable"
        # Nothing was queued: a request no runner will read is not an accepted request.
        assert plane.context.get("routine_request") is None

    asyncio.run(scenario())


# --------------------------------------------------------------- starting a run


def test_a_run_is_accepted_and_queued_for_the_runner(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/routines/calm/run", headers=auth(plane), json={}
            )
            body = await response.json()

        assert response.status == 202
        assert body == {"accepted": True, "id": "calm", "dry_run": False, "steps": 2}
        assert plane.context.get("routine_request") == {"id": "calm", "dry_run": False}

    asyncio.run(scenario())


def test_a_dry_run_is_carried_to_the_runner(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/routines/calm/run", headers=auth(plane), json={"dry_run": True}
            )
            body = await response.json()

        assert response.status == 202
        assert body["dry_run"] is True
        assert plane.context.get("routine_request") == {"id": "calm", "dry_run": True}

    asyncio.run(scenario())


def test_an_absent_body_means_not_dry(tmp_path) -> None:
    """`POST /routines/{id}/run` has no required field, so a client may send nothing at all."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(f"{API_PREFIX}/routines/calm/run", headers=auth(plane))

        assert response.status == 202
        assert plane.context.get("routine_request") == {"id": "calm", "dry_run": False}

    asyncio.run(scenario())


def test_a_string_dry_run_is_refused_rather_than_coerced(tmp_path) -> None:
    """`"true"` is truthy: coercing it would start a real run for a client asking for a rehearsal."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/routines/calm/run", headers=auth(plane), json={"dry_run": "true"}
            )
            body = await response.json()

        assert response.status == 400
        assert body["error"] == "bad_request"
        assert plane.context.get("routine_request") is None

    asyncio.run(scenario())


def test_an_unknown_id_is_a_404_with_a_suggestion(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/routines/clam/run", headers=auth(plane), json={}
            )
            body = await response.json()

        assert response.status == 404
        assert body["error"] == "not_found"
        assert body["suggestion"] == "calm"

    asyncio.run(scenario())


def test_a_second_run_while_one_is_running_is_a_conflict(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        plane.context.set(
            "routine_run", RoutineRun(routine_id="calm", name="calm", total=2, index=0)
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/routines/calm/run", headers=auth(plane), json={}
            )
            body = await response.json()

        assert response.status == 409
        assert body["error"] == "conflict"
        assert body["current"]["id"] == "calm"
        assert plane.context.get("routine_request") is None

    asyncio.run(scenario())


def test_a_request_already_queued_blocks_the_next_one(tmp_path) -> None:
    """Between the 202 and the next tick the run does not exist yet, so the queue is the lock."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM, "other": CALM})
        plane.context.set("routine_request", {"id": "calm", "dry_run": False})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/routines/other/run", headers=auth(plane), json={}
            )
            body = await response.json()

        assert response.status == 409
        assert "queued" in body["detail"]
        assert plane.context.get("routine_request") == {"id": "calm", "dry_run": False}

    asyncio.run(scenario())


def test_a_read_only_token_may_list_but_may_not_start(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        token, _principal = plane.authorizer.issue_client_token("reader", scopes=["state:read"])
        headers = {"Authorization": f"Bearer {token}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            listed = await client.get(f"{API_PREFIX}/routines", headers=headers)
            started = await client.post(
                f"{API_PREFIX}/routines/calm/run", headers=headers, json={}
            )
            body = await started.json()

        assert listed.status == 200
        assert started.status == 403
        assert body["error"] == "forbidden"
        assert plane.context.get("routine_request") is None

    asyncio.run(scenario())


# ------------------------------------------------------------ the escape hatch


def test_a_stop_ends_the_running_routine(tmp_path) -> None:
    """A routine would publish its next step on the following tick; a stop has to reach it."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        plane.context.set(
            "routine_run", RoutineRun(routine_id="calm", name="calm", total=2, index=1)
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(f"{API_PREFIX}/stop", headers=auth(plane))

        assert response.status == 202
        assert plane.context.get("routine_stop") is True

    asyncio.run(scenario())


def test_a_stop_without_a_runner_leaves_no_flag_behind(tmp_path) -> None:
    """A flag nobody consumes would outlive the stop and end the *next* run instead."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, {"calm": CALM})
        plane.context.set("routine_report", None)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(f"{API_PREFIX}/stop", headers=auth(plane))

        assert response.status == 202
        assert plane.context.get("routine_stop") is None

    asyncio.run(scenario())
