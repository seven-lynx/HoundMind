"""The state surface, split out of `services/api.py` (AP5).

Six routes that only ever answer a question: the snapshot (`GET /state`), the last head sweep
(`GET /scan`), the module table (`GET /modules`), the WebSocket (`GET /events`) and the two
pairing routes that hand a new client its token (`POST /pair`, `POST /pair/open`).

They move together because they are one job — *what is this dog doing, and who may look* — and
because `/events` is the route whose auth lives in its own `hello` frame, which is the exception
`services/api_routes.py` writes as `scope=None` beside `/meta` and `/health`.

**Nothing here touches hardware or publishes an intent.** A command goes through `POST /command`
and reaches `act/gateway.py` like every other producer's; there is no path from this module to a
servo, which is what lets any paired client read state at full rate.
"""

from __future__ import annotations

import logging

from aiohttp import web

from houndmind_ai.services.auth import AuthError
from houndmind_ai.services.http import _PRINCIPAL, _json_body, _plane
from houndmind_ai.services.state import build_modules

logger = logging.getLogger(__name__)


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
