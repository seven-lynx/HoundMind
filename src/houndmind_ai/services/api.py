"""The `v1` control plane: one port, one authenticated API (D7).

`docs/CONTROL_API.md` is the contract and this module is the only implementation of it. Two
things are load-bearing:

- **Nothing here reaches hardware.** A command is a message on a
  :class:`~houndmind_ai.kernel.commands.CommandBus`; the gateway decides, the interlock judges,
  the HAL moves. The API never has a way to bypass that, which is what makes the phone and the
  web app exactly as safe as any other producer.
- **Every refusal is explained.** A veto, a missing scope, an unknown action, a mode that does
  not allow motion — each one answers with a code the client can show a human, because a dog
  that will not move for an unstated reason is indistinguishable from a broken one.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import zipfile
from collections.abc import Callable
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from aiohttp import web

from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.commands import (
    DEFAULT_MODE,
    KNOWN_ACTIONS,
    RUNTIME_MODES,
    Command,
    CommandBus,
    Source,
    Verdict,
    canonical_action,
)
from houndmind_ai.kernel.config_schema import Problem
from houndmind_ai.kernel.decisions import DecisionRing
from houndmind_ai.kernel.place_store import PlaceStore
from houndmind_ai.kernel.routine_store import StoreReport
from houndmind_ai.services.auth import (
    AuthError,
    Authorizer,
    MotionAudit,
    PairingWindow,
    Principal,
    RateLimiter,
    StreamTickets,
    TokenStore,
)
from houndmind_ai.services.camera import CameraService
from houndmind_ai.services.sessions import SessionRegistry
from houndmind_ai.services.settings import ApiSettings
from houndmind_ai.services.state import build_modules, build_state, redact_config
from houndmind_ai.services.stream import EventHub

logger = logging.getLogger(__name__)

API_VERSION = 1

__all__ = ["API_VERSION", "LIVE_CONFIG_KEYS", "ControlPlane", "create_app"]

# Keys a client may change live. Each one is re-read from `settings` every tick by its module,
# so a change takes effect immediately; everything else is refused rather than silently stored,
# because a config write that does nothing is how B-07 happened in the first place.
LIVE_CONFIG_KEYS: tuple[str, ...] = (
    "behavior.action_cooldown_s",
    "led.brightness",
    "motors.min_action_interval_s",
    "navigation.safe_distance_cm",
)

# The deadline for a command that does not carry one. The deadman is a safety feature; a client
# does not get to opt out of it by omitting the field.
_DEFAULT_TTL_MS = 300


class ControlPlane:
    """Everything the routes need, with no aiohttp app attached to it.

    Constructing this touches no socket and no token file: `ensure_token()` is what writes, and
    only `create_app()` + `start()` binds a port. That is what lets a test build a complete
    plane on a fake context and never leave loopback.
    """

    def __init__(
        self,
        context,
        settings: ApiSettings,
        bus: CommandBus,
        clock: Callable[[], float] | None = None,
        static_root: Path | None = None,
    ) -> None:
        self.context = context
        self.settings = settings
        self.bus = bus
        self._clock = clock or time.monotonic
        self.static_root = static_root or (Path(__file__).parent / "web")

        self.tokens = TokenStore(settings.token_path)
        self.pairing = PairingWindow(now=self._clock)
        self.authorizer = Authorizer(self.tokens, self.pairing, now=self._clock)
        self.sessions = SessionRegistry(now=self._clock, max_clients=settings.max_clients)
        # Camera tickets (`#18`): an `<img>` cannot send a header, and the device token must never
        # appear in a URL again.
        self.tickets = StreamTickets(now=self._clock)
        self.audit = MotionAudit()
        self.camera = CameraService(context)
        self.pairing_limiter = RateLimiter(
            settings.pairing_attempts_per_minute, 60.0, now=self._clock
        )
        self.command_limiter = RateLimiter(40, 1.0, now=self._clock)
        self._started_at = self._clock()
        self.hub = EventHub(
            authorizer=self.authorizer,
            sessions=self.sessions,
            snapshot=self.snapshot,
            state_hz=settings.state_hz,
            link_loss_s=settings.link_loss_s,
            on_link_loss=self._on_link_loss,
            clock=self._clock,
        )

    # ---- state -------------------------------------------------------------

    def ensure_token(self) -> None:
        """Create the token file on first start. The value is never returned or logged."""
        try:
            self.tokens.ensure()
        except OSError as exc:
            logger.warning("Could not create the API token at %s: %s", self.tokens.path, exc)

    def snapshot(self) -> dict[str, object]:
        return build_state(self.context, now=self._clock())

    def now(self) -> float:
        """The plane's monotonic clock. Routes stamp commands with it, so the deadman and the
        gateway agree even under a fake clock in a test."""
        return self._clock()

    def mode(self) -> str:
        mode = self.context.get("runtime_mode")
        return mode if isinstance(mode, str) and mode in RUNTIME_MODES else DEFAULT_MODE

    def set_mode(self, mode: str) -> str:
        self.context.set("runtime_mode", mode)
        return mode

    # ---- commands ----------------------------------------------------------

    async def submit(self, command: Command) -> Verdict | None:
        """Queue a command and wait for the gateway's verdict. None means it never arrived.

        The wait happens in an executor thread: `CommandBus.wait` blocks, and blocking the
        aiohttp event loop would freeze telemetry and pings for every other client for the
        length of the deadman.
        """
        if not self.bus.submit(command):
            return None
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.bus.wait, command.id, self.settings.command_ack_timeout_s
        )

    def stop_now(self, reason: str, source: Source = Source.SYSTEM) -> Command:
        """Stop, unconditionally. Every caller of this is a safety path, so nothing may fail."""
        command = Command(
            action="stop",
            source=source,
            params={"reason": reason},
            issued_at=self._clock(),
        )
        if not self.bus.submit(command):
            # The queue is full. Rather than drop a stop, force the mode the gateway refuses to
            # drive in: the next tick sees it and the dog settles.
            self.context.set("runtime_mode", "rest")
            logger.error("Command bus full; forced rest mode instead of dropping a stop")
        return command

    def _on_link_loss(self, session_key: str) -> None:
        self.stop_now(f"link loss from {session_key}")

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        await self.hub.start()

    async def stop(self) -> None:
        await self.hub.stop()

    # ---- meta --------------------------------------------------------------

    def meta(self) -> dict[str, object]:
        settings = self.context.get("settings") or {}
        device = settings.get("device", {}) if isinstance(settings, dict) else {}
        device = device if isinstance(device, dict) else {}
        # The board is a fact read from the device tree at boot; the profile is the decision
        # made from it. They can disagree — `HOUNDMIND_PROFILE` overrides the decision, not the
        # hardware — so both are reported and neither is inferred from the other.
        return {
            "api_version": API_VERSION,
            "min_client": 1,
            # What the client actually connected to. A phone that guessed wrong cannot tell a
            # wrong-scheme redirect from a wrong host otherwise.
            "scheme": "https" if self.settings.tls_enabled else "http",
            "device_id": self.context.get("device_id") or device.get("device_id"),
            "board": self.context.get("board"),
            "profile": self.context.get("profile"),
            "uptime_s": max(0.0, self._clock() - self._started_at),
            "capabilities": self._capabilities(),
        }

    def _capabilities(self) -> list[str]:
        capabilities = {"command", "events", "mode", "state"}
        frame, _ = self.camera.latest()
        if frame is not None:
            capabilities.add("camera")
        if self.pairing.active:
            capabilities.add("pairing")
        if self.context.get("routine_report") is not None:
            # Advertised only when a runner is loaded: a screen behind a 503 is worse than one
            # the client never shows.
            capabilities.add("routines")
        return sorted(capabilities)

    # ---- support bundle ----------------------------------------------------

    def support_bundle(self) -> bytes:
        """A zip a maintainer can read without asking a question first."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("meta.json", json.dumps(self.meta(), indent=2))
            archive.writestr("state.json", json.dumps(self.snapshot(), indent=2))
            archive.writestr("modules.json", json.dumps(build_modules(self.context), indent=2))
            archive.writestr(
                "config.json",
                json.dumps(redact_config(self.context.get("settings") or {}), indent=2),
            )
            archive.writestr("audit.json", json.dumps(self.audit.recent(200), indent=2))
            archive.writestr("sessions.json", json.dumps(self.sessions.active(), indent=2))
            archive.writestr(
                "README.txt",
                "HoundMind support bundle.\n"
                "meta/state/modules/config/audit/sessions are snapshots taken when the bundle\n"
                "was requested. config.json is redacted: no token or password is included.\n"
                "File logs are not here yet; `houndmind doctor` adds them (Phase 6).\n",
            )
        return buffer.getvalue()


