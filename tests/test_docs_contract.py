"""`docs/` against the tree — the checks that keep an audit from being a one-off.

`tests/test_api_routes.py` holds the route table to the contract; this does the same job for the
documentation. Every page is listed in an index, every relative link resolves, every fence closes,
no page cites a gitignored path, and every `settings.<section>.<field>` a page names exists in the
shipped `config/settings.jsonc` or the schema behind it.

A page that deliberately names a *removed* key says so on the same line ("removed", "gone",
"deleted", "no longer"), which is how the migration stubs in `FEATURES_GUIDE.md` §21/§24/§25 keep
their did-you-mean notes without tripping this file.
"""

from __future__ import annotations

import re
from pathlib import Path

import json5

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"
INDEX = DOCS / "README.md"
PIDOG_INDEX = DOCS / "pidog" / "INDEX.md"
SETTINGS = REPO_ROOT / "config" / "settings.jsonc"
SCHEMA = REPO_ROOT / "src" / "houndmind_ai" / "kernel" / "config_schema.py"

STATUSES = {"contract", "design", "reference", "guide", "runbook", "index", "historical"}
STATUS_LINE = re.compile(r"^Status:\s*\*\*([a-z]+)\*\*", re.MULTILINE)
LINK = re.compile(r"\]\(([^)\s]+)\)")
FENCE = re.compile(r"^\s*```+(.*)$")
LOCAL_ONLY = re.compile(r"`(?:\.clinerules|\.houndmind-local|\.github/skills)/")
SETTING = re.compile(r"`settings\.([a-z0-9_]+)\.([a-z0-9_.]+)`")
REMOVED_WORDS = ("removed", "gone", "deleted", "no longer")


def pages() -> list[Path]:
    return sorted(path for path in DOCS.rglob("*.md") if path.is_file())


def label(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def test_every_page_declares_a_status() -> None:
    """A page without a `Status:` line does not say who it binds, so it cannot be quoted safely."""
    problems = []
    for page in pages():
        match = STATUS_LINE.search(page.read_text(encoding="utf-8"))
        if match is None or match.group(1) not in STATUSES:
            problems.append(label(page))
    assert not problems, f"missing or unknown Status header: {problems}"


def test_every_page_is_listed_in_an_index() -> None:
    """`docs/README.md` for the top level, `docs/pidog/INDEX.md` for the reference set."""
    root_index = INDEX.read_text(encoding="utf-8")
    pidog_index = PIDOG_INDEX.read_text(encoding="utf-8")
    problems = []
    for page in pages():
        if page in (INDEX, PIDOG_INDEX):
            continue
        index = pidog_index if page.parent.name == "pidog" else root_index
        if page.name not in index:
            problems.append(label(page))
    assert not problems, f"page not reachable from its index: {problems}"


def test_every_relative_link_resolves() -> None:
    """A link is a promise. An anchor-only link is skipped; a path must exist on disk."""
    problems = []
    for page in pages():
        for target in LINK.findall(page.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            if not path:
                continue
            if not (page.parent / path).exists():
                problems.append(f"{label(page)} -> {target}")
    assert not problems, f"broken relative link: {problems}"


def test_every_fence_closes() -> None:
    """A language-tagged fence inside an open block is the bug class this catches.

    A closing fence must have no info string. When one does, the block that opened earlier never
    closed and every heading after it renders as code — which is how two reference pages used to
    lose half their headings.
    """
    problems = []
    for page in pages():
        opened = False
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            match = FENCE.match(line)
            if match is None:
                continue
            info = match.group(1).strip()
            if not opened:
                opened = True
            elif info:
                problems.append(f"{label(page)}:{number} opens a tagged fence while one is open")
            else:
                opened = False
        if opened:
            problems.append(f"{label(page)}: last fence is never closed")
    assert not problems, "; ".join(problems)


def test_no_page_cites_a_local_only_path() -> None:
    """`.clinerules/`, `.houndmind-local/` and `.github/skills/` are gitignored.

    A tracked page that points at one is broken for every reader but its author. A page may still
    *name* one while explaining that it is excluded, which is what the `gitignored` escape is for.
    """
    problems = []
    for page in pages():
        for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if "gitignored" in line.lower():
                continue
            match = LOCAL_ONLY.search(line)
            if match is not None:
                problems.append(f"{label(page)}:{number} cites {match.group(0)[1:-1]}")
    assert not problems, "; ".join(problems)


def _shipped_settings() -> dict:
    return json5.loads(SETTINGS.read_text(encoding="utf-8")).get("settings", {})


def _schema_fields() -> set[str]:
    """Every key name the validator knows, read from the schema source.

    Loose on purpose: it answers "has this project ever defined a key by this name", not "is it in
    the right section". A name that exists nowhere is the failure this catches.
    """
    text = SCHEMA.read_text(encoding="utf-8")
    return set(re.findall(r'"([a-z][a-z0-9_]*)"\s*:', text))


def _resolves(node: object, parts: list[str]) -> bool:
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def test_cited_settings_keys_exist() -> None:
    """A `settings.<section>.<field>` a page names must resolve, or the page cost a user a load error."""
    shipped = _shipped_settings()
    known = _schema_fields()
    problems = []
    for page in pages():
        lines = page.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            # A removal note may wrap onto the next line, so look one either side before judging.
            window = " ".join(lines[max(0, index - 1) : index + 2]).lower()
            if any(word in window for word in REMOVED_WORDS):
                continue
            for section, rest in SETTING.findall(line):
                if section not in shipped:
                    continue  # the section ships from schema defaults only; nothing to compare
                parts = rest.split(".")
                if _resolves(shipped[section], parts) or parts[-1] in known:
                    continue
                problems.append(f"{label(page)}:{index + 1} settings.{section}.{rest}")
    assert not problems, f"settings key that exists nowhere: {problems}"

