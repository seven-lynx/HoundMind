"""Every route the control plane serves is reachable from the bundled web app.

The gap this closes: the app shipped as a working client for 8 of 32 routes, so most features were
reachable only by curl - and nothing failed when a new route arrived with no UI at all. A route a
user cannot reach from the app is a feature only an SSH session can use, which is the definition of
a client that is not finished.

The check is deliberately textual: it scans `services/web/**/*.js` for each route's path and
accepts a template substitution in place of a `{param}` segment, because that is how the panels
call `/routines/${id}/run`. It is not a JS parser and it does not try to be - a false negative
costs one allowlist entry, and a false positive is caught the moment the panel is opened.

`_UI_EXCLUDED` is the escape hatch: an exclusion needs a written reason, so the next person can tell
a decision from an oversight. It is empty since M3 gave `PUT /map` its editor (#309) - the route M1
shipped and this file excused now has a caller, and the row went with it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from houndmind_ai.services.api import ROUTES

__all__ = ["test_every_route_is_reachable_from_the_web_app"]

WEB_ROOT = Path(__file__).resolve().parents[1] / "src" / "houndmind_ai" / "services" / "web"

# `"GET /path": "why the app does not call it"`. A row here is a decision with a segment named in
# it, not a place to park a route nobody got round to. It is empty: M3 gave `PUT /map` its editor.
_UI_EXCLUDED: dict[str, str] = {
    "POST /config/validate": (
        "for a script or a settings panel's own preview: the web app's config panel saves through "
        "PATCH, which runs the same validation, so it has nothing to ask (#406)"
    ),
    "GET /sessions": (
        "who is connected is an admin/support question; the app has no session panel and the "
        "support bundle already carries the same list (#404)"
    ),
    "DELETE /sessions/{key}": (
        "detaching a client is an admin action from a second terminal, deliberately not a button "
        "in the app that the client being detached is using (#404)"
    ),
}

# A route segment that takes a parameter is called with a template substitution in the panels,
# e.g. `/routines/${encodeURIComponent(id)}/run`. Anything without a quote, a backtick, a slash or
# whitespace is accepted in its place.
_PARAM = r"""[^"'`\s/]+"""


def _web_sources() -> dict[str, str]:
    """Every JS file under the web root, keyed by relative path."""
    return {
        str(path.relative_to(WEB_ROOT)).replace("\\", "/"): path.read_text(encoding="utf-8")
        for path in sorted(WEB_ROOT.rglob("*.js"))
    }


def _route_pattern(path: str) -> re.Pattern[str]:
    """A regex matching how the panels spell one route path.

    The trailing lookahead keeps `/places` from being satisfied by a call to `/places/${id}/go`:
    two routes are two entries, and a list endpoint nobody calls is still a missing call.
    """
    segments = []
    for segment in path.strip("/").split("/"):
        if segment.startswith("{") and segment.endswith("}"):
            segments.append(_PARAM)
        else:
            segments.append(re.escape(segment))
    return re.compile("/" + "/".join(segments) + r"""(?![\w/-])""")


def _uncovered_routes() -> list[str]:
    sources = _web_sources()
    uncovered: list[str] = []
    for method, path, _scope, _handler in ROUTES:
        key = f"{method} {path}"
        if key in _UI_EXCLUDED:
            continue
        pattern = _route_pattern(path)
        if not any(pattern.search(text) for text in sources.values()):
            uncovered.append(key)
    return uncovered


def test_every_route_is_reachable_from_the_web_app() -> None:
    sources = _web_sources()
    assert sources, f"no JavaScript found under {WEB_ROOT}"

    uncovered = _uncovered_routes()
    if uncovered:
        listing = "\n".join(f"  - {route}" for route in uncovered)
        pytest.fail(
            f"{len(uncovered)} of {len(ROUTES)} routes are not called by the web app:\n{listing}\n"
            "Add the call to a panel under src/houndmind_ai/services/web/, or add the route to"
            " _UI_EXCLUDED with the reason it has no UI."
        )
