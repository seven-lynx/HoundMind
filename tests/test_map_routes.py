"""The home map on the wire: `GET /map` publishes a document, `PUT /map` takes one back (M1).

Why these exist: the map was a picture and the file behind it was a log. A console can now edit the
document, so the two things that must hold are the ones a happy-path test would miss - a save writes
the shape the *next start* reads (`grid.cells`, not the flat `cells` a client received), and an edit
never erases the sample log or a `rev` a client is editing against.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.mapping.home_map import CURRENT_VERSION, load_home_map, write_document
from houndmind_ai.services import api as api_module
from houndmind_ai.services.api import API_PREFIX, ControlPlane, create_app
from houndmind_ai.services.settings import ApiSettings


class DummyContext:
    """The smallest context the route reads: settings, plus whatever a test publishes."""

    def __init__(self, settings: dict | None = None) -> None:
        self.data: dict = {
            "settings": settings or {},
            "module_statuses": {},
            "trace_id": "trace-map",
        }

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


def make_plane(
    tmp_path, document: dict | None = None, odometry: dict | None = None
) -> tuple[ControlPlane, dict[str, str], Path]:
    """A plane whose map file is under `tmp_path`, and the device token's headers."""
    map_file = tmp_path / "home_map.json"
    settings = {"mapping": {"home_map_path": str(map_file), "cell_size_cm": 10.0}}
    if odometry:
        settings["odometry"] = odometry
    plane = ControlPlane(
        DummyContext(settings),
        ApiSettings(host="127.0.0.1", port=0, token_path=str(tmp_path / "api_token")),
        CommandBus(),
    )
    if document is not None:
        plane.context.set("home_map", document)
    return plane, {"Authorization": f"Bearer {plane.tokens.ensure()}"}, map_file


def wire_document(**overrides) -> dict:
    """The shape `GET /map` publishes: `cells` flat, `samples` a count."""
    document = {
        "version": CURRENT_VERSION,
        "meta": {"rev": 0, "cell_size_cm": 10.0},
        "cells": {"1,2": 3},
        "sweep": {"0": 120.0},
        "samples": 0,
    }
    document.update(overrides)
    return document


def test_get_map_publishes_the_document_beside_the_cells(tmp_path) -> None:
    """Additive, not a replacement: `map` keeps the capped cell list it always served."""
    document = wire_document()

    async def scenario() -> dict:
        plane, headers, _path = make_plane(tmp_path, document=document)
        plane.context.set("mapping_state", {"grid": {"cells": {"1,2": 3}}})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/map", headers=headers)
            body = await response.json()
        assert response.status == 200
        return body

    body = asyncio.run(scenario())
    assert body["map"]["cells"] == [[1, 2, 3]]
    assert body["document"] == document


def test_put_map_writes_a_file_the_next_start_can_load(tmp_path) -> None:
    """The trap this closes: the client shape is not the file shape, and a save must not mix them."""
    document = wire_document(rooms=[{"id": "r1", "name": "kitchen"}])

    async def scenario() -> tuple[int, dict, Path]:
        plane, headers, path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
            body = await response.json()
        return response.status, body, path

    status, body, path = asyncio.run(scenario())

    assert status == 200
    assert body["rev"] == 1
    assert body["document"]["meta"]["rev"] == 1

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["grid"]["cells"] == {"1,2": 3}
    assert "cells" not in raw, "the file keeps `grid.cells`; a flat save loads back as an empty map"
    assert raw["rooms"] == [{"id": "r1", "name": "kitchen"}]
    assert raw["meta"]["source"] == "user"

    loaded = load_home_map(path)
    assert loaded.map is not None
    assert loaded.map.cells == {"1,2": 3}
    assert loaded.map.sections["rooms"] == [{"id": "r1", "name": "kitchen"}]


def test_a_saved_document_is_what_the_next_get_serves(tmp_path) -> None:
    """One answer: the document published after a save is the one a restart would read."""
    document = wire_document(rooms=[{"id": "r1", "name": "kitchen"}])

    async def scenario() -> dict:
        plane, headers, _path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            await client.put(f"{API_PREFIX}/map", headers=headers, json={"document": document})
            response = await client.get(f"{API_PREFIX}/map", headers=headers)
            body = await response.json()
        return body["document"]

    served = asyncio.run(scenario())
    assert served["meta"]["rev"] == 1
    assert served["rooms"] == [{"id": "r1", "name": "kitchen"}]
    assert served["cells"] == {"1,2": 3}


