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
import math
import secrets
import threading
import time
import zipfile
from collections.abc import Callable
from difflib import get_close_matches
from importlib import metadata
from pathlib import Path
from typing import Any

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
from houndmind_ai.kernel.config_schema import Problem, validate_settings_section
from houndmind_ai.kernel.decisions import DecisionRing
from houndmind_ai.kernel.place import Place, slug
from houndmind_ai.kernel.place_store import PlaceStore
from houndmind_ai.kernel.routine_store import RoutineConflict, RoutineStore, StoreReport
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
from houndmind_ai.perception.place_views import (
    DEFAULT_VIEWS_DIR,
    PlaceView,
    load_views,
    remove_views,
    save_views,
    thumb_b64,
    upsert_view,
    view_from_frame,
    view_from_jpeg,
)
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


def _header_token(request: web.Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


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
