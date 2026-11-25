"""The people and places surface, split out of `services/api.py` (AP3).

Nine handlers and the helpers only they call: the place catalogue, the picture store behind it and
the walk request, then the identity roster. They moved together because both are lists a console
draws from context keys the runtime publishes (`place_store`, `identity_roster`), and because both
validate a JSON body the same way before the store or the module sees it.

**`_number` and `_problem_dict` come from `services/http.py`**, beside the body parsers that produce
the values they judge, and the pose helpers from `services/api_map.py`, which owns the map frame
(AP5a). Neither is copied: a second copy is exactly the duplication #402 exists to remove.

**`view_from_frame` is imported inside `_places_teach`, not at the top.** `tests/test_api_places.py`
plants refusals through `houndmind_ai.services.api.view_from_frame` (`:474`, `:573`, `:601`); a
module-scope `from ... import view_from_frame` would bind the original function object and the
plant would stop intercepting, so the name is resolved through `services.api` on every request —
the same idiom `services/api_camera.py` uses for `_camera_principal`.
"""

from __future__ import annotations

import asyncio
import logging
import math
from difflib import get_close_matches
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web

from houndmind_ai.kernel.place import Place, slug
from houndmind_ai.kernel.place_store import PlaceStore
from houndmind_ai.mapping.home_map import (
    document_point_to_runtime,
    runtime_point_to_document,
)
from houndmind_ai.perception.place_views import (
    DEFAULT_VIEWS_DIR,
    PlaceView,
    load_views,
    remove_views,
    save_views,
    thumb_b64,
    upsert_view,
    view_from_jpeg,
)
from houndmind_ai.services.api_map import (
    _localization_of,
    _map_document,
    _no_pose_response,
)
from houndmind_ai.services.http import (
    _json_body,
    _number,
    _optional_json_body,
    _plane,
    _problem_dict,
)

if TYPE_CHECKING:
    from houndmind_ai.services.api import ControlPlane

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ places (P4 PL5)


def _place_store(plane: ControlPlane) -> PlaceStore | None:
    """The one store the navigator published, or `None` when nothing owns the file.

    The API does not build one of its own. `PlaceStore` locks its read-modify-write pairs per
    instance (`kernel/place_store.py`), so a second store over the same path would be a second
    writer holding a second lock — the lost update that lock exists to prevent.
    """
    store = plane.context.get("place_store")
    return store if isinstance(store, PlaceStore) else None


def _no_places() -> web.Response:
    """503, not an empty catalogue: "nothing is defined yet" and "nothing is running" differ."""
    return web.json_response(
        {
            "error": "unavailable",
            "detail": "the place navigator is not running; enable modules.place_navigator",
        },
        status=503,
    )


def _bad_place(detail: str) -> web.Response:
    return web.json_response({"error": "bad_request", "detail": detail}, status=400)


def _place_not_found(store: PlaceStore, wanted: str, detail: str) -> web.Response:
    matches = get_close_matches(wanted, list(store.load().ids()), n=1)
    return web.json_response(
        {"error": "not_found", "detail": detail, "suggestion": matches[0] if matches else None},
        status=404,
    )


def _views_dir(plane: ControlPlane) -> Path:
    """Where taught views live: `settings.place_recognition.views_dir`, else the shipped default.

    The same key `navigation/place_recognition.py` reads, so a place taught here is one it can
    recognise later. `~` is expanded once, here, because a `Path` handed to `save_views` unexpanded
    would write a directory literally called `~` in the working directory.
    """
    settings = (plane.context.get("settings") or {}).get("place_recognition", {})
    settings = settings if isinstance(settings, dict) else {}
    raw = settings.get("views_dir")
    return Path(raw if isinstance(raw, str) and raw.strip() else DEFAULT_VIEWS_DIR).expanduser()