def test_an_exported_document_imports_back_and_the_sample_log_stays(tmp_path) -> None:
    """Export is `GET /map.document`; import is that body through `PUT /map` (M8).

    The panel's **Export JSON** writes what `GET /map` served and **Import…** sends it back, so the
    two failures worth pinning are the ones a happy path misses. A copy was taken at some generation,
    and its `meta.rev` is rebased before the save or the import is a `409`. And on the wire `samples`
    is a *count*: read as a log, it would delete every sample the mapper wrote.
    """
    path = tmp_path / "home_map.json"
    write_document(
        path,
        {
            "version": CURRENT_VERSION,
            "meta": {"rev": 4, "cell_size_cm": 10.0},
            "grid": {"cells": {"0,0": 2}},
            "sweep": {"0": 120.0},
            "samples": [{"timestamp": 1.0}, {"timestamp": 2.0}],
        },
    )

    async def scenario() -> tuple[dict, int, dict, Path]:
        plane, headers, _path = make_plane(tmp_path)
        plane.context.set(
            "home_map",
            wire_document(meta={"rev": 4, "cell_size_cm": 10.0}, cells={"0,0": 2}, samples=2),
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            served = await client.get(f"{API_PREFIX}/map", headers=headers)
            exported = (await served.json())["document"]
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": exported}
            )
            body = await response.json()
        return exported, response.status, body, path

    exported, status, body, path = asyncio.run(scenario())

    assert exported["samples"] == 2, "the wire carries the count, never the device's log"
    assert status == 200, body
    assert body["document"]["meta"]["rev"] == 5

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["meta"]["rev"] == 5 and raw["meta"]["source"] == "user"
    assert raw["grid"]["cells"] == {"0,0": 2}
    assert raw["samples"] == [{"timestamp": 1.0}, {"timestamp": 2.0}], (
        "the imported copy sent a count; the file's sample log is the mapper's and stays"
    )


def test_a_stale_rev_is_a_conflict_and_writes_nothing(tmp_path) -> None:
    """Two consoles editing one map: the second learns the generation, it does not overwrite it."""
    first = wire_document(rooms=[{"id": "r1", "name": "kitchen"}])
    stale = wire_document(rooms=[{"id": "r2", "name": "bogus"}])

    async def scenario() -> tuple[int, int, dict, Path]:
        plane, headers, path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            await client.put(f"{API_PREFIX}/map", headers=headers, json={"document": first})
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": stale}
            )
            body = await response.json()
        return response.status, int(body["rev"]), body, path

    status, current_rev, body, path = asyncio.run(scenario())

    assert (status, current_rev) == (409, 1), body
    assert body["error"] == "conflict"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["rooms"] == [{"id": "r1", "name": "kitchen"}], "the refused edit was not written"
    assert raw["meta"]["rev"] == 1


def test_the_rev_and_the_sample_log_come_from_the_file_when_nothing_was_loaded(tmp_path) -> None:
    """`home_map_load_path` ships empty: a `rev` read from the context alone would forget the file."""
    path = tmp_path / "home_map.json"
    write_document(
        path,
        {
            "version": CURRENT_VERSION,
            "meta": {"rev": 7},
            "grid": {"cells": {"0,0": 1}},
            "sweep": {},
            "samples": [{"timestamp": 1.0}, {"timestamp": 2.0}],
        },
    )

    async def scenario() -> tuple[int, int, int, int]:
        plane, headers, _path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            refused = await client.put(
                f"{API_PREFIX}/map",
                headers=headers,
                json={"document": wire_document(meta={"rev": 0}, cells={"0,0": 1})},
            )
            refused_body = await refused.json()
            accepted = await client.put(
                f"{API_PREFIX}/map",
                headers=headers,
                json={
                    "document": wire_document(meta={"rev": 7}, cells={"0,0": 1}, samples=2)
                },
            )
            accepted_body = await accepted.json()
        return (
            refused.status,
            int(refused_body["rev"]),
            accepted.status,
            int(accepted_body["rev"]),
        )

    assert asyncio.run(scenario()) == (409, 7, 200, 8)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["samples"] == [{"timestamp": 1.0}, {"timestamp": 2.0}], (
        "the client sent a count; the file's sample log is the mapper's and stays"
    )


