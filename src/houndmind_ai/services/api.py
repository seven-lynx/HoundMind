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

from houndmind_ai.kernel.commands import (
    DEFAULT_MODE,
    KNOWN_ACTIONS,
    RUNTIME_MODES,
    Command,
    CommandBus,
    Source,
    Verdict,
)
from houndmind_ai.services.auth import (
    AuthError,
    Authorizer,
    MotionAudit,
    PairingWindow,
    RateLimiter,
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
        return {
            "api_version": API_VERSION,
            "min_client": 1,
            "device_id": device.get("device_id"),
            "board": device.get("board"),
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


def _camera_principal(plane: ControlPlane, request: web.Request):
    """`<img>` cannot send a header, so the camera accepts `?token=` and nothing else does."""
    header = request.headers.get("Authorization")
    token = None
    if header:
        principal = plane.authorizer.authenticate(header)
    else:
        token = request.query.get("token")
        principal = plane.authorizer.authenticate_token(token)
    plane.authorizer.require(principal, "state:read")
    return principal


async def _json_body(request: web.Request) -> dict[str, object]:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise AuthError("bad_request", "body must be JSON", status=400) from exc
    if not isinstance(payload, dict):
        raise AuthError("bad_request", "body must be a JSON object", status=400)
    return payload


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

    action = str(body.get("action") or "").strip().lower().replace(" ", "_")
    if action not in KNOWN_ACTIONS:
        return web.json_response(
            {
                "error": "unknown_action",
                "detail": f"'{action}' is not in the action catalog",
                "suggestion": _suggest_action(action),
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


def _suggest_action(action: str) -> str | None:
    matches = get_close_matches(action, sorted(KNOWN_ACTIONS), n=1)
    return matches[0] if matches else None


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
    ("GET", "/events", None, _events),
    ("GET", "/camera/stream", None, _camera_stream),
    ("GET", "/camera/snapshot", None, _camera_snapshot),
    ("POST", "/pair", None, _pair),
    ("POST", "/pair/open", "admin", _pair_open),
    ("POST", "/command", "move", _command),
    ("POST", "/stop", "move", _stop),
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