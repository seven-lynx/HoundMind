"""The config, session, discovery and calibration surface (AP4, extended by AP5).

The three liveness and identity routes (`/meta`, `/health`, `/whoami`), the live-config read, patch
and dry-run, the connected-client registry, and the read-only calibration pair. They belong together
because they answer the questions an operator console asks before it changes anything — what is this
box, what may I change on it, and what has it measured.

`LIVE_CONFIG_KEYS` moved with them because the allow-list *is* the config contract: the route that
refuses a key and the two that name the allow-list in a refusal are one three-line rule, and splitting
them is how "would this be accepted" drifts from "was it accepted" (#406).

**The import direction is one-way, and that is what makes this module different.** It imports
`services/http.py`, `services/auth.py`, `services/config_writer.py`, `services/state.py` and
`kernel/config_schema.py` — never `services.api` at module scope — so it opens no cycle and `api.py`
imports it at the top rather than at the bottom.

**`_CALIBRATION_ACK_TIMEOUT_S` and `CALIBRATION_REQUESTS` stay in `services/api.py`, and are read
there at call time.** The allow-list is cited by `docs/CONTROL_API.md` as a `services/api.py` symbol,
and `tests/test_api_routes.py` patches the timeout on `services.api` so the "no ticking runtime"
case answers in 50 ms instead of a second. An in-call import resolves both names through that module
on every request, which is the same idiom `api_camera.py` uses for `_camera_principal`; a binding at
this module's scope would silently stop the patch from reaching and turn a fast test into a slow one
that still passes.

**`_header_token` left with `_command`.** It stayed behind in AP4 for the same reason and moved to
`services/api_commands.py` in AP5, when its only caller did.
"""

from __future__ import annotations

import asyncio
import secrets

from aiohttp import web

from houndmind_ai.kernel.config_schema import validate_settings_section
from houndmind_ai.services.auth import AuthError
from houndmind_ai.services.config_writer import ConfigWriteError
from houndmind_ai.services.http import _PRINCIPAL, _json_body, _plane
from houndmind_ai.services.state import redact_config

# Keys a client may change live. Each one is re-read from `settings` every tick by its module,
# so a change takes effect immediately; everything else is refused rather than silently stored,
# because a config write that does nothing is how B-07 happened in the first place.
LIVE_CONFIG_KEYS: tuple[str, ...] = (
    "behavior.action_cooldown_s",
    "led.brightness",
    "motors.min_action_interval_s",
    "navigation.safe_distance_cm",
)


# ------------------------------------------------------------------------------ discovery
# The three routes a client reads before it holds anything else. `/meta` and `/health` are public by
# contract (`api_routes.py`'s `scope=None`); `/whoami` is the one route with no scope requirement.


async def _meta(request: web.Request) -> web.Response:
    return web.json_response(_plane(request).meta())


async def _health(request: web.Request) -> web.Response:
    # Liveness only. No detail: this route is unauthenticated by design.
    return web.json_response({"status": "ok"})


