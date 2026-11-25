"""The decision and audit surface, split out of `services/api.py` (AP5).

Two reads and nothing that writes: `GET /decisions`, the per-tick record ring (§4.2 of the design),
and `GET /history`, the motion audit plus the active sessions. They are the "why did it do that"
pair, and they share one rule — a missing feed answers `503` rather than an empty list, because
`modules.decision_log.enabled: false` and "the dog has not decided anything yet" would otherwise
look identical and only one of them is worth a bug report.
"""

from __future__ import annotations

from aiohttp import web

from houndmind_ai.kernel.decisions import DecisionRing
from houndmind_ai.services.auth import AuthError
from houndmind_ai.services.http import _plane


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