def test_a_document_this_runtime_could_not_load_is_refused(tmp_path) -> None:
    """One validator: a body the next start would refuse is a `400` now, with the reason."""
    document = wire_document(version=CURRENT_VERSION + 1)

    async def scenario() -> tuple[int, dict]:
        plane, headers, _path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())
    assert status == 400
    assert any("reads up to" in problem for problem in body["problems"])


def test_a_section_of_the_wrong_type_is_refused_rather_than_dropped(tmp_path) -> None:
    """Dropping a room a human drew is the failure the validity rules exist to prevent."""
    document = wire_document(rooms="kitchen")

    async def scenario() -> tuple[int, dict, Path]:
        plane, headers, path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
            return response.status, await response.json(), path

    status, body, path = asyncio.run(scenario())
    assert status == 400
    assert "rooms must be a list of objects" in body["problems"]
    assert not path.exists(), "a refused document writes nothing"


def test_objects_round_trip_and_a_save_stamps_the_version(tmp_path) -> None:
    """Objects are user data on a v2 file, and the save writes the version this runtime writes (H3).

    The version field is the *writer's* claim, so a v2 document carrying furniture is written as v3
    rather than left labelled with a shape it no longer has — an older reader refuses a newer file by
    name, which is the only thing that stops it dropping a section it does not know.
    """
    document = wire_document(
        version=2,
        walls=[{"id": "wall_kitchen", "a": [0, 0], "b": [200, 0], "source": "user"}],
        objects=[
            {
                "id": "obj_sink",
                "wall_id": "wall_kitchen",
                "start_cm": 20,
                "width_cm": 60,
                "depth_cm": 50,
                "kind": "counter",
                "source": "user",
            }
        ],
    )

    async def scenario() -> tuple[int, dict, dict, Path]:
        plane, headers, path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            saved = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
            saved_body = await saved.json()
            response = await client.get(f"{API_PREFIX}/map", headers=headers)
            served = await response.json()
        return saved.status, saved_body, served["document"], path

    status, saved_body, served, path = asyncio.run(scenario())

    assert status == 200
    assert saved_body["document"]["version"] == CURRENT_VERSION
    assert served["objects"] == document["objects"]
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == CURRENT_VERSION
    assert raw["objects"] == document["objects"]
    assert raw["joints"] == [], "the second v3 section is written empty, never left out"


def test_put_map_needs_a_document_object(tmp_path) -> None:
    async def scenario() -> tuple[int, dict]:
        plane, headers, _path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(f"{API_PREFIX}/map", headers=headers, json={})
            return response.status, await response.json()

    status, body = asyncio.run(scenario())
    assert status == 400
    assert "document" in body["detail"]


