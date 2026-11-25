"""The route table and the application wiring, split out of `services/api.py` (AP1).

One declaration of `(method, path, scope, handler)` is what registers the routes *and* what
`tests/test_api_routes.py` checks against `docs/CONTROL_API.md`, so the table belongs beside the
contract it is checked against rather than at the bottom of the file that holds fifty handler
bodies.

**Every handler is imported from the module that owns its job** — `api_state`, `api_commands`,
`api_routines`, `api_admin`, `api_decisions`, `api_logs`, `api_web`, `api_map`, `api_people` and
`api_camera` (AP2-AP5). This module reads `ControlPlane` from `services.api` under `TYPE_CHECKING`
only, so the dependency is one-way: `services.api` imports this module on its last line, and nothing
here needs `services.api` to have finished loading. `import houndmind_ai.services.api_routes`
therefore resolves on its own, which it could not while the handlers lived there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiohttp import web

from houndmind_ai.services.api_admin import (
    _calibration,
    _calibration_run,
    _config_get,
    _config_patch,
    _config_validate,
    _health,
    _meta,
    _session_delete,
    _sessions,
    _whoami,
)
from houndmind_ai.services.api_camera import (
    _camera_snapshot,
    _camera_stream,
    _camera_ticket,
)
from houndmind_ai.services.api_commands import (
    _command,
    _mode_get,
    _mode_post,
    _repertoire,
    _stop,
)
from houndmind_ai.services.api_decisions import _decisions, _history
from houndmind_ai.services.api_logs import _logs, _support_bundle
from houndmind_ai.services.api_map import (
    _map,
    _map_go,
    _map_pose,
    _map_preview,
    _map_save,
)
from houndmind_ai.services.api_people import (
    _people_delete,
    _people_enroll,
    _people_list,
    _place_delete,
    _place_go,
    _place_update,
    _places_create,
    _places_list,
    _places_teach,
)
from houndmind_ai.services.api_routines import (
    _routine_run,
    _routines_create,
    _routines_list,
)
from houndmind_ai.services.api_state import (
    _events,
    _modules,
    _pair,
    _pair_open,
    _scan,
    _state,
)
from houndmind_ai.services.api_web import (
    _STATIC_PREFIX,
    _index,
    _service_worker,
    _static_cache_headers,
)
from houndmind_ai.services.http import _PLANE, _authed, _cors, _errors

if TYPE_CHECKING:
    from houndmind_ai.services.api import ControlPlane

__all__ = ["ANY_SCOPE", "API_PREFIX", "HANDLER_SCOPE", "ROUTES", "create_app"]

# ------------------------------------------------------------------ the table
#
# One declaration, used both to register the routes and to check them against
# `docs/CONTROL_API.md` in `tests/test_api_routes.py`. A route that exists in code and not in
# the contract is how two clients drift apart.
#
# `scope=None` means exactly one thing: the route is public on purpose. `/meta` and `/health` are
# the liveness surface, and the WebSocket authenticates inside its own `hello` frame because a
# browser cannot set a header on a handshake.
#
# `HANDLER_SCOPE` is the other case, and it is not `None`. The camera routes *do* require
# `state:read`, but the check lives inside their handler, because an `<img>` cannot send an
# `Authorization` header and a single-use ticket replaces it (`_camera_principal`, #18). Writing
# `None` on those two rows made the table read "video is unauthenticated" - a plausible enough
# reading that it was acted on - and left `None` carrying two meanings at once (#39).
HANDLER_SCOPE = "state:read (in handler)"

# The third row shape, and it is not `HANDLER_SCOPE`: `/whoami` requires a valid token and no
# particular scope, because what it reports *is* the scope list (#168). Writing `state:read` there
# would refuse a client holding only `move`, which is exactly the client that needs to be told it
# cannot read state.
ANY_SCOPE = "any valid token"

ROUTES: tuple[tuple[str, str, str | None, Any], ...] = (
    ("GET", "/meta", None, _meta),
    ("GET", "/health", None, _health),
    ("GET", "/whoami", ANY_SCOPE, _whoami),
    ("GET", "/state", "state:read", _state),
    ("GET", "/scan", "state:read", _scan),
    ("GET", "/map", "state:read", _map),
    ("PUT", "/map", "config", _map_save),
    ("PUT", "/map/pose", "move", _map_pose),
    ("POST", "/map/go", "move", _map_go),
    ("POST", "/map/preview", "state:read", _map_preview),
    ("GET", "/modules", "state:read", _modules),
    ("GET", "/repertoire", "state:read", _repertoire),
    ("GET", "/routines", "state:read", _routines_list),
    ("POST", "/routines", "config", _routines_create),
    ("GET", "/places", "state:read", _places_list),
    ("GET", "/people", "admin", _people_list),
    ("POST", "/people", "admin", _people_enroll),
    ("GET", "/decisions", "state:read", _decisions),
    ("GET", "/events", None, _events),
    ("GET", "/camera/stream", HANDLER_SCOPE, _camera_stream),
    ("GET", "/camera/snapshot", HANDLER_SCOPE, _camera_snapshot),
    ("POST", "/camera/ticket", "state:read", _camera_ticket),
    ("POST", "/pair", None, _pair),
    ("POST", "/pair/open", "admin", _pair_open),
    ("POST", "/command", "move", _command),
    ("POST", "/stop", "move", _stop),
    ("POST", "/routines/{id}/run", "move", _routine_run),
    ("POST", "/places", "config", _places_create),
    ("DELETE", "/places/{id}", "config", _place_delete),
    ("PATCH", "/places/{id}", "config", _place_update),
    ("DELETE", "/people/{id}", "admin", _people_delete),
    ("POST", "/places/{id}/go", "move", _place_go),
    ("POST", "/places/teach", "config", _places_teach),
    ("GET", "/mode", "state:read", _mode_get),
    ("POST", "/mode", "move", _mode_post),
    ("GET", "/config", "config", _config_get),
    ("PATCH", "/config", "config", _config_patch),
    ("POST", "/config/validate", "config", _config_validate),
    ("GET", "/sessions", "admin", _sessions),
    ("DELETE", "/sessions/{key}", "admin", _session_delete),
    ("GET", "/calibration", "config", _calibration),
    ("POST", "/calibration/run", "config", _calibration_run),
    ("GET", "/history", "state:read", _history),
    ("GET", "/logs", "admin", _logs),
    ("GET", "/support-bundle", "admin", _support_bundle),
)

API_PREFIX = "/api/v1"


def create_app(plane: ControlPlane) -> web.Application:
    """Build the aiohttp application. Binding a port is the caller's job (`ControlPlaneModule`)."""
    app = web.Application(middlewares=[_cors, _errors], client_max_size=64 * 1024)
    app[_PLANE] = plane
    router = app.router

    for method, path, scope, handler in ROUTES:
        route = f"{API_PREFIX}{path}"
        if scope is None or scope is HANDLER_SCOPE:
            # Public, or enforced inside the handler: registering a bearer wrapper either way
            # would break the route it is meant to protect.
            router.add_route(method, route, handler)
        elif scope is ANY_SCOPE:
            # A token, any token: the wrapper authenticates and stops there (`/whoami`, #168).
            router.add_route(method, route, _authed()(handler))
        else:
            router.add_route(method, route, _authed(scope)(handler))

    router.add_get("/", _index)
    # At the root, not under `/static/`: a worker's scope defaults to its own directory, and the app
    # shell it caches is the document at `/` (#176).
    router.add_get("/sw.js", _service_worker)
    if plane.static_root.is_dir():
        # `add_static` refuses to serve outside the directory it was given, so the web app
        # cannot be used to read `/etc/shadow` by asking for `../../etc/shadow`.
        router.add_static(_STATIC_PREFIX, plane.static_root, show_index=False)
    # One hook for the whole app: the assets are the only surface where a stale copy is a wrong
    # diagnosis rather than a slow load.
    app.on_response_prepare.append(_static_cache_headers)

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