def _view_entry(place: Place, views: dict[str, PlaceView]) -> dict[str, object]:
    """One place as `GET /places` publishes it: its stored keys, plus the picture when there is one.

    Additive on purpose (M7). `has_view` is what the **places file** claims; `thumb` is what the
    **views file** actually holds. Where the two disagree both are published as they are — the
    disagreement is the report, and resolving it silently is how a map stops matching the dog.
    """
    entry: dict[str, object] = dict(place.to_dict())
    view = views.get(place.id)
    entry["thumb"] = thumb_b64(view) if view is not None else None
    return entry


def _pose_origin(plane: ControlPlane) -> tuple[float, float, float | None] | None:
    """Where the dog believes it is, in the document frame: `(x_cm, y_cm, heading_deg | None)`.

    The live pose first — that is what `localization` publishes. Then the `dog` section the map
    file's last correction wrote, because a correction outlives the tier that produced it and is
    still the most recent thing a human said about where the dog is. `None` when neither exists:
    a bearing measured from the map's corner is a claim nothing made.
    """
    localization = plane.context.get("localization")
    pose = localization.get("pose") if isinstance(localization, dict) else None
    if isinstance(pose, dict):
        forward_cm = _number(pose.get("x"))
        left_cm = _number(pose.get("y"))
        if forward_cm is not None and left_cm is not None:
            doc_x, doc_y = runtime_point_to_document((forward_cm, left_cm))
            return doc_x, doc_y, _number(pose.get("yaw_deg"))
    document = _map_document(plane.context) or {}
    dog = document.get("dog")
    if isinstance(dog, dict):
        stored_x = _number(dog.get("x_cm"))
        stored_y = _number(dog.get("y_cm"))
        if stored_x is not None and stored_y is not None:
            return stored_x, stored_y, _number(dog.get("heading_deg"))
    return None


async def _places_list(request: web.Request) -> web.Response:
    """The catalogue, whatever the file refused, and the walk in progress.

    Each place carries its `has_view` flag and, when the views file holds one, the 32x24 thumbnail
    as base64 (M7). Additive: a client that has never heard of a pin reads exactly what it read
    before, and one that has draws the photo the dog will recognise the place by.
    """
    plane = _plane(request)
    store = _place_store(plane)
    if store is None:
        return _no_places()
    report = store.load()
    views = {view.place_id: view for view in load_views(_views_dir(plane))}
    return web.json_response(
        {
            "path": str(report.path),
            "places": [_view_entry(place, views) for place in report.places],
            "refusals": [_problem_dict(problem) for problem in report.refusals],
            "goal": plane.context.get("place_goal"),
        }
    )


async def _places_create(request: web.Request) -> web.Response:
    """Create one place. The store owns the rules; this owns the JSON types it was handed.

    A duplicate name, a heading outside the range, a name with no usable characters and the
    catalogue limit are all `Problem`s from `PlaceStore.add` — which `place_store.py` writes for a
    client to show a user — so they become a 400 body rather than a second set of rules kept in
    step by hand.
    """
    plane = _plane(request)
    store = _place_store(plane)
    if store is None:
        return _no_places()

    body = await _json_body(request)
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return _bad_place("name must be a non-empty string")
    heading = _number(body.get("heading_deg"))
    if heading is None:
        return _bad_place("heading_deg must be a number")
    distance = _number(body.get("distance_cm"))
    if distance is None:
        return _bad_place("distance_cm must be a number")
    anchor = body.get("anchor", "")
    if not isinstance(anchor, str):
        return _bad_place("anchor must be a string")
    raw_confidence = body.get("confidence")
    confidence = None if raw_confidence is None else _number(raw_confidence)
    if raw_confidence is not None and confidence is None:
        return _bad_place("confidence must be a number or null")

    place, problems = store.add(
        name,
        heading_deg=heading,
        distance_cm=distance,
        anchor=anchor,
        confidence=confidence,
    )
    if place is None:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": "the place was refused",
                "problems": [_problem_dict(problem) for problem in problems],
            },
            status=400,
        )
    return web.json_response({"place": place.to_dict()}, status=201)