def test_writing_the_map_needs_the_config_scope(tmp_path) -> None:
    """`state:read` reads the map; only `config` writes it, so a read-only client stays read-only."""
    document = wire_document()

    async def scenario() -> tuple[int, int]:
        plane, _device_headers, _path = make_plane(tmp_path)
        token, _principal = plane.authorizer.issue_client_token("Pen", scopes=["state:read"])
        headers = {"Authorization": f"Bearer {token}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            read = await client.get(f"{API_PREFIX}/map", headers=headers)
            write = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
        return read.status, write.status

    assert asyncio.run(scenario()) == (200, 403)


def test_cors_advertises_the_put_method_the_route_needs() -> None:
    """`PUT /map` is the table's first `PUT`, and a preflight that omits it refuses the save."""
    assert "PUT" in api_module._CORS_ALLOW_METHODS


def test_put_map_keeps_a_room_and_the_surface_painted_over_it(tmp_path) -> None:
    """The console's own sections survive a save verbatim: a room that loses `keep_out` is a floor the dog walks on."""
    rooms = [
        {
            "id": "room_1",
            "name": "kitchen",
            "colour": "rgba(120, 170, 220, 0.30)",
            "keep_out": True,
            "polygon": [[0, 0], [200, 0], [200, 150], [0, 150]],
        }
    ]
    surfaces = [
        {
            "id": "surf_1",
            "name": "hardwood",
            "step_scale": "hardwood",
            "polygon": [[0, 0], [200, 0], [200, 150], [0, 150]],
        }
    ]
    document = wire_document(meta={"rev": 0, "cell_size_cm": 10.0}, rooms=rooms, surfaces=surfaces)

    async def scenario() -> tuple[int, dict, dict]:
        plane, headers, path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
            body = await response.json()
        return response.status, body, json.loads(path.read_text(encoding="utf-8"))

    status, body, written = asyncio.run(scenario())
    assert status == 200
    assert written["rooms"] == rooms
    assert written["surfaces"] == surfaces
    assert body["document"]["rooms"] == rooms


def test_put_map_marks_an_unmeasured_room_scale(tmp_path) -> None:
    """A room drawn without width x depth saves normally, and the document admits it (H2).

    The requirement is the save, not the refusal: a console that refused an unmeasured room would
    make H4's discovery run impossible to start from a fresh map.
    """
    rooms = [
        {
            "id": "room_1",
            "name": "kitchen",
            "keep_out": False,
            "polygon": [[0, 0], [200, 0], [200, 150], [0, 150]],
        }
    ]
    document = wire_document(rooms=rooms)

    async def scenario() -> tuple[int, dict, dict]:
        plane, headers, path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
            body = await response.json()
        return response.status, body, json.loads(path.read_text(encoding="utf-8"))

    status, body, written = asyncio.run(scenario())

    assert status == 200, body
    assert "size_cm" not in written["rooms"][0], "unmeasured is an absent key, not a zero"
    assert written["meta"]["scale_source"] == "unmeasured"
    assert body["document"]["meta"]["scale_source"] == "unmeasured"


def test_put_map_keeps_a_measured_room_and_marks_the_scale(tmp_path) -> None:
    """The two numbers a person typed round-trip verbatim, and the document claims a real size (H2)."""
    size_cm = {"width_cm": 320.0, "depth_cm": 240.0}
    rooms = [
        {
            "id": "room_1",
            "name": "kitchen",
            "size_cm": size_cm,
            "polygon": [[0, 0], [320, 0], [320, 240], [0, 240]],
        }
    ]
    document = wire_document(rooms=rooms)

    async def scenario() -> tuple[int, dict, dict]:
        plane, headers, path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
            body = await response.json()
        return response.status, body, json.loads(path.read_text(encoding="utf-8"))

    status, body, written = asyncio.run(scenario())

    assert status == 200, body
    assert written["rooms"][0]["size_cm"] == size_cm
    assert written["meta"]["scale_source"] == "user"


def test_a_v2_map_without_a_scale_still_loads(tmp_path) -> None:
    """A file written before H2 carries neither field, and reading it is not a problem (H2)."""
    path = tmp_path / "home_map.json"
    write_document(
        path,
        {
            "version": 2,
            "meta": {"rev": 2, "cell_size_cm": 10.0},
            "grid": {"cells": {"0,0": 1}},
            "sweep": {"0": 120.0},
            "rooms": [{"id": "r1", "name": "hall", "polygon": [[0, 0], [100, 0], [100, 100]]}],
        },
    )

    loaded = load_home_map(path)

    assert loaded.map is not None, loaded.problems
    assert not loaded.problems
    assert loaded.map.sections["rooms"] == [
        {"id": "r1", "name": "hall", "polygon": [[0, 0], [100, 0], [100, 100]]}
    ]
    assert "scale_source" not in loaded.map.meta


def test_put_map_keeps_a_pin_the_console_taught(tmp_path) -> None:
    """A pin is a `places[]` entry in the existing document, so a save must carry it like a room (M7).

    The place itself lives in the catalogue (`~/.houndmind/places.json`); this is where it is drawn,
    and a save that dropped it would leave a taught spot with no mark on the map.
    """
    pins = [
        {
            "id": "kitchen",
            "name": "Kitchen",
            "x_cm": 0.0,
            "y_cm": 300.0,
            "heading_deg": 0.0,
            "uncertainty_cm": None,
        }
    ]
    document = wire_document(meta={"rev": 0, "cell_size_cm": 10.0}, places=pins)

    async def scenario() -> tuple[int, dict, dict]:
        plane, headers, path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map", headers=headers, json={"document": document}
            )
            body = await response.json()
        return response.status, body, json.loads(path.read_text(encoding="utf-8"))

    status, body, written = asyncio.run(scenario())

    assert status == 200
    assert written["places"] == pins
    assert body["document"]["places"] == pins