# --------------------------------------------------------------------- helpers

# aiohttp's documented way to key an application/request mapping: a plain string key warns on
# every request, and a warning nobody reads is a warning that hides the next one.
_PLANE: web.AppKey[ControlPlane] = web.AppKey("plane", ControlPlane)
_PRINCIPAL: web.RequestKey[Any] = web.RequestKey("principal", object)


def _plane(request: web.Request) -> ControlPlane:
    return request.app[_PLANE]


@web.middleware
async def _errors(request: web.Request, handler):
    """Turn every failure into the contract's `{error, detail}` envelope.

    A stack trace in a response body is a leak; a 500 with no explanation is a support ticket.
    The detail here is written to be shown to a human verbatim.
    """
    try:
        return await handler(request)
    except AuthError as exc:
        return web.json_response({"error": exc.code, "detail": exc.detail}, status=exc.status)
    except web.HTTPException:
        raise
    except Exception:  # noqa: BLE001 - the contract has a code for this
        logger.exception("Unhandled error serving %s %s", request.method, request.path)
        return web.json_response(
            {"error": "internal", "detail": "the device hit an internal error; see /logs"},
            status=500,
        )


def _authed(scope: str):
    """Require a valid token and a scope. Applied at route-registration time."""

    def decorate(handler):
        async def wrapped(request: web.Request):
            plane = _plane(request)
            principal = plane.authorizer.authenticate(request.headers.get("Authorization"))
            plane.authorizer.require(principal, scope)
            request[_PRINCIPAL] = principal
            return await handler(request)

        wrapped.__name__ = getattr(handler, "__name__", "handler")
        return wrapped

    return decorate


