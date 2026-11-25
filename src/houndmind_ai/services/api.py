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
import secrets
import threading
import time
import zipfile
from collections.abc import Callable
from difflib import get_close_matches
from importlib import metadata
from pathlib import Path

from aiohttp import web

from houndmind_ai.core.logging_setup import log_file_path
from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.commands import (
    AUTONOMY_SOURCES,
    DEFAULT_MODE,
    KNOWN_ACTIONS,
    RUNTIME_MODES,
    Command,
    CommandBus,
    Source,
    Verdict,
    canonical_action,
)
from houndmind_ai.kernel.decisions import DecisionRing
from houndmind_ai.kernel.routine_store import RoutineConflict, RoutineStore, StoreReport

# Kept, and imported here only, so `houndmind_ai.services.api.view_from_frame` stays the object
# `tests/test_api_places.py:474/573/601` patches: `api_people._places_teach` resolves the name
# through this module's globals on every call, the same way `api_camera` reaches `_camera_principal`.
from houndmind_ai.perception.place_views import view_from_frame  # noqa: F401
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
from houndmind_ai.services.config_writer import (
    ConfigWriteError,
    stamp_of,
    write_settings_values,
)
from houndmind_ai.services.http import (
    _CORS_ALLOW_METHODS,  # noqa: F401 - re-exported; tests/test_map_routes.py:370 reads it here
    _PRINCIPAL,
    _json_body,
    _optional_json_body,
    _plane,
    _problem_dict,
)
from houndmind_ai.services.sessions import SessionRegistry
from houndmind_ai.services.settings import ApiSettings
from houndmind_ai.services.state import build_modules, build_state, redact_config
from houndmind_ai.services.stream import EventHub, LogTail

logger = logging.getLogger(__name__)

API_VERSION = 1

__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "ANY_SCOPE",
    "HANDLER_SCOPE",
    "LIVE_CONFIG_KEYS",
    "ROUTES",
    "ControlPlane",
    "create_app",
]

# Re-exported, not repeated: the allow-list belongs with the routes that enforce it (`api_admin.py`,
# AP4), and it is still named by `__all__` and by `docs/CONTROL_API.md:229`. AP5 greps these
# transition re-exports out once the last handler has moved (Q1). `E402` is the point of the line.
from houndmind_ai.services.api_admin import LIVE_CONFIG_KEYS  # noqa: E402, F401

# The deadline for a command that does not carry one. The deadman is a safety feature; a client
# does not get to opt out of it by omitting the field.
_DEFAULT_TTL_MS = 300

# How long a routine start waits for the runner's answer. The runner reads the request on the
# decision thread, at the loop rate (200 ms at the shipped 5 Hz), so half a second is two ticks -
# enough for the normal case and short enough that a plane with no runner in it answers promptly.
# A timeout is not a refusal: the request is still queued, and the POST keeps its old `202`.
_ROUTINE_ACK_TIMEOUT_S = 0.5

# The calibration requests this route will run. Every one of them reads: servo trim, a distance
# error, a scan angle, a pose confidence. The list is the safety property - a calibration that
# moves servos is not on it, so `POST /calibration/run` cannot dispatch one (#17).
CALIBRATION_REQUESTS: tuple[str, ...] = (
    "servo_zero",
    "wall_follow",
    "corner_seek",
    "landmark_align",
)

