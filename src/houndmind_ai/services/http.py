"""The request helpers every route surface shares, split out of `services/api.py` (AP1).

Nothing here knows a route. `_plane`, the CORS pair, the auth decorator and the three body parsers
are what a handler calls *before* it does its job, and they are the part of `services/api.py` that
`services/api_routes.py` can have without importing a single handler.

**The import direction.** `ControlPlane` is imported under `TYPE_CHECKING` only: the live object is
read off the application at request time through `_PLANE`, so this module imports while
`services/api.py` is still half-way through defining its classes. That keeps

    services.api  ->  services.http  ->  services.auth

one-way. `web.AppKey` is built without its type argument for the same reason — passing the class
would need it at runtime, and aiohttp keeps that argument for `repr` alone (`helpers.BaseKey`).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web

from houndmind_ai.services.auth import AuthError

if TYPE_CHECKING:
    from houndmind_ai.services.api import ControlPlane

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- helpers

# aiohttp's documented way to key an application/request mapping: a plain string key warns on
# every request, and a warning nobody reads is a warning that hides the next one.
_PLANE: web.AppKey[ControlPlane] = web.AppKey("plane")
_PRINCIPAL: web.RequestKey[Any] = web.RequestKey("principal", object)


def _plane(request: web.Request) -> ControlPlane:
    return request.app[_PLANE]


_CORS_ALLOW_HEADERS = "Authorization, Content-Type"
_CORS_ALLOW_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"


def _with_cors(response: web.StreamResponse, origin: str | None) -> web.StreamResponse:
    """Attach the CORS headers. `Vary` goes on even when the origin is not allowed.

    A cache that keyed a response without `Vary: Origin` would hand one origin's allowed answer to a
    different one, which is the same hole with a longer path to it.
    """
    response.headers["Vary"] = "Origin"
    if origin is not None:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = _CORS_ALLOW_HEADERS
        response.headers["Access-Control-Allow-Methods"] = _CORS_ALLOW_METHODS
        response.headers["Access-Control-Max-Age"] = "600"
    return response


@web.middleware
async def _cors(request: web.Request, handler):
    """Answer a listed console's cross-origin request, and nothing else (#202).

    The token is still the boundary: this only decides which *pages* may read a response they
    already hold a token for. `settings.api.cors_origins` is empty by default, so a plain install
    behaves exactly as before and answers no cross-origin read at all.

    A preflight is answered here rather than by a route, because a browser sends `OPTIONS` without
    `Authorization` - a preflight that had to pass the token check could never pass.
    """
    allowed = _plane(request).settings.cors_origins
    if not allowed:
        return await handler(request)
    origin = request.headers.get("Origin")
    matched = origin if origin in allowed else None
    if request.method == "OPTIONS" and matched is not None:
        return _with_cors(web.Response(status=204), matched)
    return _with_cors(await handler(request), matched)


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


def _authed(scope: str | None = None):
    """Require a valid token, and a scope when one is named. Applied at registration time.

    `scope=None` means "any valid token", which is one route's requirement: `/whoami` must answer a
    caller holding *any* scope, because the scopes it reports are the answer (#168). Every other
    route names one, so `None` cannot be read as "no auth" here - that spelling is reserved for
    `ROUTES`, where `None` means public on purpose.
    """

    def decorate(handler):
        async def wrapped(request: web.Request):
            plane = _plane(request)
            principal = plane.authorizer.authenticate(request.headers.get("Authorization"))
            if scope is not None:
                plane.authorizer.require(principal, scope)
            request[_PRINCIPAL] = principal
            return await handler(request)

        wrapped.__name__ = getattr(handler, "__name__", "handler")
        return wrapped

    return decorate


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