def _camera_principal(plane: ControlPlane, request: web.Request) -> Principal:
    """`<img>` cannot send a header, so the camera accepts a ticket — and nothing else.

    The query string used to carry the **device token**, which is the one credential that must never
    reach a log: it appeared in browser history, the access log and any proxy in the path, and it
    grants `move` and `config` to whoever reads it. `POST /api/v1/camera/ticket` replaces it with a
    value that lasts a minute, works once, and buys exactly `state:read` on one frame (`#18`).

    A ticket is spent here even if the frame is then refused for want of a producer: the alternative
    is a ticket that survives its own use.
    """
    header = request.headers.get("Authorization")
    if header:
        principal = plane.authorizer.authenticate(header)
    elif plane.tickets.claim(request.query.get("ticket")):
        principal = Principal(name="camera", scopes=frozenset({"state:read"}), kind="camera")
    elif request.query.get("token"):
        raise AuthError(
            "unauthorized",
            "the camera routes do not accept ?token= any more; mint one with "
            "POST /api/v1/camera/ticket and pass ?ticket=",
        )
    else:
        raise AuthError(
            "unauthorized",
            "missing camera ticket; mint one with POST /api/v1/camera/ticket",
        )
    plane.authorizer.require(principal, "state:read")
    return principal


async def _camera_ticket(request: web.Request) -> web.Response:
    """Mint a single-use ticket for the two camera routes.

    `state:read` is required to ask for one, and it is all the ticket grants: a ticket cannot be
    escalated into `move` or `config`, which is the reason it is not simply a second token.
    """
    plane = _plane(request)
    ticket, expires_in = plane.tickets.issue()
    return web.json_response(
        {"ticket": ticket, "expires_in": expires_in},
        headers={"Cache-Control": "no-store"},
    )


def _parse_json_body(raw: str) -> dict[str, object]:
    """A JSON object or `AuthError(400)` — the one wording every POST body is judged by."""
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise AuthError("bad_request", "body must be JSON", status=400) from exc
    if not isinstance(payload, dict):
        raise AuthError("bad_request", "body must be a JSON object", status=400)
    return payload


async def _json_body(request: web.Request) -> dict[str, object]:
    return _parse_json_body(await request.text())