async def _whoami(request: web.Request) -> web.Response:
    """What this token is, and what it may do (#168).

    Deliberately no scope requirement: the caller who needs this answer is the one holding a token
    that cannot read `/state`, `/config` or `/logs`, so a named scope would refuse exactly that
    caller. The payload carries the same keys as the WebSocket `welcome` frame (`services/stream.py`),
    so a panel parses one shape whether the identity arrived over HTTP or the socket - `device` is
    the principal's name there, which is why it is spelled that way here.
    """
    principal = request[_PRINCIPAL]
    return web.json_response(
        {
            "device": principal.name,
            "scopes": sorted(principal.scopes),
            "kind": principal.kind,
        },
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------------- config
# `PATCH` and `POST /config/validate` share `_check_config_update`, so "would this be accepted" cannot
# drift from "was it accepted" (#406).


def _check_config_update(
    settings: dict[str, object], body: dict[str, object]
) -> tuple[list[tuple[str, str, dict[str, object], object]], list[str], list[dict[str, object]]]:
    """Split one config edit into what would land, what is not live, and what the schema refuses.

    One loop for both callers: `PATCH /api/v1/config` applies what this returns, and
    `POST /api/v1/config/validate` only answers with it, so "would this be accepted" cannot drift
    from "was it accepted" (#406).
    """
    pending: list[tuple[str, str, dict[str, object], object]] = []
    rejected: list[str] = []
    invalid: list[dict[str, object]] = []
    for key, value in body.items():
        dotted = str(key)
        if dotted not in LIVE_CONFIG_KEYS:
            rejected.append(dotted)
            continue
        section, _, leaf = dotted.partition(".")
        table = settings.get(section)
        if not isinstance(table, dict):
            rejected.append(dotted)
            continue
        # Shallow copy, so a reader on another thread never sees a half-applied table.
        updated = dict(table)
        updated[leaf] = value
        # The same specs the file is loaded against. Without this a client can store a string in a
        # numeric key, get a 200, and wedge the module that reads it on every tick afterwards (#123).
        problems = validate_settings_section(section, updated)
        if problems:
            invalid.append(
                {
                    "key": dotted,
                    "problems": [
                        {"path": problem.path, "message": problem.message, "hint": problem.hint}
                        for problem in problems
                    ],
                }
            )
            continue
        pending.append((dotted, section, updated, value))
    return pending, rejected, invalid


async def _config_get(request: web.Request) -> web.Response:
    plane = _plane(request)
    return web.json_response(
        {
            "config": redact_config(plane.context.get("settings") or {}),
            "live_keys": list(LIVE_CONFIG_KEYS),
        }
    )


async def _config_patch(request: web.Request) -> web.Response:
    plane = _plane(request)
    body = await _json_body(request)
    settings = plane.context.get("settings")
    if not isinstance(settings, dict):
        raise AuthError("unavailable", "no settings are loaded", status=503)

    # Validate everything before writing anything: a PATCH is one edit, and half of it landing is how
    # a client ends up unsure what the dog is running.
    pending, rejected, invalid = _check_config_update(settings, body)

    if invalid:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": "these values do not match the schema the config file is loaded against",
                "invalid": invalid,
                "live_keys": list(LIVE_CONFIG_KEYS),
                "persisted": False,
            },
            status=400,
        )

    if rejected:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": "these keys cannot be changed live",
                "rejected": rejected,
                "live_keys": list(LIVE_CONFIG_KEYS),
                "persisted": False,
            },
            status=400,
        )

    # Persist first (#174): a refused write has to leave the live table untouched, so the file and the
    # running process cannot end up disagreeing about what the dog is running. `persisted: false`
    # then means what it says - a runtime with no settings file (a `Config` built by hand) applies in
    # memory only, and the answer says so.
    persisted = False
    if plane.config_path is not None and pending:
        try:
            plane.persist_config(
                {dotted: value for dotted, _section, _updated, value in pending}
            )
        except ConfigWriteError as exc:
            return web.json_response(
                {
                    "error": "conflict",
                    "detail": exc.detail,
                    "applied": {},
                    "live_keys": list(LIVE_CONFIG_KEYS),
                    "persisted": False,
                },
                status=exc.status,
            )
        persisted = True

    applied: dict[str, object] = {}
    for dotted, section, updated, value in pending:
        settings[section] = updated
        applied[dotted] = value
    return web.json_response(
        {"applied": applied, "live_keys": list(LIVE_CONFIG_KEYS), "persisted": persisted}
    )


async def _config_validate(request: web.Request) -> web.Response:
    """Answer whether a config edit would be accepted, and write nothing (#406).

    The same body as `PATCH /api/v1/config`, run through the same loop and stopped before
    `persist_config`. `200` either way once settings are loaded: "these values would be refused" is
    the answer a client asked for, not a failure of the question. `would_apply` names what the PATCH
    would change, and `persisted` is always `false`.
    """
    plane = _plane(request)
    body = await _json_body(request)
    settings = plane.context.get("settings")
    if not isinstance(settings, dict):
        raise AuthError("unavailable", "no settings are loaded", status=503)

    pending, rejected, invalid = _check_config_update(settings, body)
    return web.json_response(
        {
            "ok": not rejected and not invalid,
            "would_apply": {dotted: value for dotted, _section, _updated, value in pending},
            "invalid": invalid,
            "rejected": rejected,
            "live_keys": list(LIVE_CONFIG_KEYS),
            "persisted": False,
        }
    )


# -------------------------------------------------------------------------------- sessions


