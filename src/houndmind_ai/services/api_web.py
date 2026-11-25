"""The web app's serving surface, split out of `services/api.py` (AP5).

Four handlers and the two constants only they read: the document at `/`, the service worker at
`/sw.js`, the `no-cache` hook every static response passes through, and the prefix `add_static` is
mounted at. The **assets** stay where they were (`services/web/`, Q3 of the plan); what moves is the
code that serves them.

All three routes are deliberately unauthenticated: they are markup, JavaScript and a stylesheet, and
a token would have to travel in the URL or the script, which is exactly what the camera-ticket work
removed (#18). Nothing here reads a sensor or publishes anything.

**`_asset_version` stays in `services/api.py`, and is imported inside the call.** It is the one
symbol `tests/test_api_routes.py` patches on `services.api` to prove an upgrade changes the asset
URL, so a module-scope binding here would stop the plant from reaching and the versioned-asset
assertion would fail for a reason that has nothing to do with the bug it guards (#102).
"""

from __future__ import annotations

from aiohttp import web

from houndmind_ai.services.http import _plane

# `index.html` asks for `?v=__VERSION__`; `_index` substitutes the package version at serve time, so
# an upgrade changes the asset URL and a returning browser cannot keep running the copy it has.
_ASSET_VERSION_PLACEHOLDER = "__VERSION__"
_STATIC_PREFIX = "/static/"


async def _index(request: web.Request) -> web.Response:
    from houndmind_ai.services.api import _asset_version

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
