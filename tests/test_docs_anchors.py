"""Every `#anchor` in `docs/` resolves to a heading in the page it names (#116).

`test_docs_contract.py` holds a relative link to its path; the fragment is the other half, and it is
the half nothing checked while 249 `§N` references sat in plain text. The slug rule is GitHub's:
lowercase, drop everything that is not a letter, digit, space, hyphen or underscore, then turn each
space into a hyphen.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"

HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"^\s*```")


def slug(title: str) -> str:
    kept = [
        char for char in title.lower() if char.isascii() and (char.isalnum() or char in " -_")
    ]
    return "".join(kept).replace(" ", "-")


def _without_fences(text: str) -> str:
    """A `#` comment inside an example is not a heading, so the block is blanked first."""
    lines: list[str] = []
    inside = False
    for line in text.splitlines():
        if FENCE.match(line):
            inside = not inside
            lines.append("")
            continue
        lines.append("" if inside else line)
    return "\n".join(lines)


def anchors(text: str) -> set[str]:
    return {slug(title) for title in HEADING.findall(_without_fences(text))}


def test_every_anchor_resolves_to_a_heading() -> None:
    pages = {path: path.read_text(encoding="utf-8") for path in sorted(DOCS.rglob("*.md"))}
    by_path = {path.resolve(): text for path, text in pages.items()}
    problems: list[str] = []
    for page, text in pages.items():
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, fragment = target.partition("#")
            if not fragment:
                continue
            resolved = (page.parent / path).resolve() if path else page.resolve()
            if resolved not in by_path:
                # A missing page is `test_every_relative_link_resolves`; do not report it twice.
                continue
            if fragment not in anchors(by_path[resolved]):
                problems.append(f"{page.relative_to(DOCS.parent).as_posix()} -> {target}")
    assert problems == [], f"anchor with no heading behind it: {problems}"