async def _sessions(request: web.Request) -> web.Response:
    """Who is connected (#404).

    The registry already held this - key, name, scopes, seconds connected, commands - and the only
    way to read it was a support bundle. The key is a token fingerprint, never the token.
    """
    plane = _plane(request)
    return web.json_response(
        {"sessions": plane.sessions.active(), "limit": plane.sessions.max_clients}
    )


async def _session_delete(request: web.Request) -> web.Response:
    """Detach one connected client, by closing its socket (#404).

    A registry-only eviction would be a lie: the session would read `connected: false` while its
    socket kept receiving state. The hub closes the socket, the socket's own cleanup detaches the
    session, and the answer says how many connections were closed.
    """
    plane = _plane(request)
    key = str(request.match_info.get("key") or "").strip()
    if not key:
        return web.json_response(
            {"error": "bad_request", "detail": "a session key is required"}, status=400
        )
    closed = await plane.hub.close_session(key)
    if not closed:
        return web.json_response(
            {"error": "not_found", "detail": "no connected session with that key"}, status=404
        )
    return web.json_response({"key": key, "closed": closed})


# ---------------------------------------------------------------------------- calibration
# Read-only by contract: `CALIBRATION_REQUESTS` is an allow-list of *reads*, and a request outside
# it is refused before anything reaches the context. A calibration that moves servos is not on it,
# so `POST /calibration/run` cannot dispatch one (#17).


async def _calibration(request: web.Request) -> web.Response:
    """Read-only by contract. Writing offsets moves the dog; that is a device action."""
    plane = _plane(request)
    calibration = (plane.context.get("settings") or {}).get("calibration", {})
    calibration = calibration if isinstance(calibration, dict) else {}
    offsets = calibration.get("servo_zero_offsets", {})
    return web.json_response(
        {
            "servo_zero_offsets": offsets if isinstance(offsets, dict) else {},
            "auto_apply": bool(calibration.get("auto_apply_servo_offsets", False)),
            "writable": False,
            "detail": "calibration is applied on the device; this endpoint is read-only in v1",
        }
    )


async def _calibration_run(request: web.Request) -> web.Response:
    """Run one read-only calibration request and return what it measured (#17).

    This route exists to *not* be the footgun the contract reserved for. Calibration as it exists
    in this tree reads: servo trim (`hal.read_offsets`), the distance error against a wall-follow
    target, the best angle of the last scan, and the pose confidence. Nothing here writes an
    offset or publishes a motion intent, so there is nothing for a physical confirmation to
    confirm — and a prompt that guards nothing teaches the operator to approve it reflexively.

    The safety is structural rather than ceremonial: `CALIBRATION_REQUESTS` is an allow-list, and a
    request outside it is refused before anything is put on the context. A future calibration that
    does move servos must be a separate route with its own, deliberately designed arming step,
    because it will not dispatch through this one.
    """
    from houndmind_ai.services.api import (
        _CALIBRATION_ACK_TIMEOUT_S,
        CALIBRATION_REQUESTS,
    )

    plane = _plane(request)
    body = await _json_body(request)
    name = str(body.get("request") or "").strip()
    if name not in CALIBRATION_REQUESTS:
        return web.json_response(
            {
                "error": "unknown_request",
                "detail": f"'{name}' is not a calibration request this route runs",
                "requests": list(CALIBRATION_REQUESTS),
            },
            status=400,
        )

    # The id is what makes a second identical POST run again: `CalibrationModule` compares what it
    # was asked for, and it must not treat "read the trim again" as the same request it already
    # answered (#17).
    request_id = secrets.token_hex(4)
    plane.context.set("calibration_request", {"request": name, "id": request_id})

    # The loop ticks the module on its own thread at the configured rate, so this waits rather than
    # executing anything: polling keeps the event loop free for telemetry, which is the same reason
    # `_routine_run` waits on an executor.
    deadline = plane.now() + _CALIBRATION_ACK_TIMEOUT_S
    while plane.now() < deadline:
        result = plane.context.get("calibration_result")
        if isinstance(result, dict) and result.get("request_id") == request_id:
            return web.json_response(
                {"request": name, "request_id": request_id, "result": result}, status=202
            )
        await asyncio.sleep(0.02)
    return web.json_response(
        {
            "error": "unavailable",
            "detail": "no module answered the calibration request; is the runtime ticking?",
            "request_id": request_id,
        },
        status=503,
    )

