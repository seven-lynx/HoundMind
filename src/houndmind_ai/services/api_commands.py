"""The command surface, split out of `services/api.py` (AP5).

Everything that asks the dog to do something, and the two reads that describe what it may be asked:
`POST /command` and `POST /stop` (the escape hatch), `GET|POST /mode` (the driver of the gateway's
`runtime_mode`), `GET /repertoire` (the catalogue a client renders its buttons from) and the
allow-list helpers those two routes share.

**None of this moves hardware.** `_command` builds a :class:`~houndmind_ai.kernel.commands.Command`
and awaits `plane.submit()`, which posts it to the decision loop; `act/gateway.py` decides whether it
becomes a motion intent and the interlock judges it. The refusal envelopes below exist so a veto is
explained rather than silent, which is the whole of this module's contract.

**`_header_token` lives here because `_command` is its only caller.** It parsed the bearer token out
of the header to record which session issued a command; AP4 left it behind for exactly this segment
so the two could move together.
"""

from __future__ import annotations

import logging
from difflib import get_close_matches
from typing import TYPE_CHECKING

from aiohttp import web

from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.commands import (
    KNOWN_ACTIONS,
    RUNTIME_MODES,
    Command,
    Source,
    canonical_action,
)
from houndmind_ai.services.http import _PRINCIPAL, _json_body, _plane

if TYPE_CHECKING:
    from houndmind_ai.services.api import ControlPlane

logger = logging.getLogger(__name__)

# The deadline for a command that does not carry one. The deadman is a safety feature; a client
# does not get to opt out of it by omitting the field.
_DEFAULT_TTL_MS = 300


async def _command(request: web.Request) -> web.Response:
    plane = _plane(request)
    principal = request[_PRINCIPAL]
    if not plane.command_limiter.allow(principal.name):
        return web.json_response(
            {"error": "rate_limited", "detail": "too many commands; slow down"},
            status=429,
            headers={"Retry-After": "1"},
        )
    body = await _json_body(request)

    action = canonical_action(str(body.get("action") or ""))
    allowed = _allowed_actions(plane)
    if action not in allowed:
        return web.json_response(
            {
                "error": "unknown_action",
                "detail": f"'{action}' is not in the action catalog",
                "suggestion": _suggest_action(action, allowed),
            },
            status=400,
        )

    params = body.get("params")
    params = params if isinstance(params, dict) else {}
    ttl = body.get("ttl_ms")
    ttl_ms = _DEFAULT_TTL_MS
    if isinstance(ttl, int) and not isinstance(ttl, bool) and ttl > 0:
        ttl_ms = min(ttl, 5000)

    command = Command(
        action=action,
        source=Source.CLIENT,
        params=params,
        ttl_ms=ttl_ms,
        # The deadman starts when the device received the command, not when the phone queued
        # it. A command that sat in a tunnel must not run when it finally arrives.
        issued_at=plane.now(),
    )
    command_id = str(body.get("id") or command.id)
    verdict = await plane.submit(command)
    if verdict is None:
        # The decision loop never answered: the dog cannot be driven right now.
        return web.json_response(
            {
                "error": "unavailable",
                "detail": "no module answered the command; is the runtime ticking?",
                "id": command_id,
            },
            status=503,
        )
    plane.audit.record(command, verdict, principal)
    plane.sessions.record_command(_header_token(request))

    if not verdict.accepted:
        plane.hub.publish_event(
            "command_vetoed",
            {"id": command_id, "veto": verdict.veto, "detail": verdict.detail},
        )
        return web.json_response(
            {
                "accepted": False,
                "id": command_id,
                "veto": verdict.veto,
                "detail": verdict.detail,
                "retry_after_ms": verdict.retry_after_ms,
            },
            status=409,
        )
    plane.hub.publish_event("command_accepted", {"id": command_id, "action": action})
    return web.json_response(
        {
            "accepted": True,
            "id": command_id,
            "action": action,
            "expires_at": round(command.deadline(), 3),
        },
        status=202,
    )