def test_get_map_publishes_the_measured_step_per_surface(tmp_path) -> None:
    """A vocabulary without values is a menu that lies: the panel cannot read the config, so it rides here."""
    odometry = {"surface_step_cm": {"hardwood": 18.4, "carpet": 0, "tile": "nonsense", "rug": -3}}

    async def scenario() -> dict:
        plane, headers, _path = make_plane(tmp_path, odometry=odometry)
        plane.context.set("mapping_state", {"grid": {"cells": {"1,2": 3}}})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/map", headers=headers)
            return await response.json()

    body = asyncio.run(scenario())
    # A zero, a negative and a string are all "not measured", never a number a panel would draw.
    assert body["surface_step_cm"] == {"hardwood": 18.4}


def test_get_map_publishes_an_empty_measurement_before_calibration(tmp_path) -> None:
    """`{}` and not a default: an assumed step drawn as measured is a false observation."""

    async def scenario() -> dict:
        plane, headers, _path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/map", headers=headers)
            return await response.json()

    body = asyncio.run(scenario())
    # The empty-grid return carries the key too: a client must not have to guess which branch it got.
    assert body["map"] is None
    assert body["surface_step_cm"] == {}


# ---- M5: position and go ----------------------------------------------------


def test_put_map_pose_re_anchors_in_the_runtime_frame(tmp_path) -> None:
    """The console sends document points; `pose_reset` is `(forward, left)`. Exactly one swap."""

    async def scenario() -> tuple[int, dict, dict | None]:
        plane, headers, _path = make_plane(tmp_path, document=wire_document())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map/pose",
                headers=headers,
                json={"x_cm": 30.0, "y_cm": 100.0, "heading_deg": 90.0},
            )
            body = await response.json()
        return response.status, body, plane.context.get("pose_reset")

    status, body, reset = asyncio.run(scenario())
    assert status == 200
    assert body["dog"]["x_cm"] == 30.0 and body["dog"]["y_cm"] == 100.0
    assert reset is not None
    # left 30 / forward 100 in the document is forward 100 / left 30 for odometry (#347).
    assert reset["x_cm"] == 100.0 and reset["y_cm"] == 30.0
    assert reset["source"] == "user"
    assert isinstance(reset["frame_ts"], float)


def test_put_map_pose_writes_the_dog_into_the_file(tmp_path) -> None:
    """It has to survive a restart: the position is the one fact a restart cannot recompute."""

    async def scenario() -> tuple[int, dict, Path]:
        plane, headers, path = make_plane(tmp_path, document=wire_document(meta={"rev": 4}))
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map/pose", headers=headers, json={"x_cm": 12.5, "y_cm": -7.5}
            )
            return response.status, await response.json(), path

    status, body, path = asyncio.run(scenario())
    assert status == 200
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["dog"]["x_cm"] == 12.5 and raw["dog"]["y_cm"] == -7.5
    assert raw["meta"]["rev"] == 5, "the file changed, so the generation moved with it"
    assert body["rev"] == 5


def test_put_map_pose_needs_two_numbers(tmp_path) -> None:
    """`"left"` is not a coordinate, and a guessed one moves the origin without anyone noticing."""

    async def scenario() -> int:
        plane, headers, _path = make_plane(tmp_path, document=wire_document())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.put(
                f"{API_PREFIX}/map/pose", headers=headers, json={"x_cm": "left", "y_cm": 5}
            )
            return response.status

    assert asyncio.run(scenario()) == 400


def test_get_map_publishes_the_pose_in_the_document_frame(tmp_path) -> None:
    """A runtime pose drawn against the document mirrors the dog; the route does the swap once."""

    async def scenario() -> dict:
        plane, headers, _path = make_plane(tmp_path)
        plane.context.set(
            "localization",
            {"tier": "user", "pose": {"x": 100.0, "y": 30.0, "yaw_deg": 90.0}, "confidence": 0.8},
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/map", headers=headers)
            return await response.json()

    body = asyncio.run(scenario())
    assert body["pose"]["x_cm"] == 30.0 and body["pose"]["y_cm"] == 100.0
    assert body["pose"]["heading_deg"] == 90.0, "yaw is already 0 = forward, positive = left"
    assert body["pose"]["tier"] == "user"


def test_map_go_refuses_without_a_pose_and_says_why(tmp_path) -> None:
    """`202` followed by a refusal in `/state` reads as "accepted": say it now instead."""

    async def scenario() -> tuple[int, dict, object]:
        plane, headers, _path = make_plane(tmp_path)
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/go", headers=headers, json={"x_cm": 10, "y_cm": 20}
            )
            return response.status, await response.json(), plane.context.get("route_request")

    status, body, request = asyncio.run(scenario())
    assert status == 409
    assert body["error"] == "no_pose" and body["tier"] is None
    assert request is None, "a refused goal must not be queued for the follower"


