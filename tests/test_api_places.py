"""The place routes: the catalogue, creating one, forgetting one, and asking for a walk.

`tests/test_api_routes.py` already proves every route here is declared in the contract, carries a
scope and refuses an anonymous caller. This file covers the answers themselves — 201 for a created
place, the `problems[]` a refused body comes back with, 404 for a handle that is not there, and 409
for a second walk while the first is still in flight.

The store is a real `PlaceStore` over real files, published the way the navigator publishes it, so
these routes are exercised against the shape they will meet on the dog rather than a stub that could
drift from it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.kernel.place_store import PlaceStore
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
from houndmind_ai.services.settings import ApiSettings


class DummyContext:
    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {"settings": settings or {}}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def __contains__(self, key) -> bool:
        return key in self.data


def place_model(**overrides) -> dict:
    """One place in the stored shape. `id` is the slug of the name, filled in by the loader."""
    body = {"name": "Kitchen", "heading_deg": 0.0, "distance_cm": 100.0}
    body.update(overrides)
    return body


def plane_for(tmp_path: Path, *places: dict, with_navigator: bool = True) -> ControlPlane:
    """A control plane whose context carries a store over a real file, as the navigator publishes it."""
    path = tmp_path / "places.json"
    if places:
        path.write_text(json.dumps({"version": 1, "places": list(places)}), encoding="utf-8")
    context = DummyContext(load_config().settings)
    if with_navigator:
        context.set("place_store", PlaceStore(str(path)))
    api_settings = ApiSettings(
        host="127.0.0.1",
        port=0,
        token_path=str(tmp_path / "api_token"),
        pairing_enabled=False,
    )
    return ControlPlane(context, api_settings, CommandBus())


def auth(plane: ControlPlane) -> dict[str, str]:
    return {"Authorization": f"Bearer {plane.tokens.ensure()}"}


def stored(tmp_path: Path) -> list[dict]:
    """The places file as it is on disk now, or an empty list when nothing has been written."""
    path = tmp_path / "places.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["places"]


def test_the_catalogue_is_what_the_file_holds(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model(), place_model(name="Hall", heading_deg=90.0))
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/places", headers=auth(plane))
            body = await response.json()
            assert response.status == 200
            assert [place["id"] for place in body["places"]] == ["kitchen", "hall"]
            assert body["path"].endswith("places.json")
            assert body["refusals"] == []
            assert body["goal"] is None

    asyncio.run(scenario())


def test_an_entry_the_file_refused_is_reported_not_hidden(tmp_path) -> None:
    """The store keeps what it understood and names the rest; the route must not swallow that."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model(), {"name": "Nowhere", "heading_deg": 999.0})
        async with TestClient(TestServer(create_app(plane))) as client:
            body = await (await client.get(f"{API_PREFIX}/places", headers=auth(plane))).json()
            assert [place["id"] for place in body["places"]] == ["kitchen"]
            assert body["refusals"], "a refused entry has to be visible to the user"

    asyncio.run(scenario())


def test_no_place_navigator_is_a_503_with_a_reason(tmp_path) -> None:
    """An empty catalogue and a service that is not running are different answers."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, with_navigator=False)
        async with TestClient(TestServer(create_app(plane))) as client:
            for method, path in (("get", "/places"), ("post", "/places"), ("delete", "/places/x")):
                call = getattr(client, method)
                response = await call(f"{API_PREFIX}{path}", headers=auth(plane))
                assert response.status == 503, path
                assert (await response.json())["error"] == "unavailable"

    asyncio.run(scenario())


def test_a_created_place_is_written_and_returned(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places",
                headers=auth(plane),
                json={"name": "Living Room", "heading_deg": 45.0, "distance_cm": 180.0},
            )
            body = await response.json()
            assert response.status == 201
            assert body["place"]["id"] == "living_room"
            assert body["place"]["heading_deg"] == 45.0

        assert [place["id"] for place in stored(tmp_path)] == ["living_room"]

    asyncio.run(scenario())


def test_a_duplicate_name_is_refused_with_the_stores_own_problem(tmp_path) -> None:
    """The duplicate rule lives in `check_places_document`, not in a second copy inside the route."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places",
                headers=auth(plane),
                json={"name": "kitchen", "heading_deg": 0.0, "distance_cm": 50.0},
            )
            body = await response.json()
            assert response.status == 400
            assert body["problems"], "a refusal has to say why"
            assert all("message" in problem for problem in body["problems"])

        assert len(stored(tmp_path)) == 1, "a refused place must not be written"

    asyncio.run(scenario())