async def _places_teach(request: web.Request) -> web.Response:
    """Teach the spot the dog is standing in, with the camera's view of it (M7).

    Four things happen in an order that cannot leave a lie behind. The frame is turned into a view
    **in memory**, so a featureless wall costs nothing; the place is created by the store, so a
    duplicate name is the same `problems[]` a `POST /places` body gets; the view is written; and
    `has_view` is flipped **last**, so the flag is true only once a picture really is on disk. A
    failure after the place exists names which half landed instead of claiming nothing happened.

    `x_cm`/`y_cm` are the pin's point in the **document** frame, like every other point the console
    sends, and the bearing and range stored in the place are measured from the dog's own pose —
    because that is the only thing `place_navigator` can walk. A pin under the dog is a place at
    zero distance: the dog is here, and the view is what recognises it next time.
    """
    plane = _plane(request)
    store = _place_store(plane)
    if store is None:
        return _no_places()

    body = await _json_body(request)
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return _bad_place("name must be a non-empty string")
    # The id the view is filed under, before the place exists to ask. `slug` is exactly the rule
    # `PlaceStore.add` applies to the same name (`place_store.py::_add`), and if the two ever part
    # company the flag lands true on a place whose picture is filed elsewhere — which `GET /places`
    # publishes as `has_view` beside a null `thumb` rather than hiding.
    place_id = slug(name.strip())
    if not place_id:
        return _bad_place("name needs letters, digits, '_' or '-' so the place can be given an id")

    # 1. A view, or a reason. `vision_frame` is the raw array `vision`/`vision_pi4` publish; the
    #    control plane's camera holds encoded frames and only `vision_pi4` publishes those too, so
    #    trying both is what keeps a teach working on the Pi 3 path as well.
    # Resolved through `services.api` on every call, never at module scope: `tests/test_api_places.py`
    # plants its stub at `houndmind_ai.services.api.view_from_frame`, and a module-scope
    # `from ... import` would bind the real function so the plant stopped intercepting — the same
    # rule `services/api_camera.py` follows for `_camera_principal`.
    from houndmind_ai.services.api import view_from_frame

    frame = plane.context.get("vision_frame")
    try:
        if frame is not None:
            view = view_from_frame(frame, place_id)
        else:
            jpeg, _stamp = plane.camera.latest()
            if jpeg is None:
                return web.json_response(
                    {
                        "error": "unavailable",
                        "detail": "no camera frames are being published; enable a vision module "
                        "to teach a place by its picture",
                    },
                    status=503,
                )
            view = view_from_jpeg(jpeg, place_id)
    except ImportError as exc:
        return web.json_response(
            {
                "error": "unavailable",
                "detail": f"OpenCV is not installed ({exc.name or 'cv2'}); a view needs it",
            },
            status=503,
        )
    except ValueError as exc:
        # `view_from_frame` already says what to do about a blank wall, and that sentence is the
        # point of the refusal — restating it here is how two messages drift apart.
        return _bad_place(str(exc))

    # 2. Where the pin is, relative to the dog.
    pin_x = _number(body.get("x_cm"))
    pin_y = _number(body.get("y_cm"))
    if (pin_x is None) != (pin_y is None):
        return _bad_place("x_cm and y_cm must both be numbers, or both be left out")
    _localization, tier = _localization_of(plane.context)
    origin = _pose_origin(plane)
    if origin is None:
        # No live pose and no confirmed position: a bearing from here is a claim nothing measured.
        return _no_pose_response(tier)
    if pin_x is None or pin_y is None:
        pin_x, pin_y = origin[0], origin[1]

    # `home_map`'s swap, once per point (#347): the pin and the dog are both document points, and
    # the vector between them is taken in the runtime frame so no reader has to decide which of the
    # two orders `x` and `y` are in.
    pin_forward, pin_left = document_point_to_runtime((pin_x, pin_y))
    dog_forward, dog_left = document_point_to_runtime((origin[0], origin[1]))
    delta_forward = pin_forward - dog_forward
    delta_left = pin_left - dog_left
    distance_cm = math.hypot(delta_forward, delta_left)
    # A place at zero distance needs no heading: arrival is decided before a turn is ever considered
    # (`navigation/place_navigator.py`). Keeping the dog's own reading beats inventing a zero.
    heading_deg = origin[2] if origin[2] is not None else 0.0
    if distance_cm > 0.0:
        heading_deg = math.degrees(math.atan2(delta_left, delta_forward))

    places_settings = (plane.context.get("settings") or {}).get("places", {})
    places_settings = places_settings if isinstance(places_settings, dict) else {}
    anchor = str(places_settings.get("anchor") or "")

    # 3. The place, judged by the store — the same rules a `POST /places` body meets.
    place, problems = store.add(
        name,
        heading_deg=round(heading_deg, 3),
        distance_cm=round(distance_cm, 3),
        anchor=anchor,
    )
    if place is None:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": "the place was refused",
                "problems": [_problem_dict(problem) for problem in problems],
            },
            status=400,
        )

    # 4. The picture, then the flag.
    views_dir = _views_dir(plane)
    try:
        written = save_views(views_dir, upsert_view(load_views(views_dir), view))
    except OSError as exc:
        logger.warning("View for %s not written to %s: %s", place.id, views_dir, exc)
        return web.json_response(
            {
                "error": "unavailable",
                "detail": f"the place was created but its picture could not be written: {exc}",
                "place": place.to_dict(),
            },
            status=503,
        )

    flagged, flag_problems = store.update(place.id, has_view=True)
    if flagged is None:
        # The view is on disk either way; only the catalogue's record of it is missing, and
        # `GET /places` shows that as a thumbnail beside `has_view: false` instead of hiding it.
        logger.warning(
            "Place %s has a view but its flag was not written: %s", place.id, flag_problems
        )
    entry: dict[str, object] = dict((flagged or place).to_dict())
    entry["thumb"] = thumb_b64(view)
    return web.json_response({"place": entry, "view_path": str(written)}, status=201)