def test_map_go_hands_the_goal_to_the_follower_in_the_runtime_frame(tmp_path) -> None:
    """One write: `route_follower` plans and walks it, which is the hand-off that already exists."""

    async def scenario() -> tuple[int, object]:
        plane, headers, _path = make_plane(tmp_path)
        plane.context.set(
            "localization", {"tier": "dead_reckoning", "pose": {"x": 0.0, "y": 0.0}}
        )
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/go", headers=headers, json={"x_cm": 30.0, "y_cm": 100.0}
            )
            return response.status, plane.context.get("route_request")

    status, request = asyncio.run(scenario())
    assert status == 202
    assert request == {"goal_cm": {"x_cm": 100.0, "y_cm": 30.0}}


def test_map_go_does_not_queue_behind_a_walk_in_flight(tmp_path) -> None:
    """One destination at a time, or the brake and the throttle stop being one control."""

    async def scenario() -> int:
        plane, headers, _path = make_plane(tmp_path)
        plane.context.set("localization", {"tier": "user", "pose": {"x": 0.0, "y": 0.0}})
        plane.context.set("route", {"state": "walking", "index": 0, "total": 3})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/go", headers=headers, json={"x_cm": 10, "y_cm": 10}
            )
            return response.status

    assert asyncio.run(scenario()) == 409


def test_position_and_go_both_need_the_move_scope(tmp_path) -> None:
    """`config` edits the map; only `move` may re-anchor the pose or send the dog somewhere."""

    async def scenario() -> tuple[int, int]:
        plane, _device, _path = make_plane(tmp_path, document=wire_document())
        token, _principal = plane.authorizer.issue_client_token("Pen", scopes=["config"])
        headers = {"Authorization": f"Bearer {token}"}
        async with TestClient(TestServer(create_app(plane))) as client:
            pose = await client.put(
                f"{API_PREFIX}/map/pose", headers=headers, json={"x_cm": 1, "y_cm": 2}
            )
            go = await client.post(
                f"{API_PREFIX}/map/go", headers=headers, json={"x_cm": 1, "y_cm": 2}
            )
        return pose.status, go.status

    assert asyncio.run(scenario()) == (403, 403)


# ---- M6: preview, trail, health ---------------------------------------------

BAND = [[-50, 80], [50, 80], [50, 120], [-50, 120]]


def _keep_out_document(*rooms: dict) -> dict:
    return wire_document(rooms=list(rooms))


def _pose(x: float = 0.0, y: float = 0.0) -> dict:
    return {"tier": "dead_reckoning", "pose": {"x": x, "y": y, "yaw_deg": 0.0}}


def test_preview_refuses_without_a_pose(tmp_path) -> None:
    """A route in map coordinates means nothing to a dog that cannot place itself on the map."""

    async def scenario() -> tuple[int, dict]:
        plane, headers, _path = make_plane(tmp_path, document=wire_document())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/preview", headers=headers, json={"x_cm": 10, "y_cm": 20}
            )
            return response.status, await response.json()

    status, body = asyncio.run(scenario())
    assert status == 409 and body["error"] == "no_pose"


def test_preview_plans_and_answers_in_the_document_frame(tmp_path) -> None:
    """`state:read` plans a route it may not walk, and the waypoints come back in the document frame."""

    async def scenario() -> tuple[int, dict]:
        plane, headers, _path = make_plane(tmp_path, document=wire_document())
        plane.context.set("localization", _pose())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/preview", headers=headers, json={"x_cm": 30.0, "y_cm": 100.0}
            )
            assert response.status == 200
            return response.status, await response.json()

    _status, body = asyncio.run(scenario())
    assert body["valid"] is True and body["refusal"] is None
    assert body["distance_cm"] > 0
    assert body["waypoints"], "a plan over an empty grid is still a straight line"
    # The goal echoed back is the document point that was sent, not the runtime swap.
    assert body["goal_cm"] == {"x_cm": 30.0, "y_cm": 100.0}
    for waypoint in body["waypoints"]:
        assert "x_cm" in waypoint and "y_cm" in waypoint