# How long a run waits for the module's answer. The loop ticks at 5 Hz, so this is five ticks -
# enough for a HAL read on a slow card, short enough that a plane with no calibration module in it
# answers with a `503` instead of hanging.
_CALIBRATION_ACK_TIMEOUT_S = 1.0


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
            # The live log channel (#170). Injected so the hub stays a pure fan-out: it reads no
            # settings and opens no files of its own.
            log_lines=LogTail(self.context).read_new,
            state_hz=settings.state_hz,
            link_loss_s=settings.link_loss_s,
            on_link_loss=self._on_link_loss,
            clock=self._clock,
        )
        # #174: the settings file the runtime read, and its stamp when this plane came up. A `Config`
        # built by hand carries no path, so `PATCH /config` then answers `persisted: false` instead of
        # inventing a file to write.
        config = self.context.get("config")
        self._config_path: Path | None = getattr(config, "path", None)
        self._config_stamp = stamp_of(self._config_path)

    # ---- state -------------------------------------------------------------

    @property
    def config_path(self) -> Path | None:
        """The `settings.jsonc` this runtime read, when there was one."""
        return self._config_path

    def persist_config(self, updates: dict[str, object]) -> None:
        """Write live keys into the settings file, or raise `ConfigWriteError` (#174).

        The stamp is the file's state when this process last read or wrote it, so an edit made on the
        device after boot is refused rather than overwritten (G1).
        """
        if self._config_path is None:
            raise ConfigWriteError("the runtime has no settings file to write to", status=409)
        self._config_stamp = write_settings_values(
            self._config_path, updates, expected_stamp=self._config_stamp
        )

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
        """Switch the runtime mode, and drop every autonomy intent the old one left standing.

        `MODE_ALLOWED_SOURCES` decides whether a *new* intent is admitted; it says nothing about one
        that is already published, so without this a hand on the wheel keeps a behaviour or navigation
        intent live until it expires — a stale slot a client command then has to outrank (#270).
        """
        previous = self.mode()
        self.context.set("runtime_mode", mode)
        if previous != mode:
            self._retract_autonomy()
        return mode

    def _retract_autonomy(self) -> None:
        """Withdraw every autonomy slot now. The client's request and the watchdog's hold stay."""
        board = self.context.get("intent_board")
        if board is None:
            return
        for source in AUTONOMY_SOURCES:
            board.retract(source)

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
            # And withdraw what autonomy was asking for, for the same reason `set_mode` does: a stop
            # that leaves a live intent behind is a stop a later tick can be talked out of.
            self._retract_autonomy()
            logger.error("Command bus full; forced rest mode instead of dropping a stop")
        return command

    def _on_link_loss(self, session_key: str) -> None:
        """A client that stopped pinging loses its command *and* the mode that would resume it.

        The same brake as `POST /stop` (#337): under `idle` the behaviour and the navigator
        publish a fresh intent about 100 ms later, so a stop that only reached the actuators was
        undone on the next tick. `rest` is the mode the gateway refuses to drive in, so the dog
        stays parked while nobody is holding the leash. `command_expired` is the hub's to publish:
        this path raises no `command_accepted`, because no client asked for anything.
        """
        self.stop_now(f"link loss from {session_key}")
        # A running routine publishes its next step on the following tick, exactly as it does for
        # `POST /stop`; only when a runner is loaded, so the flag cannot outlive the stop.
        if self.context.get("routine_report") is not None:
            self.context.set("routine_stop", True)
        if self.mode() != "rest":
            self.set_mode("rest")
            self.hub.publish_event("mode_changed", {"mode": "rest"})

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
            # The device tree's own words, verbatim. A `board` of `unknown` says the detection
            # failed and nothing more, so this is the only way a support bundle can show what the
            # hardware actually called itself (#32).
            "board_model": self.context.get("board_model"),
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
                "File logs are not in this bundle. For them, read GET /api/v1/logs (scope\n"
                "admin), or run `python -m tools.collect_support_bundle` on the device, which\n"
                "zips logs/ alongside the files it collects.\n",
            )
        return buffer.getvalue()


# --------------------------------------------------------------- camera auth (#18)

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


# --------------------------------------------------------------------- routes


async def _state(request: web.Request) -> web.Response:
    return web.json_response(_plane(request).snapshot())


async def _scan(request: web.Request) -> web.Response:
    """The last head sweep, verbatim (#169).

    A dedicated read rather than a field of the snapshot: a sweep holds one bearing per angle, and
    the snapshot is sent at `api.state_hz` to every client. `state.scan` carries the summary (mode,
    timestamp, sample count), so a client fetches this only when the scan actually changed.

    `{"scan": null}` before the first scan, and `200` either way: "no scan yet" is an answer, not a
    failure, and the scanner being disabled is visible in `/modules`.
    """
    latest = _plane(request).context.get("scan_latest")
    return web.json_response(
        {"scan": latest if isinstance(latest, dict) else None},
        headers={"Cache-Control": "no-store"},
    )


async def _modules(request: web.Request) -> web.Response:
    return web.json_response(build_modules(_plane(request).context))


async def _events(request: web.Request) -> web.StreamResponse:
    return await _plane(request).hub.handle(request)


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


# ----------------------------------------------------------------- routines
#
# A routine is playable state, not a command: `POST /routines/{id}/run` writes one request key and
# `behavior/routine_runner.py` turns it into a step per tick. Both handlers read the *runner's*
# report rather than the directory, because two readers of one directory are two answers to "which
# routines exist" — and the dog can only play the ones it loaded.


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


