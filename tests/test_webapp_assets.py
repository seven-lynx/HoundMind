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

import re
from pathlib import Path

__all__ = ["test_the_stylesheet_honours_the_hidden_attribute"]

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

