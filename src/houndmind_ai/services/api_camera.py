"""The camera surface, split out of `services/api.py` (AP2).

Three handlers and nothing else: the MJPEG stream, a single frame, and the ticket that buys both.
They are the only routes whose scope check lives inside the handler (`HANDLER_SCOPE` in
`services/api_routes.py`) because an `<img>` cannot send an `Authorization` header, and a single-use
ticket replaces the device token (#18). Moving them together gives that rule one home.

**`_camera_principal` stays in `services/api.py`, and is imported inside the call, not at the top.**
It is the guard, and `tests/test_api_routes.py` proves the handlers consult it by planting a refusal
with `monkeypatch.setattr(api_module, "_camera_principal", …)`. A module-scope
`from houndmind_ai.services.api import _camera_principal` would bind the original function object, so
the plant would stop intercepting and the test would pass for the wrong reason; a call-time import
resolves the name through `services.api` on every request, which is what the test patches.

**The import direction is one-way.** This module imports `services.http` and `aiohttp` only, so it
loads while `services/api.py` is still half-way through defining its classes — the same reason
`services/http.py` imports `ControlPlane` under `TYPE_CHECKING`.
"""

from __future__ import annotations

from aiohttp import web

from houndmind_ai.services.http import _plane


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


async def _camera_stream(request: web.Request) -> web.StreamResponse:
    from houndmind_ai.services.api import _camera_principal

    plane = _plane(request)
    _camera_principal(plane, request)
    return await plane.camera.stream(request)


async def _camera_snapshot(request: web.Request) -> web.Response:
    from houndmind_ai.services.api import _camera_principal

    plane = _plane(request)
    _camera_principal(plane, request)
    return await plane.camera.snapshot(request)