async def _optional_json_body(request: web.Request) -> dict[str, object]:
    """A POST body that may be absent, read as `{}`.

    `POST /command` and `POST /mode` are meaningless without their fields, but
    `POST /routines/{id}/run` has none: a client that sends nothing means "run it, not dry".
    Absent is not malformed, so it gets the same parser rather than a second set of rules.
    """
    if not request.can_read_body:
        return {}
    raw = await request.text()
    return _parse_json_body(raw) if raw.strip() else {}


# --------------------------------------------------------------------- routes


async def _meta(request: web.Request) -> web.Response:
    return web.json_response(_plane(request).meta())


async def _health(request: web.Request) -> web.Response:
    # Liveness only. No detail: this route is unauthenticated by design.
    return web.json_response({"status": "ok"})


async def _state(request: web.Request) -> web.Response:
    return web.json_response(_plane(request).snapshot())


async def _modules(request: web.Request) -> web.Response:
    return web.json_response(build_modules(_plane(request).context))


async def _events(request: web.Request) -> web.StreamResponse:
    return await _plane(request).hub.handle(request)


async def _camera_stream(request: web.Request) -> web.StreamResponse:
    plane = _plane(request)
    _camera_principal(plane, request)
    return await plane.camera.stream(request)


async def _camera_snapshot(request: web.Request) -> web.Response:
    plane = _plane(request)
    _camera_principal(plane, request)
    return await plane.camera.snapshot(request)


async def _pair(request: web.Request) -> web.Response:
    plane = _plane(request)
    peer = request.remote or "unknown"
    if not plane.pairing_limiter.allow(peer):
        raise AuthError(
            "rate_limited",
            "too many pairing attempts; wait a minute",
            status=429,
        )
    if not plane.settings.pairing_enabled:
        raise AuthError("unavailable", "pairing is disabled in settings.api", status=503)
    body = await _json_body(request)
    code = str(body.get("code") or "")
    name = str(body.get("client_name") or "client")
    if not plane.pairing.claim(code):
        # One message for "wrong code" and "no window open": a probe learns nothing.
        raise AuthError("unauthorized", "no pairing window is open for that code")
    token, principal = plane.authorizer.issue_client_token(name)
    plane.hub.publish_event("pairing_window_open", {"client": principal.name})
    # This is the only response that carries a token, and it is not logged anywhere.
    return web.json_response(
        {"device_token": token, "scopes": sorted(principal.scopes), "name": principal.name}
    )


async def _pair_open(request: web.Request) -> web.Response:
    """Open a pairing window and return the code.

    There is no screen on a headless Pi, so the operator's browser *is* the dashboard the code
    is shown on. Only a holder of the device token (`admin`) can open a window, and the code is
    returned once, never logged, and dies after the window closes.
    """
    plane = _plane(request)
    if not plane.settings.pairing_enabled:
        raise AuthError("unavailable", "pairing is disabled in settings.api", status=503)
    code = plane.pairing.open()
    plane.hub.publish_event("pairing_window_open", {"opened": True})
    logger.info("Pairing window opened by %s", request[_PRINCIPAL].name)
    return web.json_response({"code": code, "expires_in_s": 300})


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
    plane.hub.publish_event("command_accepted", {"action": "stop"})
    return web.json_response({"accepted": True, "action": "stop"}, status=202)


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


# ----------------------------------------------------------------- routines
#
# A routine is playable state, not a command: `POST /routines/{id}/run` writes one request key and
# `behavior/routine_runner.py` turns it into a step per tick. Both handlers read the *runner's*
# report rather than the directory, because two readers of one directory are two answers to "which
# routines exist" — and the dog can only play the ones it loaded.


def _problem_dict(problem: Problem) -> dict[str, object]:
    """One refused file's reason, in the shape `Problem` already has."""
    return {"path": problem.path, "message": problem.message, "hint": problem.hint}


def _routine_state(plane: ControlPlane) -> dict[str, object] | None:
    """The run in progress, as the runner serialises it (`RoutineRun.to_dict`).

    Duck-typed on purpose: `services` may not import `behavior` (the API would then own the
    runner's shape), so this republishes the dict the runner built instead of rebuilding one.
    """
    run = plane.context.get("routine_run")
    to_dict = getattr(run, "to_dict", None)
    return to_dict() if callable(to_dict) else None


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

    plane.context.set("routine_request", {"id": routine.id, "dry_run": dry_run})
    return web.json_response(
        {"accepted": True, "id": routine.id, "dry_run": dry_run, "steps": len(routine.steps)},
        status=202,
    )


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


