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

import pytest
from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.kernel.place_store import PlaceStore
from houndmind_ai.perception.place_views import (
    DESCRIPTOR_BYTES,
    MIN_DESCRIPTORS,
    THUMB_H,
    THUMB_W,
    PlaceView,
    load_views,
    save_views,
)
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


def plane_for(
    tmp_path: Path, *places: dict, with_navigator: bool = True, views_dir: Path | None = None
) -> ControlPlane:
    """A control plane whose context carries a store over a real file, as the navigator publishes it.

    `views_dir` defaults inside `tmp_path` on purpose: `GET /places` and `POST /places/teach` read and
    write that directory, and a test that used the shipped default would be reading (and writing) the
    developer's own `~/.houndmind`.
    """
    path = tmp_path / "places.json"
    if places:
        path.write_text(json.dumps({"version": 1, "places": list(places)}), encoding="utf-8")
    base = load_config().settings
    settings = dict(base)
    recognition = dict(base.get("place_recognition") or {})
    recognition["views_dir"] = str(tmp_path / "views" if views_dir is None else views_dir)
    settings["place_recognition"] = recognition
    context = DummyContext(settings)
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



def test_a_place_can_be_renamed_and_keeps_its_id(tmp_path) -> None:
    """#173: a typo in a name used to mean forget and retype, which loses the visit count."""
    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.patch(
                f"{API_PREFIX}/places/kitchen", headers=auth(plane), json={"name": "Galley"}
            )
            body = await response.json()
            catalogue = await (await client.get(f"{API_PREFIX}/places", headers=auth(plane))).json()

        assert response.status == 200
        assert body["place"]["id"] == "kitchen", "the id is the handle goals use"
        assert body["place"]["name"] == "Galley"
        assert body["path"].endswith("places.json")
        assert [(place["id"], place["name"]) for place in catalogue["places"]] == [
            ("kitchen", "Galley")
        ]
        # On disk, not just in the answer.
        assert stored(tmp_path)[0]["name"] == "Galley"

    asyncio.run(scenario())


def test_a_patch_refuses_a_new_id_and_an_empty_body(tmp_path) -> None:
    """Silently ignoring `id` would look like a successful rename of the handle."""
    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model())
        async with TestClient(TestServer(create_app(plane))) as client:
            new_id = await client.patch(
                f"{API_PREFIX}/places/kitchen", headers=auth(plane), json={"id": "galley"}
            )
            empty = await client.patch(
                f"{API_PREFIX}/places/kitchen", headers=auth(plane), json={}
            )
            new_id_body = await new_id.json()
            empty_body = await empty.json()

        assert new_id.status == 400
        assert "id cannot be changed" in new_id_body["detail"]
        assert empty.status == 400
        assert "at least one of" in empty_body["detail"]
        assert stored(tmp_path)[0]["name"] == "Kitchen", "neither request may have written"

    asyncio.run(scenario())


def test_a_patch_for_an_unknown_place_is_a_404_with_a_suggestion(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.patch(
                f"{API_PREFIX}/places/kitch", headers=auth(plane), json={"name": "Galley"}
            )
            body = await response.json()

        assert response.status == 404
        assert body["error"] == "not_found"
        assert body["suggestion"] == "kitchen"

    asyncio.run(scenario())


def test_a_rename_onto_an_existing_name_comes_back_as_problems(tmp_path) -> None:
    """The same refusal a second `POST` would produce, so a client renders it the same way."""
    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model(), place_model(name="Hall", heading_deg=90.0))
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.patch(
                f"{API_PREFIX}/places/kitchen", headers=auth(plane), json={"name": "Hall"}
            )
            body = await response.json()

        assert response.status == 400
        assert body["error"] == "bad_request"
        assert body["problems"], "a refusal a client can show a user, not a bare message"
        assert [place["name"] for place in stored(tmp_path)] == ["Kitchen", "Hall"]

    asyncio.run(scenario())


def test_a_patch_without_the_navigator_is_a_503(tmp_path) -> None:
    async def scenario() -> None:
        plane = plane_for(tmp_path, place_model(), with_navigator=False)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.patch(
                f"{API_PREFIX}/places/kitchen", headers=auth(plane), json={"name": "Galley"}
            )
            body = await response.json()

        assert response.status == 503
        assert body["error"] == "unavailable"

    asyncio.run(scenario())


# ---- M7: photo pins and teach-a-place ---------------------------------------