async def _place_delete(request: web.Request) -> web.Response:
    """Forget one place. A second call is a 404, never a silent success (P4 PL6).

    The view goes with it (#356). `PlaceStore.remove` rewrites only the places file, so a view left
    behind kept `place_recognition` naming a place the user had just removed — a `localization.reason`
    for a spot that no longer exists, and a stale entry competing in every later `match`. The place is
    already gone when the second write is attempted, so a failure to drop the view is a warning, not a
    500 that says nothing happened.
    """
    plane = _plane(request)
    store = _place_store(plane)
    if store is None:
        return _no_places()
    wanted = str(request.match_info.get("id") or "").strip()
    removed, problems = store.remove(wanted)
    if removed is None:
        detail = problems[0].message if problems else f"no place with id or name {wanted!r}"
        return _place_not_found(store, wanted, detail)
    views_dir = _views_dir(plane)
    try:
        save_views(views_dir, remove_views(load_views(views_dir), removed.id))
    except OSError as exc:
        logger.warning("View for %s not removed from %s: %s", removed.id, views_dir, exc)
    return web.json_response({"removed": removed.to_dict(), "path": str(store.path)})


async def _place_update(request: web.Request) -> web.Response:
    """Correct one place: a typo in the name, a heading measured wrong (#173).

    `id` is neither editable nor derived from the new name. Goals and the navigator address a place
    by id, so a rename must not move the handle out from under a walk that is already under way.
    An empty body is a 400 rather than a no-op: a PATCH that changes nothing is how a client comes to
    believe it edited something.
    """
    plane = _plane(request)
    store = _place_store(plane)
    if store is None:
        return _no_places()
    wanted = str(request.match_info.get("id") or "").strip()

    body = await _json_body(request)
    if "id" in body:
        return _bad_place(
            "id cannot be changed; delete the place and create it under the new name"
        )
    name = body.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        return _bad_place("name must be a non-empty string")
    heading = None
    if "heading_deg" in body:
        heading = _number(body.get("heading_deg"))
        if heading is None:
            return _bad_place("heading_deg must be a number")
    distance = None
    if "distance_cm" in body:
        distance = _number(body.get("distance_cm"))
        if distance is None:
            return _bad_place("distance_cm must be a number")
    anchor = None
    if "anchor" in body:
        if not isinstance(body.get("anchor"), str):
            return _bad_place("anchor must be a string")
        anchor = str(body.get("anchor"))
    if name is None and heading is None and distance is None and anchor is None:
        return _bad_place("give at least one of name, heading_deg, distance_cm or anchor")

    # Resolve the handle here, so a 404 does not depend on how the store words a refusal: the store
    # owns the validation problems, and this owns "there is no such place".
    report = store.load()
    if not (report.get(wanted) or report.by_name(wanted)):
        return _place_not_found(store, wanted, f"no place with id or name {wanted!r}")

    place, problems = store.update(
        wanted,
        name=name,
        heading_deg=heading,
        distance_cm=distance,
        anchor=anchor,
    )
    if place is None:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": "the edit was refused",
                "problems": [_problem_dict(problem) for problem in problems],
            },
            status=400,
        )
    return web.json_response({"place": place.to_dict(), "path": str(store.path)})


