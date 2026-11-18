"""The contract and the snapshot are checked against each other (#314).

`docs/CONTROL_API.md` is what a client implements against, and nothing asserted that its state
section matched what `build_state` publishes: a renamed key would break a shipped phone while the
suite stayed green, and a new key reached clients with no contract row at all. The JSON block in
section 4 is the machine-readable half - it is parsed here, not restated - so the two cannot drift
without a failure.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.services.state import build_state

__all__ = [
    "test_every_documented_key_is_published",
    "test_every_published_key_is_documented",
    "test_every_state_field_a_panel_reads_is_documented",
]

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs" / "CONTROL_API.md"
WEB_ROOT = ROOT / "src" / "houndmind_ai" / "services" / "web"


def documented_state() -> dict:
    """The JSON block under `## 4. State snapshot`, parsed rather than copied."""
    text = CONTRACT.read_text(encoding="utf-8")
    section = text.split("## 4. State snapshot", 1)[1]
    block = section.split("```json", 1)[1].split("```", 1)[0]
    return json.loads(block)


WILDCARD = re.compile(r"^<[a-z_]+>$")


def _is_map(documentation: dict) -> bool:
    """A block whose one key is a `<name>` placeholder is a map, documented by example.

    `supervisor.exempt` is keyed by module name and `health.high_water` by signal, so the contract
    cannot name their keys. The placeholder is the convention that says so, and it is what stops
    this test from demanding a module called `<module>`.
    """
    return bool(documentation) and all(WILDCARD.match(str(key)) for key in documentation)


def _nested_differences(documented: dict, published: object, path: str) -> list[str]:
    """Documented keys that are not in the published tree, for sections that publish one.

    A section the snapshot reports as `null` is skipped: the contract says which ones are null
    until something publishes them, and a test that demanded a decision record before the gateway
    has ticked would be testing the fake, not the contract.
    """
    if not isinstance(published, dict) or _is_map(documented):
        return []
    missing = [f"{path}.{key}" for key in documented if key not in published]
    for key, value in documented.items():
        if isinstance(value, dict):
            missing += _nested_differences(value, published.get(key), f"{path}.{key}")
    return missing


def test_every_documented_key_is_published() -> None:
    snapshot = build_state(RuntimeContext(), now=0.0)
    differences = _nested_differences(documented_state(), snapshot, "state")

    assert not differences, "documented but not published: " + ", ".join(differences)


def test_every_published_key_is_documented() -> None:
    """A new key reaches clients the moment it is published, so it needs a contract row first."""
    documented = set(documented_state())
    published = set(build_state(RuntimeContext(), now=0.0))

    assert not published - documented, "published but undocumented: " + ", ".join(
        sorted(published - documented)
    )


def test_every_state_field_a_panel_reads_is_documented() -> None:
    """The panels are the shipped client, so what they read is the contract in practice."""
    documented = set(documented_state())
    pattern = re.compile(r"\bsnapshot\.([a-z_][a-z0-9_]*)")
    read: dict[str, str] = {}
    for source in sorted(WEB_ROOT.rglob("*.js")):
        for key in pattern.findall(source.read_text(encoding="utf-8")):
            read.setdefault(key, str(source.relative_to(WEB_ROOT)).replace("\\", "/"))

    assert read, "no panel reads a snapshot field: the scan is broken, not the contract"
    undocumented = {key: where for key, where in read.items() if key not in documented}
    assert not undocumented, "read by a panel but undocumented: " + ", ".join(
        f"{key} ({where})" for key, where in sorted(undocumented.items())
    )