def _picture(place_id: str) -> PlaceView:
    """A view with synthetic descriptors, the way `test_place_recognition.py` stands in for ORB.

    OpenCV is not installed in every development venv, and the ORB path itself is covered by
    `tests/test_place_views.py` under `importorskip`. What these tests are about is the wiring: which
    frame was read, where the view was filed, and what reached the places file.
    """
    return PlaceView(
        place_id=place_id,
        created_at=1.0,
        thumb=bytes(THUMB_W * THUMB_H),
        keypoints=tuple((0.0, float(index)) for index in range(MIN_DESCRIPTORS)),
        descriptors=tuple(bytes([index]) * DESCRIPTOR_BYTES for index in range(MIN_DESCRIPTORS)),
    )


def _standing_at(plane: ControlPlane, forward_cm: float = 100.0, heading: float = 0.0) -> None:
    """Publish a live pose the way `localization` does: runtime frame, `(x = forward, y = left)`."""
    plane.context.set(
        "localization",
        {"tier": "dead_reckoning", "pose": {"x": forward_cm, "y": 0.0, "yaw_deg": heading}},
    )


def _stub_picture(monkeypatch) -> None:
    """Make the extractor answer with a view for whichever place id it is asked about."""
    monkeypatch.setattr(
        "houndmind_ai.services.api.view_from_frame",
        lambda _frame, place_id: _picture(place_id),
    )


def test_teach_writes_the_place_and_files_its_picture(tmp_path, monkeypatch) -> None:
    """One act: the place in the catalogue, and the view `place_recognition` will match (M7)."""
    _stub_picture(monkeypatch)

    async def scenario() -> tuple[int, dict]:
        plane = plane_for(tmp_path)
        plane.context.set("vision_frame", b"frame")
        _standing_at(plane)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/teach",
                headers=auth(plane),
                json={"name": "Kitchen", "x_cm": 0.0, "y_cm": 300.0},
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 201
    place = body["place"]
    assert place["id"] == "kitchen"
    assert place["has_view"] is True
    assert place["thumb"], "the panel draws the picture from the answer"
    # The pin is a document point; the place is the vector from the dog, in the runtime frame.
    assert place["distance_cm"] == pytest.approx(200.0)
    assert place["heading_deg"] == pytest.approx(0.0)
    (view,) = load_views(Path(body["view_path"]).parent)
    assert view.place_id == "kitchen"
    assert stored(tmp_path)[0]["has_view"] is True


def test_forgetting_a_place_drops_its_view_too(tmp_path) -> None:
    """The catalogue and the views file are one fact: a view left behind keeps naming the place (#356)."""
    views_dir = tmp_path / "views"
    save_views(views_dir, (_picture("kitchen"), _picture("hall")))

    async def scenario() -> int:
        plane = plane_for(tmp_path, place_model(), place_model(name="Hall"))
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.delete(f"{API_PREFIX}/places/kitchen", headers=auth(plane))
            return response.status

    assert asyncio.run(scenario()) == 200
    # The other place keeps its picture: forgetting one place is not forgetting the catalogue.
    assert [view.place_id for view in load_views(views_dir)] == ["hall"]


def test_teaching_where_the_dog_stands_is_a_place_at_zero_distance(tmp_path, monkeypatch) -> None:
    """The dog is here, call it the kitchen: no point in the body means the dog's own (M7)."""
    _stub_picture(monkeypatch)

    async def scenario() -> tuple[int, dict]:
        plane = plane_for(tmp_path)
        plane.context.set("vision_frame", b"frame")
        _standing_at(plane, forward_cm=250.0, heading=90.0)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/teach", headers=auth(plane), json={"name": "Kitchen"}
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 201
    assert body["place"]["distance_cm"] == 0.0
    # Arrival is decided before a turn is considered, so the heading of a place at zero distance is
    # the dog's own reading rather than an invented zero.
    assert body["place"]["heading_deg"] == pytest.approx(90.0)


def test_teach_without_a_camera_is_a_503_and_writes_nothing(tmp_path) -> None:
    async def scenario() -> tuple[int, dict]:
        plane = plane_for(tmp_path)
        _standing_at(plane)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/teach", headers=auth(plane), json={"name": "Kitchen"}
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 503
    assert body["error"] == "unavailable"
    assert "vision" in body["detail"]
    assert stored(tmp_path) == [], "no camera is not a reason to leave a place behind"