async def _place_go(request: web.Request) -> web.Response:
    """Ask the navigator to walk to one place. The API asks; the navigator and the interlock decide.

    The request is written for the next tick, exactly like `POST /routines/{id}/run`: every check
    happens before the write and nothing awaits between them. Whether the dog actually sets off —
    the anchor confirmation, a missing heading, a veto — is the navigator's answer, published on
    `place_goal` and readable at `GET /places`.
    """
    plane = _plane(request)
    store = _place_store(plane)
    if store is None:
        return _no_places()

    wanted = str(request.match_info.get("id") or "").strip()
    report = store.load()
    place = report.get(wanted) or report.by_name(wanted)
    if place is None:
        return _place_not_found(store, wanted, f"no place with id or name {wanted!r}")

    body = await _optional_json_body(request)
    at_anchor = body.get("at_anchor", False)
    if not isinstance(at_anchor, bool):
        # The string "false" is truthy, and this flag decides whether a walk across the room is
        # allowed to start. Same trap, same answer as `dry_run`.
        return _bad_place("at_anchor must be true or false")

    goal = plane.context.get("place_goal")
    # `"travelling"` is `navigation/place_navigator.py`'s own word for a walk in progress. Compared
    # as a string on purpose: `services` may not import `navigation`, the same reason
    # `_routine_state` reads `RoutineRun.to_dict` duck-typed instead of importing `behavior`.
    travelling = isinstance(goal, dict) and goal.get("state") == "travelling"
    if travelling or plane.context.get("place_request") is not None:
        return web.json_response(
            {
                "error": "conflict",
                "detail": "a walk to a place is already in flight",
                "current": goal,
            },
            status=409,
        )

    plane.context.set("place_request", {"id": place.id, "at_anchor": at_anchor})
    return web.json_response(
        {"accepted": True, "id": place.id, "name": place.name, "at_anchor": at_anchor},
        status=202,
    )


# ------------------------------------------------------------------ people (P4 PL6)

# The module that owns the identities, and the name `GET /api/v1/modules` reports it under.
_IDENTITY_MODULE = "face_recognition"


def _identity_status(plane: ControlPlane) -> dict[str, Any]:
    """What that module says about itself, or `{}` when it never registered."""
    table = plane.context.get("module_statuses")
    if isinstance(table, dict):
        entry = table.get(_IDENTITY_MODULE)
        if isinstance(entry, dict):
            return entry
    return {}


def _identity_off_reason(plane: ControlPlane) -> str:
    """Why there is no roster — in the module's own words when it has any, because it knows."""
    status = _identity_status(plane)
    if not status:
        return "identity is not registered; enable modules.face_recognition"
    if not status.get("enabled", True):
        return str(
            status.get("disabled_reason")
            or "identity is disabled; enable modules.face_recognition"
        )
    return str(status.get("last_error") or "identity is running but published no roster")


