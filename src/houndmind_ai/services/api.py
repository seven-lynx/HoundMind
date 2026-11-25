"""The `v1` control plane: one port, one authenticated API (D7).

`docs/CONTROL_API.md` is the contract. The handlers that implement it live in one module per job
under `services/` — `api_state`, `api_commands`, `api_routines`, `api_admin`, `api_decisions`,
`api_logs`, `api_web`, `api_map`, `api_people` and `api_camera` — and the table that registers them
is `api_routes.py`. What stays here is what all of them share: :class:`ControlPlane`, the object the
routes read, the camera guard, and the calibration allow-list. Two things are load-bearing:

- **Nothing here reaches hardware.** A command is a message on a
  :class:`~houndmind_ai.kernel.commands.CommandBus`; the gateway decides, the interlock judges,
  the HAL moves. The API never has a way to bypass that, which is what makes the phone and the
  web app exactly as safe as any other producer.
- **Every refusal is explained.** A veto, a missing scope, an unknown action, a mode that does
  not allow motion — each one answers with a code the client can show a human, because a dog
  that will not move for an unstated reason is indistinguishable from a broken one.

**Every entry point is still this module.** `services/module.py` imports `ControlPlane` and
`create_app` from here, and so do the fourteen `tests/test_api_*.py` files, so the table is
re-exported at the bottom. Since AP5 the import direction behind that re-export is one-way —
`api_routes` imports the job modules and nothing from this one except the type — which is why
`import houndmind_ai.services.api_routes` now resolves on its own.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import zipfile
from collections.abc import Callable
from importlib import metadata
from pathlib import Path

from aiohttp import web

from houndmind_ai.kernel.commands import (
    AUTONOMY_SOURCES,
    DEFAULT_MODE,
    RUNTIME_MODES,
    Command,
    CommandBus,
    Source,
    Verdict,
)

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

# Re-exported, not used here: `tests/test_map_routes.py:370` reads the CORS method list off this
# module, which is where it lived before AP1 moved the helpers. `F401` is the point of the line.
from houndmind_ai.services.http import _CORS_ALLOW_METHODS  # noqa: F401
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


# ------------------------------------------------------------------ asset versioning (#102)

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


# ------------------------------------------------------------- the table, re-exported
# The table and the application wiring live in `api_routes.py`. Importing it here, on the last line,
# keeps every existing entry point working: `services/module.py` and all fourteen
# `tests/test_api_*.py` files import `ControlPlane` and `create_app` from this module.
#
# Since AP5 this is a re-export and no longer a cycle. `api_routes` imports the handlers from the job
# modules and only the *type* from here (under `TYPE_CHECKING`), so `services.api` -> `api_routes` is
# the single direction and `import houndmind_ai.services.api_routes` resolves on its own.
#
# `E402` is the point of the line, not an accident of it.
from houndmind_ai.services.api_routes import (  # noqa: E402
    ANY_SCOPE,
    API_PREFIX,
    HANDLER_SCOPE,
    ROUTES,
    create_app,
)
