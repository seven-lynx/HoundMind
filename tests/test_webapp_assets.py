"""The stylesheet must honour the `hidden` attribute.

`hidden` is implemented by the user agent as `[hidden] { display: none }`, and an author rule that
sets `display` on the same element beats it no matter how specific the other selector is. The web app
hides the shell with the attribute and the connect card with the property, and both of those
elements carry `display: grid` - so before this rule existed, "Use token" hid a card that stayed on
screen while the console rendered one screen below it. It read as a dead button for three commits,
and the symptom pointed at the network rather than at the cascade.

There is no browser in this suite, so the guard is textual. It fails when the rule that makes
`hidden` work is deleted, which is the only way this comes back.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = [
    "test_a_notification_is_never_the_only_signal",
    "test_components_take_their_colours_from_tokens",
    "test_every_dark_colour_token_has_a_light_value",
    "test_notifications_are_asked_for_on_a_click_and_checked_before_use",
    "test_the_manifest_points_at_an_icon_that_exists",
    "test_the_stylesheet_honours_the_hidden_attribute",
    "test_the_worker_is_registered_only_in_a_secure_context",
    "test_the_worker_never_caches_the_api",
]

WEB = Path(__file__).resolve().parents[1] / "src" / "houndmind_ai" / "services" / "web"
STYLE = WEB / "style.css"

# Anchored at the start of a line on purpose: `.banner[hidden] { … }` is a rule about one element,
# and accepting it would let the global rule be deleted while this test stayed green.
_GLOBAL_HIDDEN_RULE = re.compile(r"^\s*\[hidden\]\s*\{[^}]*display\s*:\s*none", re.MULTILINE)


def test_the_stylesheet_honours_the_hidden_attribute() -> None:
    css = STYLE.read_text(encoding="utf-8")
    assert _GLOBAL_HIDDEN_RULE.search(css), (
        "style.css has no `[hidden] { display: none }` rule. `.connect` and `.shell` set their own"
        " `display`, which overrides the user-agent rule behind the `hidden` attribute - so the"
        " connect card never leaves the screen and the console stays below it."
    )


def test_the_elements_that_rely_on_hidden_still_set_their_own_display() -> None:
    """The precondition, asserted so this test file explains itself.

    If `.connect` or `.shell` stops setting `display`, the rule above becomes unnecessary rather than
    wrong - this only fails if someone removes the `display` and then deletes the guard as "dead
    code", which is how a fix gets reverted by tidying.
    """
    css = STYLE.read_text(encoding="utf-8")
    assert ".connect {" in css and ".shell {" in css


# ------------------------------------------------------------- themes (#178)

_TOKEN = re.compile(r"(--[\w-]+)\s*:\s*([^;]+);")
_LIGHT_OPENER = r':root\[data-theme="light"\]\s*\{'


def _block(css: str, opener: str) -> str:
    """The body of the first rule matching `opener`."""
    match = re.search(opener, css)
    assert match is not None, f"no rule matching {opener!r} in style.css"
    start = match.end()
    return css[start : css.index("}", start)]


def _tokens(block: str) -> dict[str, str]:
    return {match.group(1): match.group(2).strip() for match in _TOKEN.finditer(block)}


def test_every_dark_colour_token_has_a_light_value() -> None:
    """One token missing from the light block is one component in the wrong palette (#178).

    Invisible in review, because the dark block is the one people read: a rule that uses a token the
    light theme never restates silently inherits a near-black value on a white page.
    """
    css = STYLE.read_text(encoding="utf-8")
    dark = _tokens(_block(css, r":root\s*\{"))
    light = _tokens(_block(css, _LIGHT_OPENER))

    colours = {name for name, value in dark.items() if value.startswith("#")}
    assert len(colours) >= 10, "the dark block has no colour tokens: has the stylesheet moved?"
    assert colours <= set(light), f"light is missing {sorted(colours - set(light))}"


def test_components_take_their_colours_from_tokens() -> None:
    """A literal hex in a component rule is a rule that ignores the theme (#178)."""
    css = STYLE.read_text(encoding="utf-8")
    # Comments are stripped first: a comment that explains a contrast ratio names colours, and it is
    # not a rule.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    without_tokens = css
    for opener in (r":root\s*\{", _LIGHT_OPENER):
        match = re.search(opener, without_tokens)
        assert match is not None
        end = without_tokens.index("}", match.end()) + 1
        without_tokens = without_tokens[: match.start()] + without_tokens[end:]

    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b", without_tokens)
    assert literals == [], f"component colours must be tokens, found {literals}"


# ------------------------------------------------------------- the app shell (#176)


def test_the_manifest_points_at_an_icon_that_exists() -> None:
    """An installable console with a 404 icon is a console the browser will not install."""
    manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))

    assert manifest["start_url"] == "/" and manifest["scope"] == "/"
    icons = manifest["icons"]
    assert icons, "a PWA without an icon is not installable"
    for icon in icons:
        relative = icon["src"].removeprefix("/static/")
        assert (WEB / relative).is_file(), icon["src"]


def test_the_worker_is_registered_only_in_a_secure_context() -> None:
    """`http://<pi>:8420` is not secure, so a worker there would only error (#176)."""
    lib = (WEB / "lib.js").read_text(encoding="utf-8")

    guard = lib.index("isSecureContext")
    register = lib.index("navigator.serviceWorker.register")
    assert guard < register, "the secure-context check must run before the registration"


def test_the_worker_never_caches_the_api() -> None:
    """A cached `/state` is a console showing a dog that is not there."""
    worker = (WEB / "sw.js").read_text(encoding="utf-8")

    assert 'url.pathname.startsWith("/api/")' in worker

# ------------------------------------------------------------- notifications (#177)


def test_notifications_are_asked_for_on_a_click_and_checked_before_use() -> None:
    """A permission prompt on load is the one nobody grants; a notification without permission throws."""
    app = (WEB / "app.js").read_text(encoding="utf-8")

    request = app.index("Notification.requestPermission")
    construct = app.index("new Notification(")
    assert request < construct, "the prompt must be reachable before anything notifies"
    assert app.count("Notification.requestPermission") == 1, (
        "one place asks: a prompt that fires from several paths is a prompt that fires on load"
    )
    # The one ask is inside the button's click handler, not at startup.
    assert app.rindex('bind("notify-toggle", "click"', 0, request) < request
    assert 'Notification.permission !== "granted"' in app, (
        "constructing without permission throws on every event"
    )
    assert "isSecureContext" in app, "Notification needs a secure context; plain http must not ask"


def test_a_notification_is_never_the_only_signal() -> None:
    """The ticker records every event whether or not a notification is allowed."""
    app = (WEB / "app.js").read_text(encoding="utf-8")

    branch = app[app.index('frame.type === "event"') :]
    branch = branch[: branch.index("} else if")]
    assert "store.event(" in branch
    assert branch.index("store.event(") < branch.index("notifySafety("), (
        "record it first: the notification is the extra signal, not the record"
    )