# `_header_token` stays here: its only caller is `_command`, and AP5b moves the two together.
# for it, so a handler that moves now cannot take it along.
def _header_token(request: web.Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


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


# The level names `core/logging_setup.py::JsonFormatter` writes, and the whole accepted set for the
# `level` query parameter: an unknown one is a 400 rather than a silent "no lines match", because
# "your filter is misspelled" and "nothing matched" are different answers (#171).
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LOG_CHUNK = 64 * 1024
# A filtered read walks back further than the unfiltered tail, but the work has to be bounded: 4 MiB
# is hours of this runtime's log and still one comfortable read on a Pi's SD card.
_FILTER_BUDGET = 4 * 1024 * 1024


async def _logs(request: web.Request) -> web.Response:
    plane = _plane(request)
    tail = request.query.get("tail")
    try:
        count = max(1, min(int(tail), plane.settings.log_tail)) if tail else plane.settings.log_tail
    except (TypeError, ValueError):
        raise AuthError("bad_request", "tail must be an integer", status=400) from None
    level = (request.query.get("level") or "").strip().upper()
    if level and level not in _LOG_LEVELS:
        raise AuthError(
            "bad_request",
            f"level must be one of {', '.join(_LOG_LEVELS)}",
            status=400,
        )
    contains = (request.query.get("contains") or "").strip()
    found = _tail_lines(plane, count, level=level or None, contains=contains or None)
    if found is None:
        return web.json_response(
            {
                "error": "unavailable",
                "detail": "no log file is configured; set settings.logging.enable_file",
            },
            status=503,
        )
    lines, truncated = found
    return web.json_response(
        {
            "lines": lines,
            "filtered": bool(level or contains),
            # `truncated` means the walk stopped at its byte budget before reaching the start of the
            # file, so "no lines" is "no match in the window", not "no match in the log" (#171).
            "truncated": truncated,
        }
    )


def _log_path(plane: ControlPlane) -> Path | None:
    """The configured log file, or None when file logging is switched off.

    The resolution lives in `core/logging_setup.py::log_file_path` because the live tail on the
    WebSocket reads the same file (#170), and two answers to "which file" is one too many.
    """
    return log_file_path(plane.context.get("settings"))


def _tail_lines(
    plane: ControlPlane,
    count: int,
    *,
    level: str | None = None,
    contains: str | None = None,
) -> tuple[list[str], bool] | None:
    """The last `count` lines, optionally filtered. None means "no log file configured".

    Unfiltered is one 64 KiB read from the end: the default panel view must not depend on the file's
    size. A filter has to look further back or it lies in exactly the case it exists for — "the ERROR
    was ten minutes ago" (#171) — so it walks backwards in 64 KiB chunks, stopping once it has
    `count` matches or has read `_FILTER_BUDGET` bytes.

    The second element is `truncated`: the walk stopped at the budget rather than at the start of the
    file, so an empty answer honestly means "nothing matched in the window".
    """
    path = _log_path(plane)
    if path is None:
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(0, io.SEEK_END)
            end = handle.tell()
            if level is None and not contains:
                handle.seek(max(0, end - _LOG_CHUNK))
                chunk = handle.read().decode("utf-8", errors="replace")
                return chunk.splitlines()[-count:], False
            budget = min(end, _FILTER_BUDGET)
            window = b""
            kept: list[str] = []
            while end > 0 and len(window) < budget:
                step = min(_LOG_CHUNK, end)
                end -= step
                handle.seek(end)
                window = handle.read(step) + window
                lines = window.decode("utf-8", errors="replace").splitlines()
                if end > 0:
                    # The first element is cut at the window edge; the next iteration completes it.
                    lines = lines[1:]
                kept = _matching_lines(lines, count, level, contains)
                if len(kept) >= count:
                    break
    except OSError:
        return None
    return kept[-count:], end > 0


def _matching_lines(
    lines: list[str], count: int, level: str | None, contains: str | None
) -> list[str]:
    """The last `count` lines that match, walking backwards so the cost is the match, not the file.

    The file is one JSON object per line (`core/logging_setup.py::JsonFormatter`). A traceback's
    continuation lines carry no level of their own, so a `level` filter keeps record lines only -
    which is what the panel has always rendered. `contains` still matches continuation lines, because
    the stack trace is usually the thing being searched for.
    """
    needle = contains.lower() if contains else None
    kept: list[str] = []
    for line in reversed(lines):
        if needle is not None and needle not in line.lower():
            continue
        if level is not None and _line_level(line) != level:
            continue
        kept.append(line)
        if len(kept) >= count:
            break
    kept.reverse()
    return kept


def _line_level(line: str) -> str | None:
    """The `level` of a JSON log line, or None when the line is not a record."""
    stripped = line.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("level")
    return str(value).upper() if value else None


async def _support_bundle(request: web.Request) -> web.Response:
    plane = _plane(request)
    body = plane.support_bundle()
    return web.Response(
        body=body,
        content_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="houndmind-support.zip"'},
    )


# ------------------------------------------------------------------ the web app (#102)

# `index.html` asks for `?v=__VERSION__`; `_index` substitutes the package version at serve time, so
# an upgrade changes the asset URL and a returning browser cannot keep running the copy it has.
_ASSET_VERSION_PLACEHOLDER = "__VERSION__"
_STATIC_PREFIX = "/static/"


def _asset_version() -> str:
    """The installed package version, or `""` in a working tree with no distribution metadata.

    `pytest` runs against `PYTHONPATH=src`, where `houndmind` is not installed, so an empty answer is
    the normal one on a workstation. Empty means the bare path — the behaviour before this existed —
    rather than a broken URL.
    """
    try:
        return metadata.version("houndmind")
    except metadata.PackageNotFoundError:
        return ""


async def _index(request: web.Request) -> web.Response:
    index = _plane(request).static_root / "index.html"
    missing = {"error": "not_found", "detail": "the web app is not bundled with this build"}
    if not index.is_file():
        return web.json_response(missing, status=404)
    try:
        html = index.read_text(encoding="utf-8")
    except OSError:
        return web.json_response(missing, status=404)
    # `no-cache` on the document as well as on the assets (#102, one level up): the markup and the
    # module that reads it ship together, so a browser that keeps an old `index.html` runs new
    # JavaScript against ids that no longer exist. That is not a slow load - it is a `TypeError` at
    # module scope and a page whose buttons do nothing, which reads as a broken device.
    return web.Response(
        text=html.replace(_ASSET_VERSION_PLACEHOLDER, _asset_version()),
        content_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


async def _service_worker(request: web.Request) -> web.Response:
    """The console's service worker, served from the **root** so its scope can cover the document.

    A worker's scope defaults to the directory it was served from, so `/static/sw.js` would only
    control `/static/` and could not answer for `/`. `Service-Worker-Allowed` widens the scope, and a
    same-origin script fetch is the only thing this route ever serves (#176).

    Unauthenticated like the assets it caches: it is static JavaScript, and a token would have to be
    in the URL or the script, which is exactly what the camera-ticket work removed.
    """
    plane = _plane(request)
    path = plane.static_root / "sw.js"
    missing = {"error": "not_found", "detail": "no service worker is bundled with this build"}
    if not path.is_file():
        return web.json_response(missing, status=404)
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return web.json_response(missing, status=404)
    return web.Response(
        text=body,
        content_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


async def _static_cache_headers(request: web.Request, response: web.StreamResponse) -> None:
    """`no-cache` on the web app's assets: revalidate, do not silently reuse (#102).

    `add_static` sends `Last-Modified`/`ETag` and no `Cache-Control`, which lets a browser apply
    heuristic freshness and keep an `app.js` from an older release. Revalidation costs one
    conditional request and removes the failure mode this bug was: stale JavaScript that does not
    break loudly but reports a confident, wrong cause. `setdefault`, so a handler with its own
    answer keeps it.
    """
    if request.path.startswith(_STATIC_PREFIX):
        response.headers.setdefault("Cache-Control", "no-cache")


# ------------------------------------------------------------- the table, re-exported
# The table and the application wiring live in `api_routes.py`, because the table imports these
# handlers *by name*: importing it here, on the last line of this module, is what keeps that
# direction resolvable — `api_routes` imports `services.api` at module scope, so this module has to
# finish defining its handlers first. Every entry point is `services.api` (`services/module.py:247`
# and all fourteen `tests/test_api_*.py` files), so the direction stays this way until AP5 moves the
# last handler out and the dependency becomes one-way.
#
# `E402` is the point of the line, not an accident of it.
from houndmind_ai.services.api_routes import (  # noqa: E402
    ANY_SCOPE,
    API_PREFIX,
    HANDLER_SCOPE,
    ROUTES,
    create_app,
)