def test_teach_names_the_wheel_that_is_missing(tmp_path, monkeypatch) -> None:
    """A `lite` install has no OpenCV; that is a 503 naming the package, not a traceback."""

    def no_wheel(_frame, _place_id):
        raise ImportError("No module named 'cv2'", name="cv2")

    monkeypatch.setattr("houndmind_ai.services.api.view_from_frame", no_wheel)

    async def scenario() -> tuple[int, dict]:
        plane = plane_for(tmp_path)
        plane.context.set("vision_frame", b"frame")
        _standing_at(plane)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/teach", headers=auth(plane), json={"name": "Kitchen"}
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 503
    assert "cv2" in body["detail"]
    assert stored(tmp_path) == []


def test_a_featureless_frame_is_refused_before_anything_is_written(tmp_path, monkeypatch) -> None:
    """The refusal is `view_from_frame`'s own sentence, which says what to do about a blank wall."""

    def blank(_frame, _place_id):
        raise ValueError(
            "a view needs at least 8 descriptors and this frame gave 0: point the camera at "
            "something with texture"
        )

    monkeypatch.setattr("houndmind_ai.services.api.view_from_frame", blank)

    async def scenario() -> tuple[int, dict]:
        plane = plane_for(tmp_path)
        plane.context.set("vision_frame", b"blank")
        _standing_at(plane)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/teach", headers=auth(plane), json={"name": "Kitchen"}
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 400
    assert "texture" in body["detail"]
    assert stored(tmp_path) == []
    assert not (tmp_path / "views" / "views.json").exists()


def test_a_refused_name_files_no_picture(tmp_path, monkeypatch) -> None:
    """The store owns the catalogue rules, and a duplicate must not leave a view behind either."""
    _stub_picture(monkeypatch)

    async def scenario() -> tuple[int, dict]:
        plane = plane_for(tmp_path, place_model())
        plane.context.set("vision_frame", b"frame")
        _standing_at(plane)
        async with TestClient(TestServer(create_app(plane))) as client:
            # `Kitchen` is already in the file; the store refuses the second one by name.
            response = await client.post(
                f"{API_PREFIX}/places/teach", headers=auth(plane), json={"name": "Kitchen"}
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 400
    assert body["problems"], "a refusal a client can show a user"
    assert not (tmp_path / "views" / "views.json").exists()
    assert len(stored(tmp_path)) == 1
    assert not stored(tmp_path)[0].get("has_view"), "the file was not rewritten at all"


def test_teach_with_no_position_to_measure_from_is_a_409(tmp_path, monkeypatch) -> None:
    """A bearing from a dog that cannot place itself is a claim nothing measured."""
    _stub_picture(monkeypatch)

    async def scenario() -> tuple[int, dict]:
        plane = plane_for(tmp_path)
        plane.context.set("vision_frame", b"frame")
        # No `localization` and no `document.dog`: there is nothing to measure the pin from.
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/teach",
                headers=auth(plane),
                json={"name": "Kitchen", "x_cm": 10.0, "y_cm": 10.0},
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())

    assert status == 409
    assert body["error"] == "no_pose"
    assert stored(tmp_path) == []


def test_teach_needs_the_config_scope(tmp_path, monkeypatch) -> None:
    """A token that may read the catalogue must not be able to teach a place."""
    _stub_picture(monkeypatch)

    async def scenario() -> int:
        plane = plane_for(tmp_path)
        plane.context.set("vision_frame", b"frame")
        _standing_at(plane)
        token, _principal = plane.authorizer.issue_client_token("Phone", scopes=["state:read"])
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/places/teach",
                headers={"Authorization": f"Bearer {token}"},
                json={"name": "Kitchen"},
            )
        return response.status

    assert asyncio.run(scenario()) == 403


def test_the_catalogue_publishes_the_picture_beside_the_flag(tmp_path) -> None:
    """`has_view` is the places file's claim and `thumb` is the views file's evidence."""
    save_views(tmp_path / "views", (_picture("kitchen"),))

    async def scenario() -> dict:
        plane = plane_for(
            tmp_path,
            place_model(has_view=True),
            place_model(name="Hall", id="hall", has_view=True),
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/places", headers=auth(plane))
            return await response.json()

    body = asyncio.run(scenario())

    by_id = {place["id"]: place for place in body["places"]}
    assert by_id["kitchen"]["has_view"] is True
    assert by_id["kitchen"]["thumb"], "the picture is what the map panel draws"
    # A flag with no picture is published as exactly that, not quietly corrected in either direction.
    assert by_id["hall"]["has_view"] is True
    assert by_id["hall"]["thumb"] is None

