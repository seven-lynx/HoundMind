"""The routine surface, split out of `services/api.py` (AP5).

A routine is playable state, not a command: `POST /routines/{id}/run` writes one request key and
`behavior/routine_runner.py` turns it into a step per tick. Both read handlers read the *runner's*
report rather than the directory, because two readers of one directory are two answers to "which
routines exist" — and the dog can only play the ones it loaded (#172).

**The API asks; the runner and the interlock still decide, step by step.** Nothing here publishes a
motion intent: `_routine_run` hands the runner a request and waits half a second for its ack, and a
refusal comes back as the POST's own `409` rather than a `202` a client has no way to retract (#72).
"""

from __future__ import annotations

import asyncio
import threading
from difflib import get_close_matches
from typing import TYPE_CHECKING

from aiohttp import web

from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.routine_store import RoutineConflict, RoutineStore, StoreReport
from houndmind_ai.services.http import (
    _json_body,
    _optional_json_body,
    _plane,
    _problem_dict,
)

if TYPE_CHECKING:
    from houndmind_ai.services.api import ControlPlane

# How long a routine start waits for the runner's answer. The runner reads the request on the
# decision thread, at the loop rate (200 ms at the shipped 5 Hz), so half a second is two ticks -
# enough for the normal case and short enough that a plane with no runner in it answers promptly.
# A timeout is not a refusal: the request is still queued, and the POST keeps its old `202`.
_ROUTINE_ACK_TIMEOUT_S = 0.5


def _routine_state(plane: ControlPlane) -> dict[str, object] | None:
    """The run in progress, as the runner serialises it (`RoutineRun.to_dict`).

    Duck-typed on purpose: `services` may not import `behavior` (the API would then own the
    runner's shape), so this republishes the dict the runner built instead of rebuilding one.
    """
    run = plane.context.get("routine_run")
    to_dict = getattr(run, "to_dict", None)
    return to_dict() if callable(to_dict) else None


def _routine_store(plane: ControlPlane) -> RoutineStore | None:
    """The store the runner published, or None when no runner is loaded (#172).

    The API never builds its own: the runner's store is the one whose directory the catalogue came
    from, and a second store over the same path would be a second opinion about what is claimed.
    """
    store = plane.context.get("routine_store")
    return store if isinstance(store, RoutineStore) else None


async def _routines_list(request: web.Request) -> web.Response:
    plane = _plane(request)
    report = plane.context.get("routine_report")
    if not isinstance(report, StoreReport):
        return web.json_response(
            {"error": "unavailable", "detail": "the routine runner is not running"}, status=503
        )
    return web.json_response(
        {
            "directory": str(report.directory),
            "routines": [report.routines[routine_id].to_dict() for routine_id in report.ids()],
            "refusals": {
                name: [_problem_dict(problem) for problem in problems]
                for name, problems in report.refusals.items()
            },
            "current": _routine_state(plane),
        }
    )


async def _routines_create(request: web.Request) -> web.Response:
    """Create or replace one routine file (#172).

    The document is validated by `check_routine` inside `RoutineStore.save` - the same function the
    loader runs - so an accepted routine is one the loader would accept too, locomotion opt-in and
    action names included.

    Creation and replacement are different requests: an id already on disk is a `409` unless
    `?replace=true`, because the directory is user data and a form that silently overwrites it loses
    somebody else's work with no undo.

    `reload_required` used to be the honest half of this route: the runner reads the directory once,
    so a routine written now only became playable after the next start (#196). It no longer is - the
    write sets `routine_reload`, the runner re-reads the directory on its next tick, and `GET
    /routines` and `POST /routines/{id}/run` follow immediately. A run already in flight keeps the
    steps it started with.
    """
    plane = _plane(request)
    store = _routine_store(plane)
    if store is None:
        return web.json_response(
            {"error": "unavailable", "detail": "the routine runner is not running"}, status=503
        )
    replace = str(request.query.get("replace", "")).strip().lower() in {"1", "true", "yes"}
    document = await _json_body(request)
    try:
        saved, problems = store.save(
            document,
            repertoire_from_settings(plane.context.get("settings")),
            replace=replace,
        )
    except RoutineConflict as exc:
        return web.json_response({"error": "conflict", "detail": exc.message}, status=409)
    if saved is None:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": "the routine was refused",
                "problems": [_problem_dict(problem) for problem in problems],
            },
            status=400,
        )
    # The runner re-reads the directory on its next tick, which is what makes the write playable
    # without a restart (#196). Set after the file is on disk, so a reload cannot race the save.
    plane.context.set("routine_reload", True)
    return web.json_response(
        {
            "routine": saved,
            "path": str(store.directory / f"{saved['id']}.json"),
            "reload_required": False,
        },
        status=201,
    )


async def _routine_run(request: web.Request) -> web.Response:
    """Start one routine. The API asks; the runner and the interlock still decide, step by step.

    Every check happens before the write, and nothing between them awaits, so two POSTs on the
    same event loop cannot both pass the "is one already running?" test.
    """
    plane = _plane(request)
    routine_id = str(request.match_info.get("id") or "").strip()
    report = plane.context.get("routine_report")
    if not isinstance(report, StoreReport):
        return web.json_response(
            {"error": "unavailable", "detail": "the routine runner is not running"}, status=503
        )
    routine = report.get(routine_id)
    if routine is None:
        matches = get_close_matches(routine_id, list(report.ids()), n=1)
        return web.json_response(
            {
                "error": "not_found",
                "detail": f"no routine named '{routine_id}' was loaded",
                "suggestion": matches[0] if matches else None,
            },
            status=404,
        )

    body = await _optional_json_body(request)
    dry_run = body.get("dry_run", False)
    if not isinstance(dry_run, bool):
        # A string "false" is truthy, so a coercion would start a real run for a client that asked
        # for a rehearsal — the trap `kernel/routine.py` closes for `allow_locomotion`.
        return web.json_response(
            {"error": "bad_request", "detail": "dry_run must be true or false"}, status=400
        )

    current = plane.context.get("routine_run")
    pending = plane.context.get("routine_request")
    if getattr(current, "state", None) == "running" or pending is not None:
        detail = (
            "a run request is already queued for the next tick"
            if pending is not None
            else f"'{getattr(current, 'routine_id', 'a routine')}' is still running"
        )
        return web.json_response(
            {"error": "conflict", "detail": detail, "current": _routine_state(plane)},
            status=409,
        )

    # The runner reads this on the decision thread and fills in the answer, so the wait below is an
    # executor wait for the same reason `submit()` is one: blocking the aiohttp loop would freeze
    # telemetry for every other client. `ack` and `refusal` are the two-way door the request needs;
    # a plain dict stays JSON-shaped for everything else that reads the key.
    ack = threading.Event()
    start_request: dict[str, object] = {
        "id": routine.id,
        "dry_run": dry_run,
        "ack": ack,
    }
    plane.context.set("routine_request", start_request)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, ack.wait, _ROUTINE_ACK_TIMEOUT_S)
    refusal = start_request.get("refusal")
    if isinstance(refusal, str) and refusal:
        # The runner looked at the request and said no, so this is the POST's own answer rather
        # than a `202` a client has no way to retract (#72).
        return web.json_response(
            {"error": "conflict", "detail": refusal, "current": _routine_state(plane)},
            status=409,
        )
    return web.json_response(
        {"accepted": True, "id": routine.id, "dry_run": dry_run, "steps": len(routine.steps)},
        status=202,
    )