def test_a_json_boolean_is_not_a_number_and_a_string_is_not_coerced(tmp_path) -> None:
    """`true` is an `int` in Python, and `"90"` would silently become 90.0 on its way to a servo."""

    async def scenario() -> None:
        plane = plane_for(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            for body in (
                {"name": "Hall", "heading_deg": True, "distance_cm": 100.0},
                {"name": "Hall", "heading_deg": "90", "distance_cm": 100.0},
                {"name": "Hall", "heading_deg": 0.0, "distance_cm": False},
            ):
                response = await client.post(
                    f"{API_PREFIX}/places", headers=auth(plane), json=body
                )
                assert response.status == 400, body
                assert (await response.json())["error"] == "bad_request"

        assert stored(tmp_path) == []

    asyncio.run(scenario())


def test_a_name_with_no_usable_characters_is_refused(tmp_path) -> None:
    """`slug("///")` is `""`, so a place nobody could ever address is refused, not written."""

    async def scenario() -> None:
        plane = plane_for(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places",
                headers=auth(plane),
                json={"name": "///", "heading_deg": 0.0, "distance_cm": 100.0},
            )
            assert response.status == 400
            assert (await response.json())["problems"]

        assert stored(tmp_path) == []

    asyncio.run(scenario())


def test_forgetting_a_place_removes_it_and_a_second_call_is_a_404(tmp_path) -> None:
    """P4 PL6's exit criterion starts here: a second `DELETE` is visibly a no-op."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model(), place_model(name="Hall"))
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.delete(f"{API_PREFIX}/places/kitchen", headers=auth(plane))
            body = await response.json()
            assert response.status == 200
            assert body["removed"]["id"] == "kitchen"

            again = await client.delete(f"{API_PREFIX}/places/kitchen", headers=auth(plane))
            assert again.status == 404
            assert (await again.json())["error"] == "not_found"

            # A near-miss is answered with the handle it probably meant, like `/routines/{id}/run`.
            typo = await client.delete(f"{API_PREFIX}/places/hal", headers=auth(plane))
            assert typo.status == 404
            assert (await typo.json())["suggestion"] == "hall"

        assert [place["id"] for place in stored(tmp_path)] == ["hall"]

    asyncio.run(scenario())


def test_a_place_can_be_forgotten_by_name(tmp_path) -> None:
    """A name is accepted where an id is expected, because the user is right about the place."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.delete(f"{API_PREFIX}/places/Kitchen", headers=auth(plane))
            assert response.status == 200
            assert (await response.json())["removed"]["id"] == "kitchen"

        assert stored(tmp_path) == []

    asyncio.run(scenario())


def test_go_writes_the_request_the_navigator_reads(tmp_path) -> None:
    """The route asks; the navigator walks. `place_request` is the one channel between them."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/kitchen/go",
                headers=auth(plane),
                json={"at_anchor": True},
            )
            body = await response.json()
            assert response.status == 202
            assert body["accepted"] is True
            assert body["at_anchor"] is True

        assert plane.context.get("place_request") == {"id": "kitchen", "at_anchor": True}

    asyncio.run(scenario())


def test_a_second_walk_is_a_conflict_while_one_is_in_flight(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model(), place_model(name="Hall"))
        async with TestClient(TestServer(create_app(plane))) as client:
            # A queued request blocks a second one before the navigator has even seen it.
            first = await client.post(
                f"{API_PREFIX}/places/kitchen/go", headers=auth(plane), json={"at_anchor": True}
            )
            assert first.status == 202
            second = await client.post(
                f"{API_PREFIX}/places/hall/go", headers=auth(plane), json={"at_anchor": True}
            )
            assert second.status == 409
            assert (await second.json())["error"] == "conflict"

            # And a goal already travelling blocks one too, reporting what is under way.
            plane.context.set("place_request", None)
            plane.context.set("place_goal", {"id": "kitchen", "state": "travelling"})
            third = await client.post(
                f"{API_PREFIX}/places/hall/go", headers=auth(plane), json={"at_anchor": True}
            )
            assert third.status == 409
            assert (await third.json())["current"]["id"] == "kitchen"

    asyncio.run(scenario())


def test_go_refuses_a_truthy_string_for_the_anchor_confirmation(tmp_path) -> None:
    """`"false"` is truthy, and this flag decides whether the dog walks across the room."""

    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/kitchen/go",
                headers=auth(plane),
                json={"at_anchor": "false"},
            )
            assert response.status == 400
            assert (await response.json())["error"] == "bad_request"

        assert plane.context.get("place_request") is None

    asyncio.run(scenario())


def test_go_to_an_unknown_place_is_a_404_with_a_suggestion(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/kitch/go", headers=auth(plane), json={"at_anchor": True}
            )
            body = await response.json()
            assert response.status == 404
            assert body["suggestion"] == "kitchen"

        assert plane.context.get("place_request") is None

    asyncio.run(scenario())