def _number(value: object) -> float | None:
    """A JSON number, or `None`. `bool` is an `int` in Python, so `true` would arrive as 1.0.

    The same trap `POST /routines/{id}/run` closes for `dry_run`, where the *string* `"false"` is
    truthy and would start a real run for a client that asked for a rehearsal.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _place_not_found(store: PlaceStore, wanted: str, detail: str) -> web.Response:
    matches = get_close_matches(wanted, list(store.load().ids()), n=1)
    return web.json_response(
        {"error": "not_found", "detail": detail, "suggestion": matches[0] if matches else None},
        status=404,
    )


async def _places_list(request: web.Request) -> web.Response:
    """The catalogue, whatever the file refused, and the walk in progress."""
    plane = _plane(request)
    store = _place_store(plane)
    if store is None:
        return _no_places()
    report = store.load()
    return web.json_response(
        {
            "path": str(report.path),
            "places": [place.to_dict() for place in report.places],
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


async def _place_delete(request: web.Request) -> web.Response:
    """Forget one place. A second call is a 404, never a silent success (P4 PL6)."""
    plane = _plane(request)
    store = _place_store(plane)
    if store is None:
        return _no_places()
    wanted = str(request.match_info.get("id") or "").strip()
    removed, problems = store.remove(wanted)
    if removed is None:
        detail = problems[0].message if problems else f"no place with id or name {wanted!r}"
        return _place_not_found(store, wanted, detail)
    return web.json_response({"removed": removed.to_dict(), "path": str(store.path)})


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


def _header_token(request: web.Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


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

    applied: dict[str, object] = {}
    rejected: list[str] = []
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
        settings[section] = updated
        applied[dotted] = value

    if rejected:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": "these keys cannot be changed live",
                "rejected": rejected,
                "live_keys": list(LIVE_CONFIG_KEYS),
            },
            status=400,
        )
    return web.json_response({"applied": applied, "live_keys": list(LIVE_CONFIG_KEYS)})


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


async def _history(request: web.Request) -> web.Response:
    limit = request.query.get("limit", "50")
    try:
        count = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        raise AuthError("bad_request", "limit must be an integer", status=400) from None
    plane = _plane(request)
    return web.json_response(
        {"commands": plane.audit.recent(count), "sessions": plane.sessions.active()}
    )


async def _decisions(request: web.Request) -> web.Response:
    """The decision feed: one record per tick, oldest first (§4.2 of the design).

    A missing ring answers 503 rather than an empty list. `modules.decision_log.enabled: false` and
    "the dog has not decided anything yet" would otherwise look identical, and only one of them is
    worth a bug report.
    """
    limit = request.query.get("limit", "50")
    try:
        count = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        raise AuthError("bad_request", "limit must be an integer", status=400) from None
    ring = _plane(request).context.get("decision_ring")
    if not isinstance(ring, DecisionRing):
        return web.json_response(
            {
                "error": "unavailable",
                "detail": "the decision feed is not running; enable modules.decision_log",
            },
            status=503,
        )
    records = ring.recent(count)
    return web.json_response(
        {"decisions": [record.to_dict() for record in records], "count": len(records)}
    )


async def _logs(request: web.Request) -> web.Response:
    plane = _plane(request)
    tail = request.query.get("tail")
    try:
        count = max(1, min(int(tail), plane.settings.log_tail)) if tail else plane.settings.log_tail
    except (TypeError, ValueError):
        raise AuthError("bad_request", "tail must be an integer", status=400) from None
    lines = _tail_lines(plane, count)
    if lines is None:
        return web.json_response(
            {
                "error": "unavailable",
                "detail": "no log file is configured; set settings.logging.enable_file",
            },
            status=503,
        )
    return web.json_response({"lines": lines})


def _tail_lines(plane: ControlPlane, count: int) -> list[str] | None:
    """Read the last `count` lines without loading the file. None means "no file configured"."""
    settings = plane.context.get("settings") or {}
    logging_settings = settings.get("logging", {}) if isinstance(settings, dict) else {}
    logging_settings = logging_settings if isinstance(logging_settings, dict) else {}
    if not logging_settings.get("enable_file", True):
        return None
    name = logging_settings.get("log_file_name") or "logs/houndmind.log"
    path = Path(str(name))
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    try:
        with path.open("rb") as handle:
            handle.seek(0, io.SEEK_END)
            size = handle.tell()
            # 64 KiB is enough for a few thousand lines and bounded regardless of file size.
            handle.seek(max(0, size - 65536))
            chunk = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    return chunk.splitlines()[-count:]


async def _support_bundle(request: web.Request) -> web.Response:
    plane = _plane(request)
    body = plane.support_bundle()
    return web.Response(
        body=body,
        content_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="houndmind-support.zip"'},
    )


async def _index(request: web.Request) -> web.StreamResponse:
    index = _plane(request).static_root / "index.html"
    if not index.is_file():
        return web.json_response(
            {"error": "not_found", "detail": "the web app is not bundled with this build"},
            status=404,
        )
    return web.FileResponse(index)


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
            }
        )
    people = roster.get("people")
    return web.json_response(
        {
            "identity": {"enabled": True, "backend": roster.get("backend"), "reason": None},
            "path": roster.get("path"),
            "people": people if isinstance(people, list) else [],
        }
    )


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


# ------------------------------------------------------------------ the table
#
# One declaration, used both to register the routes and to check them against
# `docs/CONTROL_API.md` in `tests/test_api_routes.py`. A route that exists in code and not in
# the contract is how two clients drift apart.
#
# `scope=None` means "no bearer token": `/meta` and `/health` are the liveness surface, and the
# WebSocket authenticates inside its own `hello` frame because a browser cannot set a header on
# a WebSocket handshake.
ROUTES: tuple[tuple[str, str, str | None, Any], ...] = (
    ("GET", "/meta", None, _meta),
    ("GET", "/health", None, _health),
    ("GET", "/state", "state:read", _state),
    ("GET", "/modules", "state:read", _modules),
    ("GET", "/repertoire", "state:read", _repertoire),
    ("GET", "/routines", "state:read", _routines_list),
    ("GET", "/places", "state:read", _places_list),
    ("GET", "/people", "admin", _people_list),
    ("GET", "/decisions", "state:read", _decisions),
    ("GET", "/events", None, _events),
    ("GET", "/camera/stream", None, _camera_stream),
    ("GET", "/camera/snapshot", None, _camera_snapshot),
    ("POST", "/camera/ticket", "state:read", _camera_ticket),
    ("POST", "/pair", None, _pair),
    ("POST", "/pair/open", "admin", _pair_open),
    ("POST", "/command", "move", _command),
    ("POST", "/stop", "move", _stop),
    ("POST", "/routines/{id}/run", "move", _routine_run),
    ("POST", "/places", "config", _places_create),
    ("DELETE", "/places/{id}", "config", _place_delete),
    ("DELETE", "/people/{id}", "admin", _people_delete),
    ("POST", "/places/{id}/go", "move", _place_go),
    ("GET", "/mode", "state:read", _mode_get),
    ("POST", "/mode", "move", _mode_post),
    ("GET", "/config", "config", _config_get),
    ("PATCH", "/config", "config", _config_patch),
    ("GET", "/calibration", "config", _calibration),
    ("GET", "/history", "state:read", _history),
    ("GET", "/logs", "admin", _logs),
    ("GET", "/support-bundle", "admin", _support_bundle),
)

API_PREFIX = "/api/v1"


def create_app(plane: ControlPlane) -> web.Application:
    """Build the aiohttp application. Binding a port is the caller's job (`ControlPlaneModule`)."""
    app = web.Application(middlewares=[_errors], client_max_size=64 * 1024)
    app[_PLANE] = plane
    router = app.router

    for method, path, scope, handler in ROUTES:
        router.add_route(method, f"{API_PREFIX}{path}", _authed(scope)(handler) if scope else handler)

    router.add_get("/", _index)
    if plane.static_root.is_dir():
        # `add_static` refuses to serve outside the directory it was given, so the web app
        # cannot be used to read `/etc/shadow` by asking for `../../etc/shadow`.
        router.add_static("/static/", plane.static_root, show_index=False)

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


async def _on_startup(app: web.Application) -> None:
    plane = app[_PLANE]
    plane.ensure_token()
    await plane.start()


async def _on_cleanup(app: web.Application) -> None:
    plane = app[_PLANE]
    await plane.stop()