async def _people_list(request: web.Request) -> web.Response:
    """Who the dog has been taught, as ids and names — never a face, never an embedding.

    200 with an `identity` block rather than the 503 `/places` answers when no navigator runs:
    identity ships `enabled: false`, so an error status would make the shipped default a permanent
    failure on a screen a client wants to draw. The block is what stops `people: []` from being
    read as "nobody is enrolled" — the one wrong answer this route exists to prevent.

    `admin`, not `state:read`: an enrolled face is biometric data (`robot-pet-design.md` §6.4), so
    a paired phone holding `move` does not get to enumerate who lives here.
    """
    plane = _plane(request)
    roster = plane.context.get("identity_roster")
    if not isinstance(roster, dict):
        return web.json_response(
            {
                "identity": {
                    "enabled": False,
                    "backend": None,
                    "reason": _identity_off_reason(plane),
                },
                "path": None,
                "people": [],
                "last_enroll": None,
            }
        )
    people = roster.get("people")
    return web.json_response(
        {
            "identity": {"enabled": True, "backend": roster.get("backend"), "reason": None},
            "path": roster.get("path"),
            "people": people if isinstance(people, list) else [],
            "last_enroll": roster.get("last_enroll"),
        }
    )


async def _people_enroll(request: web.Request) -> web.Response:
    """Teach the dog one face, and answer with the handle a client polls (§9, P4 PL9).

    `202`, not `200`: an enrolment needs the next tick and exactly one face in frame, so the most
    this route can honestly promise is that the request is accepted. `GET /api/v1/people` is the
    state that carries the rest — the person appears in `people`, or `last_enroll.reason` says why
    not. Refusals used to stop at a log line no client can read.

    `503` when no identity module is running, the asymmetry `DELETE` already uses: a read can report
    "nothing to show" about a stopped module, a write cannot report "learning".
    """
    plane = _plane(request)
    if plane.context.get("identity_admin") is None:
        return _no_identity(plane)
    body = await _json_body(request)
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return web.json_response(
            {"error": "bad_request", "detail": "name must be a non-empty string"}, status=400
        )
    name = name.strip()
    person_id = slug(name)
    if not person_id:
        return web.json_response(
            {"error": "bad_request", "detail": "name needs at least one usable character"},
            status=400,
        )
    plane.context.set("face_recognition_command", {"action": "enroll", "name": name})
    return web.json_response({"id": person_id, "name": name, "status": "pending"}, status=202)


async def _people_delete(request: web.Request) -> web.Response:
    """Forget one person. A second call is a `404`, never a silent success (§7's rule for places).

    `503` where `/people` answers `200`, and the asymmetry is the point: a read can honestly report
    "nothing to show" about a module that is not running, a write cannot honestly report "removed".

    The work runs in an executor. Deleting the last LBPH person retrains the model from the images
    that remain — file reads and a `cv2.train`, which is not something to hold the event loop for.
    `ControlPlane.wait_for` already does exactly this for `CommandBus.wait`.
    """
    plane = _plane(request)
    admin = plane.context.get("identity_admin")
    if admin is None:
        return _no_identity(plane)
    wanted = str(request.match_info.get("id") or "").strip()
    if not wanted:
        return web.json_response(
            {"error": "bad_request", "detail": "a person id is required"}, status=400
        )

    removed = await asyncio.get_running_loop().run_in_executor(None, admin.forget, wanted)
    if removed is None:
        return web.json_response(
            {"error": "not_found", "detail": f"no person with id {wanted!r}"}, status=404
        )
    roster = plane.context.get("identity_roster")
    path = roster.get("path") if isinstance(roster, dict) else None
    return web.json_response({"removed": removed, "path": path})


def _no_identity(plane: ControlPlane) -> web.Response:
    """503 with the reason a client would have read in `identity`, for a write that cannot happen."""
    return web.json_response(
        {"error": "unavailable", "detail": _identity_off_reason(plane)}, status=503
    )