def test_preview_refuses_a_goal_inside_a_keep_out_room(tmp_path) -> None:
    """#353: a keep-out room the user drew now refuses something, and names itself."""

    async def scenario() -> dict:
        document = _keep_out_document(
            {"id": "stairs", "name": "stairs", "keep_out": True, "polygon": BAND}
        )
        plane, headers, _path = make_plane(tmp_path, document=document)
        plane.context.set("localization", _pose())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/preview", headers=headers, json={"x_cm": 0.0, "y_cm": 100.0}
            )
            assert response.status == 200, "a refusal about a hypothetical is not a bad request"
            return await response.json()

    body = asyncio.run(scenario())
    assert body["valid"] is False
    assert body["refusal"] == "goal_in_keep_out"
    assert body["keep_out"]["label"] == "stairs"
    assert body["waypoints"] == []


def test_preview_refuses_a_walk_that_crosses_a_keep_out_room(tmp_path) -> None:
    """Neither end is in the room; the straight run between them is. That is the case to catch."""

    async def scenario() -> dict:
        document = _keep_out_document(
            {"id": "stairs", "name": "stairs", "keep_out": True, "polygon": BAND}
        )
        plane, headers, _path = make_plane(tmp_path, document=document)
        plane.context.set("localization", _pose())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/preview", headers=headers, json={"x_cm": 0.0, "y_cm": 200.0}
            )
            return await response.json()

    body = asyncio.run(scenario())
    assert body["valid"] is False and body["refusal"] == "route_in_keep_out"
    assert body["keep_out"]["label"] == "stairs"


def test_preview_does_not_trap_a_dog_already_inside_a_keep_out_room(tmp_path) -> None:
    """A room is marked to keep the dog out, not to imprison it: the walk back out is allowed."""

    async def scenario() -> dict:
        document = _keep_out_document(
            {"id": "stairs", "name": "stairs", "keep_out": True, "polygon": BAND}
        )
        plane, headers, _path = make_plane(tmp_path, document=document)
        plane.context.set("localization", _pose(100.0, 0.0))
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/preview", headers=headers, json={"x_cm": 0.0, "y_cm": 300.0}
            )
            return await response.json()

    body = asyncio.run(scenario())
    assert body["valid"] is True
    assert "already inside" in (body["note"] or "")


def test_preview_needs_two_numbers(tmp_path) -> None:
    async def scenario() -> int:
        plane, headers, _path = make_plane(tmp_path)
        plane.context.set("localization", _pose())
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.post(
                f"{API_PREFIX}/map/preview", headers=headers, json={"x_cm": None, "y_cm": 2}
            )
            return response.status

    assert asyncio.run(scenario()) == 400


def test_get_map_publishes_the_trail_and_the_health(tmp_path) -> None:
    """Both ride beside the document: what the dog walked, and what the map can say about itself."""

    async def scenario() -> dict:
        plane, headers, _path = make_plane(
            tmp_path, document=wire_document(meta={"rev": 3, "updated_at": 500.0})
        )
        plane.context.set("mapping_state", {"grid": {"cells": {"1,2": 3}}})
        plane.context.set("pose_trail", [{"x_cm": 100.0, "y_cm": 30.0, "ts": 1.0}])
        plane.context.set(
            "home_map_status",
            {"loaded": True, "notes": ["kept the strongest cells"], "loaded_at": 400.0},
        )
        plane.context.set("odometry", {"step_cm": 18.4, "step_cm_source": "measured:hardwood"})
        async with TestClient(TestServer(create_app(plane))) as client:
            response = await client.get(f"{API_PREFIX}/map", headers=headers)
            return await response.json()

    body = asyncio.run(scenario())
    assert body["trail"] == [[30.0, 100.0]], "runtime (forward, left) swapped once, on the device"
    health = body["health"]
    assert health["loaded"] is True
    assert health["loaded_at"] == 400.0
    assert health["updated_at"] == 500.0
    assert health["rev"] == 3.0
    assert health["step_cm"] == 18.4
    assert health["step_cm_source"] == "measured:hardwood"
    assert health["conflicts"] == [] and health["notes"] == ["kept the strongest cells"]
    assert health["cells"] == 1