async def _stop(request: web.Request) -> web.Response:
    plane = _plane(request)
    # Not vetoable and not queued behind anything: this is the escape hatch in the contract.
    plane.stop_now("client stop", Source.SYSTEM)
    # A running routine publishes its next step on the following tick, so a stop that only
    # reached the actuators would be undone 200 ms later. The runner consumes this key and ends
    # the run as `stopped` (behavior/routine_runner.py::_advance). Only when a runner is loaded:
    # otherwise the flag would outlive the stop and kill the next run instead.
    if plane.context.get("routine_report") is not None:
        plane.context.set("routine_stop", True)
    # And the stop has to *park*, not just clear the motion in flight (#333). In `idle` the
    # behaviour and the navigator publish a fresh intent about 100 ms later, so the operator's
    # panic press was a stop autonomy overwrote on the next tick. `rest` is the mode the gateway
    # refuses to drive in, and any client may set another mode, so the brake and the throttle stay
    # one control. A pad release does not come through here: it issues a `stop` command
    # (`panels/drive.js::stopMotion`), which is a motion stop with no mode change.
    if plane.mode() != "rest":
        plane.set_mode("rest")
        plane.hub.publish_event("mode_changed", {"mode": "rest"})
    plane.hub.publish_event("command_accepted", {"action": "stop"})
    return web.json_response(
        {"accepted": True, "action": "stop", "mode": plane.mode()}, status=202
    )


async def _mode_get(request: web.Request) -> web.Response:
    return web.json_response({"mode": _plane(request).mode()})


async def _mode_post(request: web.Request) -> web.Response:
    plane = _plane(request)
    body = await _json_body(request)
    mode = str(body.get("mode") or "").strip().lower()
    if mode not in RUNTIME_MODES:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": f"mode must be one of {', '.join(RUNTIME_MODES)}",
            },
            status=400,
        )
    plane.set_mode(mode)
    plane.hub.publish_event("mode_changed", {"mode": mode})
    return web.json_response({"mode": mode})


async def _repertoire(request: web.Request) -> web.Response:
    """Every action this dog can actually run, with its class and the params it reads.

    Two sources, because neither is complete alone: the classification the runtime loaded
    (`config/actions.jsonc`) and the action list the HAL reports. A name the HAL has and the
    catalog does not is answered with `class: null` — the dog can do it, nothing has said what kind
    of thing it is, and `null` is the honest answer (`services/state.py` makes the same rule for a
    sensor that could not be read).
    """
    plane = _plane(request)
    repertoire = repertoire_from_settings(plane.context.get("settings"))
    hal = plane.context.get("hal")
    hal_actions: frozenset[str] = frozenset()
    if hal is not None:
        try:
            hal_actions = frozenset(canonical_action(name) for name in hal.actions())
        except Exception:  # noqa: BLE001 - a read-only route must not fail on a broken HAL
            logger.debug("HAL action list unavailable", exc_info=True)

    actions: list[dict[str, object]] = []
    for name in sorted(repertoire.known() | hal_actions):
        spec = repertoire.spec(name)
        if spec is None:
            # The HAL can do it; nothing has classified it. `null`, never a guessed class.
            actions.append({"name": name, "class": None, "params": []})
        else:
            actions.append(spec.to_dict())
    return web.json_response({"actions": actions, "count": len(actions)})


def _allowed_actions(plane: ControlPlane) -> frozenset[str]:
    """Every action a client may name: the built-in vocabulary plus the loaded classification.

    The classification is data in `config/actions.jsonc`, so an action a user adds there can be
    commanded without a code change. A name nothing classifies is refused here, with a suggestion,
    rather than queued and then vetoed by the interlock — the client gets the same explanation
    either way, one round trip earlier.
    """
    repertoire = repertoire_from_settings(plane.context.get("settings"))
    return frozenset(KNOWN_ACTIONS) | repertoire.known()


def _suggest_action(action: str, allowed: frozenset[str]) -> str | None:
    matches = get_close_matches(action, sorted(allowed), n=1)
    return matches[0] if matches else None


def _header_token(request: web.Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None
