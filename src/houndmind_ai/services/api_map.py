"""The home-map surface, split out of `services/api.py` (AP5a).

Five routes and the helpers only they call: the capped occupancy grid plus the versioned home-map
document (`GET /map`, `PUT /map`), the dog's position on the map (`PUT /map/pose`), the click that
becomes a walk request (`POST /map/go`) and the read-only preview of that walk (`POST /map/preview`).
They move together because they share one frame — every point on the wire is in the **document's**
frame, and the swap to the runtime's frame happens here, once, at the boundary (#347).

**`_localization_of`, `_has_pose` and `_no_pose_response` live here, not in `services/http.py`.**
`services/api_people.py` imports them: a place needs the same pose check and the same `409 no_pose`
envelope a map goal does. They are context readers and one response shape, so the edge is
`api_people -> api_map -> http`, which is one direction and opens no cycle.

**`_number` comes from `services/http.py`.** It is the JSON-boundary coercion (a `bool` is an `int`,
so `true` would arrive as `1.0`), used by the map, the routines, the calibration routes and the
people surface alike, so it belongs beside the body parsers rather than in whichever surface happens
to hold it.
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from houndmind_ai.mapping.home_map import (
    CURRENT_VERSION,
    document_point_to_runtime,
    load_home_map,
    map_path,
    runtime_point_to_document,
    scale_source_for,
    validate_document,
    write_document,
)
from houndmind_ai.mapping.planner import plan_route
from houndmind_ai.mapping.rooms import (
    keep_out_room_at,
    polyline_in_keep_out,
    room_label,
)
from houndmind_ai.services.http import _json_body, _number, _plane

if TYPE_CHECKING:
    from houndmind_ai.services.api import ControlPlane

logger = logging.getLogger(__name__)
# One response has to be drawable on a phone, so the grid is capped. The cap keeps the cells with the
# most hits: a map that outgrew it is exactly the one where the strong returns are worth keeping.
_MAP_CELLS = 4000


def _map_document(context) -> dict[str, Any] | None:
    """The home-map document this runtime knows, or `None` when it has none (M1).

    The same key the mapper publishes on load (`mapping/mapper.py:75`), so `GET /map` and
    `PUT /map` never disagree about which map is current.
    """
    document = context.get("home_map")
    return document if isinstance(document, dict) else None


def _pose_in_document(context) -> dict[str, Any] | None:
    """The live pose, in the document's frame, swapped once here (M5).

    The console draws the document, so handing it a runtime point would mirror the dog - the defect
    `home_map.document_point_to_runtime` exists to prevent (#347). The swap belongs on this side
    because the panel keeps no second copy of it. `heading_deg` passes through unchanged: the
    runtime's yaw is already "0 is forward, positive is left", and the canvas maps forward to up and
    left to left, which is the same rotation.
    """
    localization = context.get("localization")
    if not isinstance(localization, dict):
        return None
    pose = localization.get("pose")
    if not isinstance(pose, dict):
        return None
    forward_cm = _number(pose.get("x"))
    left_cm = _number(pose.get("y"))
    if forward_cm is None or left_cm is None:
        return None
    doc_x, doc_y = runtime_point_to_document((forward_cm, left_cm))
    yaw = _number(pose.get("yaw_deg"))
    return {
        "x_cm": round(doc_x, 3),
        "y_cm": round(doc_y, 3),
        "heading_deg": round(yaw if yaw is not None else 0.0, 3),
        "tier": str(localization.get("tier") or ""),
        "confidence": _number(localization.get("confidence")),
    }


def _trail_in_document(context) -> list[list[float]]:
    """The walk so far, in the document frame, as `[[x, y], ...]` (M6).

    The same rule as the pose: the console draws the document, so the swap happens here once (#347).
    An entry the producer could not read is dropped rather than plotted at the origin - a breadcrumb is
    only worth drawing if every vertex on it is a place the dog actually was.
    """
    trail = context.get("pose_trail")
    if not isinstance(trail, list):
        return []
    points: list[list[float]] = []
    for entry in trail:
        if not isinstance(entry, dict):
            continue
        forward_cm = _number(entry.get("x_cm"))
        left_cm = _number(entry.get("y_cm"))
        if forward_cm is None or left_cm is None:
            continue
        doc_x, doc_y = runtime_point_to_document((forward_cm, left_cm))
        points.append([round(doc_x, 1), round(doc_y, 1)])
    return points


def _map_health(context) -> dict[str, Any]:
    """What the map can honestly say about itself (M6).

    `conflicts` is the loader's own list of what it could not take at face value - a room of the wrong
    type, a version newer than this runtime, a grid longer than the cap - and `notes` is what it
    accepted while saying something about it. They are kept apart because one means "this is not the
    map that was written" and the other means "this is, with a caveat".

    `step_cm_source` reads the odometry module first and the document second: the document's copy is
    only as fresh as the last save, so after a calibration the module knows a measured stride the file
    does not.
    """
    status = context.get("home_map_status")
    status = status if isinstance(status, dict) else {}
    odometry = context.get("odometry")
    odometry = odometry if isinstance(odometry, dict) else {}
    document = _map_document(context) or {}
    meta = document.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    cells = document.get("cells")
    step_cm = _number(odometry.get("step_cm"))
    if step_cm is None:
        step_cm = _number(meta.get("step_cm"))
    return {
        "loaded": bool(status.get("loaded")),
        "reason": status.get("reason"),
        "path": status.get("path"),
        "conflicts": [str(item) for item in status.get("problems") or ()],
        "notes": [str(item) for item in status.get("notes") or ()],
        "loaded_at": _number(status.get("loaded_at")),
        "updated_at": _number(meta.get("updated_at")),
        "rev": _number(meta.get("rev")),
        "cells": len(cells) if isinstance(cells, dict) else 0,
        "step_cm": step_cm,
        "step_cm_source": str(odometry.get("step_cm_source") or meta.get("step_cm_source") or "assumed"),
    }


def _file_document(plane: ControlPlane, path: Path) -> dict[str, Any] | None:
    """The document a write should extend: the file's, else the published one, in file shape.

    The file wins because it is what a restart reads - `home_map_load_path` ships empty, so a
    context-only copy is only whatever this process has seen. `None` means there is no map at all,
    and a correction with nowhere to live must not invent an empty document behind the mapper's
    back: the next scan save would then be writing over a map the user never made.
    """
    stored = load_home_map(path).map
    if stored is not None:
        return stored.to_file_document()
    published = _map_document(plane.context)
    if published is None:
        return None
    known = validate_document(published)
    return known.map.to_file_document() if known.map is not None else None


def _localization_of(context) -> tuple[dict[str, Any], str]:
    """The `localization` key and its tier, whatever shape the context happens to hold."""
    raw = context.get("localization")
    localization = raw if isinstance(raw, dict) else {}
    return localization, str(localization.get("tier") or "")


def _has_pose(localization: dict[str, Any]) -> bool:
    """A pose a route can start from: a tier that is not the floor, and a point behind it."""
    tier = str(localization.get("tier") or "")
    return tier not in ("", "reactive") and isinstance(localization.get("pose"), dict)


def _no_pose_response(tier: str) -> web.Response:
    """The `409` a route that needs a pose answers with: the tier, and what to do about it."""
    if tier == "reactive":
        detail = "localization is reactive: there is no pose to plan from"
    elif not tier:
        detail = "the dog cannot place itself on the map yet; correct its position first"
    else:
        detail = f"the dog reports {tier} but published no pose to plan from"
    return web.json_response(
        {"error": "no_pose", "tier": tier or None, "detail": detail}, status=409
    )


async def _map(request: web.Request) -> web.Response:
    """The occupancy grid the mapper built, bounded (#175), and the home-map document (M1).

    `mapping` has kept a hit histogram per cell since P3 (`mapping/mapper.py::_ingest_into_grid`) and
    nothing could see it. Cells are published as `[ix, iy, hits]` **in cells, not centimetres**:
    `cell_size_cm` rides along so a client scales them, and the integer pair is what the mapper
    stores, so nothing here re-derives a projection and disagrees with the producer.

    `truncated` and `count` say what was left out, because an empty corner of a truncated map means
    "not sent", not "not mapped" - and only one of those is worth walking into.

    `document` is the versioned home map, additively: `map` stays the capped cell list this route
    has always served, and `document` is what `PUT /map` takes back. It is `null` when no map was
    loaded and none was saved, which is a fact a client has to see rather than an empty map.
    """
    plane = _plane(request)
    state = plane.context.get("mapping_state")
    all_settings = plane.context.get("settings") or {}
    settings = all_settings.get("mapping", {}) if isinstance(all_settings, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    # The console names a surface; what that surface *measures* was decided by `tools.step_calibrate`
    # and lives in the config, which the panel cannot read. Publishing the table here is what lets the
    # map say "hardwood - 18.4 cm measured" instead of offering a vocabulary with no values behind it.
    odometry = all_settings.get("odometry") if isinstance(all_settings, dict) else None
    measured_raw = odometry.get("surface_step_cm") if isinstance(odometry, dict) else None
    surface_step_cm: dict[str, float] = {}
    if isinstance(measured_raw, dict):
        for name, value in measured_raw.items():
            number = _number(value)
            if number is not None and number > 0:
                surface_step_cm[str(name)] = number
    document = _map_document(plane.context)
    grid_enabled = bool(settings.get("grid_enabled", True))
    grid = state.get("grid") if isinstance(state, dict) else None
    cells = grid.get("cells") if isinstance(grid, dict) else None
    if not isinstance(cells, dict) or not cells:
        return web.json_response(
            {
                "map": None,
                "grid_enabled": grid_enabled,
                "document": document,
                "pose": _pose_in_document(plane.context),
                "trail": _trail_in_document(plane.context),
                "health": _map_health(plane.context),
                "surface_step_cm": surface_step_cm,
            },
            headers={"Cache-Control": "no-store"},
        )

    triples: list[list[int]] = []
    for key, hits in cells.items():
        try:
            ix_text, iy_text = str(key).split(",", 1)
            triples.append([int(ix_text), int(iy_text), int(hits)])
        except (AttributeError, TypeError, ValueError):
            # A key that is not `ix,iy` is not a cell this mapper wrote; skip it rather than answer
            # 500 for the whole map because the context was poked by something else.
            continue

    total = len(triples)
    truncated = total > _MAP_CELLS
    if truncated:
        triples.sort(key=lambda cell: (-cell[2], cell[0], cell[1]))
        triples = triples[:_MAP_CELLS]
    cell_size = _number(settings.get("cell_size_cm"))
    return web.json_response(
        {
            "map": {
                "cell_size_cm": cell_size if cell_size is not None else 10.0,
                "cells": triples,
                "count": total,
                "truncated": truncated,
            },
            "grid_enabled": grid_enabled,
            "document": document,
            "pose": _pose_in_document(plane.context),
            "trail": _trail_in_document(plane.context),
            "health": _map_health(plane.context),
            "surface_step_cm": surface_step_cm,
        },
        headers={"Cache-Control": "no-store"},
    )


async def _map_save(request: web.Request) -> web.Response:
    """Save the home-map document a console edited, guarded by `meta.rev` (M1).

    The body carries the **client** shape `GET /map` published - `cells` flat, `samples` a count, the
    user's sections beside them. The file keeps `grid.cells` and the sample log, which are the
    mapper's and which a client never received; `mapping/home_map.py::validate_document` judges both
    spellings, so a document this route accepts is one the next start can load.

    `rev` is optimistic concurrency, not a lock: the client sends the generation it read, a mismatch
    answers `409` with the current one, and nothing is overwritten. A scan save never bumps it, so a
    30 s snapshot cannot invalidate an edit in progress.
    """
    plane = _plane(request)
    settings = (plane.context.get("settings") or {}).get("mapping", {})
    settings = settings if isinstance(settings, dict) else {}
    path = map_path(settings.get("home_map_path", "data/home_map.json"), "data/home_map.json")

    body = await _json_body(request)
    raw = body.get("document")
    if not isinstance(raw, dict):
        return web.json_response(
            {"error": "bad_request", "detail": "the body must carry a `document` object"}, status=400
        )

    result = validate_document(raw)
    if result.map is None:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": "the map document was refused",
                "problems": list(result.problems) or [str(result.reason or "unknown")],
            },
            status=400,
        )
    incoming = result.map

    # The file is the authority on what a restart would read: `home_map_load_path` ships empty, so a
    # `rev` taken from the context alone would forget every edit made before the last restart, and
    # the sample log the mapper writes is never on the wire at all.
    stored_map = load_home_map(path).map
    if stored_map is not None:
        current_rev = stored_map.rev
        created_at = stored_map.meta.get("created_at")
        kept_samples: list[dict[str, Any]] | None = [
            dict(entry) for entry in stored_map.samples
        ]
    else:
        published_document = _map_document(plane.context) or {}
        published_meta_raw = (
            published_document.get("meta") if isinstance(published_document, dict) else None
        )
        published_meta = published_meta_raw if isinstance(published_meta_raw, dict) else {}
        current = published_meta.get("rev")
        current_rev = current if isinstance(current, int) and not isinstance(current, bool) else 0
        created_at = published_meta.get("created_at")
        kept_samples = None
    if incoming.rev != current_rev:
        return web.json_response(
            {
                "error": "conflict",
                "detail": "the map changed since this copy was read; fetch it again",
                "rev": current_rev,
            },
            status=409,
        )

    document = incoming.to_file_document()
    if not incoming.samples and kept_samples:
        # The client sent a count, not the log. Keeping the file's window is what stops an edit from
        # quietly deleting evidence the mapper wrote.
        document["samples"] = kept_samples
    # The version is the writer's claim, not the reader's. `validate_document` accepts any older
    # document, so a v2 file edited here is written as v3 rather than left labelled with a shape it no
    # longer has: an older reader refuses a newer file *by name*, and that refusal is the only thing
    # that stops it dropping a section it does not know (H3).
    document["version"] = CURRENT_VERSION
    now = time.time()
    document["meta"]["rev"] = current_rev + 1
    created = _number(created_at)
    document["meta"]["created_at"] = created if created is not None else now
    document["meta"]["updated_at"] = now
    document["meta"]["source"] = "user"
    # Whether this map carries a real dimension is a claim about the whole document, derived here
    # rather than taken from the console: one writer per fact, the same reason `meta.source` is
    # stamped on this side (H2). `size_cm` stays per-room — a client that needs the per-room truth
    # reads the room, not this.
    document["meta"]["scale_source"] = scale_source_for(document.get("rooms"))

    try:
        write_document(path, document)
    except OSError as exc:
        logger.warning("Home map not written to %s: %s", path, exc)
        return web.json_response(
            {"error": "unavailable", "detail": f"the map file could not be written: {exc}"},
            status=503,
        )

    # Publish what a restart would read, not what was sent: one shape answers `GET /map` and feeds
    # the mapper's next snapshot.
    verified = validate_document(document)
    wire = verified.map.to_document() if verified.map is not None else incoming.to_document()
    plane.context.set("home_map", wire)
    return web.json_response(
        {"rev": wire["meta"].get("rev"), "document": wire},
        headers={"Cache-Control": "no-store"},
    )


async def _map_pose(request: web.Request) -> web.Response:
    """Move the dog on the map, and make the move stick (M5).

    Two writes with different lifetimes, made together so they cannot disagree. The **pose** is
    immediate: `pose_reset` re-anchors `navigation/odometry.py` at that point in `odometry`'s own
    frame, which is what the next plan measures from. The **document** is durable: the `dog` section
    lands in the file, `rev` moves because the file changed, and a restart still knows where the dog
    was left.

    The body is in the **document's** frame (`x` left, `y` forward) like every other point the
    console sends, and is swapped exactly once, here (#347). Nothing here drives the dog: this is
    about where the runtime believes it is, and a correction while walking simply re-anchors mid-walk.
    """
    plane = _plane(request)
    body = await _json_body(request)
    doc_x = _number(body.get("x_cm"))
    doc_y = _number(body.get("y_cm"))
    if doc_x is None or doc_y is None:
        return web.json_response(
            {"error": "bad_request", "detail": "x_cm and y_cm must be numbers"}, status=400
        )
    heading = _number(body.get("heading_deg"))

    forward_cm, left_cm = document_point_to_runtime((doc_x, doc_y))
    frame_ts = plane.now()
    plane.context.set(
        "pose_reset",
        {"x_cm": forward_cm, "y_cm": left_cm, "source": "user", "frame_ts": frame_ts},
    )

    dog: dict[str, Any] = {
        "x_cm": round(doc_x, 3),
        "y_cm": round(doc_y, 3),
        "source": "user",
        "ts": time.time(),
    }
    if heading is not None:
        dog["heading_deg"] = round(heading, 3)

    settings = (plane.context.get("settings") or {}).get("mapping", {})
    settings = settings if isinstance(settings, dict) else {}
    path = map_path(settings.get("home_map_path", "data/home_map.json"), "data/home_map.json")
    rev: int | None = None
    document = _file_document(plane, path)
    if document is not None:
        meta = document.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        document["meta"] = meta
        meta["rev"] = int(_number(meta.get("rev")) or 0) + 1
        meta["updated_at"] = time.time()
        meta["source"] = "user"
        document["dog"] = dog
        try:
            write_document(path, document)
        except OSError as exc:
            logger.warning("Dog position not written to %s: %s", path, exc)
        else:
            verified = validate_document(document)
            wire = verified.map.to_document() if verified.map is not None else None
            if wire is not None:
                plane.context.set("home_map", wire)
                rev = wire["meta"].get("rev")

    return web.json_response(
        {"accepted": True, "rev": rev, "dog": dog, "frame_ts": frame_ts},
        headers={"Cache-Control": "no-store"},
    )


async def _map_go(request: web.Request) -> web.Response:
    """Send the dog to a point on the map: the console's click, handed to `route_follower` (M5).

    One write and no motion. `navigation/route_follower.py::_accept_request` plans the route itself on
    the next tick and publishes `route` with either waypoints or the refusal that ended it - the
    existing hand-off, so this adds no second planner and no second clearance rule.

    A goal in map coordinates means nothing to a dog that cannot place itself on the map, so the
    answer is `409` and *why*: the refusal the follower would publish, said before the client starts
    watching for a walk that will not happen. A route already in flight is `409` too - one
    destination at a time is what keeps the brake and the throttle one control.
    """
    plane = _plane(request)
    body = await _json_body(request)
    doc_x = _number(body.get("x_cm"))
    doc_y = _number(body.get("y_cm"))
    if doc_x is None or doc_y is None:
        return web.json_response(
            {"error": "bad_request", "detail": "x_cm and y_cm must be numbers"}, status=400
        )

    localization, tier = _localization_of(plane.context)
    if not _has_pose(localization):
        return _no_pose_response(tier)

    route = plane.context.get("route")
    if isinstance(route, dict) and route.get("state") in ("publish", "walking"):
        return web.json_response(
            {"error": "conflict", "detail": "a route is already being walked", "current": route},
            status=409,
        )

    forward_cm, left_cm = document_point_to_runtime((doc_x, doc_y))
    goal = {"x_cm": round(forward_cm, 3), "y_cm": round(left_cm, 3)}
    plane.context.set("route_request", {"goal_cm": goal})
    return web.json_response({"accepted": True, "goal_cm": goal, "tier": tier}, status=202)


def _room_ref(room: dict[str, Any] | None) -> dict[str, Any] | None:
    """A room as a client can name it, without shipping its polygon back."""
    if room is None:
        return None
    return {"id": room.get("id"), "name": room.get("name"), "label": room_label(room)}


def _safe_pose(pose: dict[str, Any], key: str) -> float:
    """One coordinate of a pose, or `0.0` when it is not a number. Callers check `_has_pose` first."""
    value = _number(pose.get(key))
    return value if value is not None else 0.0


def _mapped_cells(context, document: dict[str, Any]) -> dict[str, Any]:
    """The cells to plan over: the live grid first, the document's flat copy second.

    The live grid is the mapper's own and newer than any save; the document is what a restart would
    read. `mapping/planner.py` treats a cell below the hit threshold as unknown ground rather than
    clear, so an empty grid plans a straight line and says how much room it believed it had through
    each waypoint's `clearance_cm`.
    """
    state = context.get("mapping_state")
    if isinstance(state, dict):
        grid = state.get("grid")
        cells = grid.get("cells") if isinstance(grid, dict) else None
        if isinstance(cells, dict) and cells:
            return cells
    flat = document.get("cells")
    return flat if isinstance(flat, dict) else {}


async def _map_preview(request: web.Request) -> web.Response:
    """What a walk to that point would look like, or the refusal that stops it (M6).

    A read, not a command: it plans with the same pure `mapping/planner.py::plan_route` that
    `route_follower` walks, and writes nothing. That is why the scope is `state:read` and not `move` -
    a client that may not drive is exactly the client that should be able to see the route first.

    Two refusals belong to this route, and they are what a `keep_out` room finally *means* (#353):
    `goal_in_keep_out` when the clicked point is inside one, `route_in_keep_out` when the walk crosses
    one. Both name the room. Neither is decided here from scratch - `mapping/rooms.py` owns the geometry
    and `mapping/planner.py` still owns the route.

    The case that is **not** refused is a dog already standing inside a keep-out room. A room is marked
    to keep the dog out, not to imprison it: refusing would leave no way to plan the walk back out. The
    answer says so in `note` rather than allowing it silently.
    """
    plane = _plane(request)
    body = await _json_body(request)
    doc_x = _number(body.get("x_cm"))
    doc_y = _number(body.get("y_cm"))
    if doc_x is None or doc_y is None:
        return web.json_response(
            {"error": "bad_request", "detail": "x_cm and y_cm must be numbers"}, status=400
        )

    localization, tier = _localization_of(plane.context)
    if not _has_pose(localization):
        return _no_pose_response(tier)
    pose = localization.get("pose")
    pose = pose if isinstance(pose, dict) else {}

    forward_cm, left_cm = document_point_to_runtime((doc_x, doc_y))
    start = (_safe_pose(pose, "x"), _safe_pose(pose, "y"))
    document = _map_document(plane.context) or {}
    goal_document = {"x_cm": round(doc_x, 3), "y_cm": round(doc_y, 3)}

    def refuse(reason: str, detail: str, room: dict[str, Any] | None = None) -> web.Response:
        # A refusal is a `200`: it is a true answer about a hypothetical. Only a malformed request or a
        # missing pose is a `4xx`, and both are decided before a route exists.
        return web.json_response(
            {
                "valid": False,
                "refusal": reason,
                "detail": detail,
                "distance_cm": None,
                "goal_cm": goal_document,
                "waypoints": [],
                "keep_out": _room_ref(room),
                "note": None,
            },
            headers={"Cache-Control": "no-store"},
        )

    inside = keep_out_room_at((doc_x, doc_y), document)
    if inside is not None:
        return refuse(
            "goal_in_keep_out", f"that point is inside the keep-out room {room_label(inside)}", inside
        )

    settings = (plane.context.get("settings") or {}).get("mapping", {})
    settings = settings if isinstance(settings, dict) else {}
    plan = plan_route(
        _mapped_cells(plane.context, document), start, (forward_cm, left_cm), settings
    )
    if not plan.ok:
        return refuse(str(plan.refusal or "no_path"), str(plan.detail or "no route was found"))

    route_document = [
        runtime_point_to_document((waypoint.x_cm, waypoint.y_cm)) for waypoint in plan.waypoints
    ]
    waypoints = [
        {
            "x_cm": round(point[0], 1),
            "y_cm": round(point[1], 1),
            "clearance_cm": waypoint.to_dict()["clearance_cm"],
        }
        for point, waypoint in zip(route_document, plan.waypoints, strict=False)
    ]

    # A room marked keep-out *after* the dog walked in must not become a trap: the walk out crosses it
    # by definition, so the path is only judged when the dog starts outside one.
    start_room = keep_out_room_at(runtime_point_to_document(start), document)
    note: str | None = None
    if start_room is not None:
        note = f"the dog is already inside {room_label(start_room)}; the route out is not refused"
    else:
        # From the goal back along the route: the first leg runs from the goal to the cell the dog
        # stands in, so this judges the whole walk and not only the waypoints.
        crossing = polyline_in_keep_out([(doc_x, doc_y), *route_document], document)
        if crossing is not None:
            return refuse(
                "route_in_keep_out",
                f"the route crosses the keep-out room {room_label(crossing)}",
                crossing,
            )

    distance_cm = 0.0
    previous = start
    for waypoint in plan.waypoints:
        distance_cm += math.hypot(waypoint.x_cm - previous[0], waypoint.y_cm - previous[1])
        previous = (waypoint.x_cm, waypoint.y_cm)
    # The planner's last waypoint is the goal's *cell centre*, so a preview that stopped there would
    # understate every walk by up to half a cell.
    distance_cm += math.hypot(forward_cm - previous[0], left_cm - previous[1])

    return web.json_response(
        {
            "valid": True,
            "refusal": None,
            "detail": None,
            "distance_cm": round(distance_cm, 1),
            "goal_cm": goal_document,
            "waypoints": waypoints,
            "keep_out": None,
            "note": note,
        },
        headers={"Cache-Control": "no-store"},
    )
