#!/usr/bin/env python3
"""Check the voice phrase map without starting the runtime (VD1, #258, #321).

A phrase that resolves to an action nothing can execute is silent by construction: the voice module
sets `behavior_override`, the gateway refuses the name as unclassified, and the operator hears
nothing because the dog did nothing. Nothing between the two said so — the phrase map is a table of
strings, and a typo in a value is indistinguishable from a valid entry until someone says the word.

What this tool checks is what `optional/voice.py::_resolve_action` actually does, not what the table
looks like it does. That runtime resolves **one hop**: a phrase equal to a `command_map` key yields
that key's value; a phrase equal to an `aliases` key yields `command_map[value]` when `value` is a
key, and otherwise `value` **raw**, as if it were an action name. So an alias whose value names no
action is not a broken chain that falls back — it is a dead action name, and a cycle is a dead name
too rather than a hang. The name set is `kernel/actions.py::repertoire_from_settings`, which is the
catalog the config implies plus the built-in floor, and names are compared through
`kernel/commands.py::canonical_action`, so `turn left` and `turn_left` are one action.

Usage:
    python -m tools.validate_phrases
    python -m tools.validate_phrases --config bench-settings.jsonc
    python -m tools.validate_phrases --json

Exit codes: `0` every phrase resolves (warnings are printed and still exit `0`), `1` at least one
phrase or alias cannot reach an action, `2` the config would not load.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.actions import Repertoire, repertoire_from_settings
from houndmind_ai.kernel.commands import canonical_action
from houndmind_ai.kernel.config_schema import ConfigError

__all__ = ["Finding", "check", "main", "validate"]

# Findings that describe a smell rather than a defect: they are printed, and they do not set the
# exit code. A shipped config must be able to be clean, or the tool gets ignored on day one.
_WARNING_KINDS = frozenset({"shadowed_key"})


@dataclass(frozen=True)
class Finding:
    """One thing wrong with the phrase map, and the phrase it was found on."""

    kind: str
    section: str
    phrase: str
    target: str
    message: str

    @property
    def severity(self) -> str:
        return "warning" if self.kind in _WARNING_KINDS else "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "section": self.section,
            "phrase": self.phrase,
            "target": self.target,
            "message": self.message,
        }


def _phrase_map(raw: Any) -> dict[str, str]:
    """The `phrase -> value` table, or nothing when the section is absent or the wrong shape.

    A non-string key or value is ignored rather than guessed at: `kernel/config_schema.py` refuses
    one at load, so anything reaching here has already been typed.
    """
    if not isinstance(raw, Mapping):
        return {}
    return {
        key: value
        for key, value in raw.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _voice_section(settings: Any) -> Mapping[str, Any]:
    """`settings.voice_assistant` — the section the runtime reads (`optional/voice.py:80`, `:120`)."""
    section = settings.get("voice_assistant") if isinstance(settings, Mapping) else None
    return section if isinstance(section, Mapping) else {}


def _dead_action(section: str, phrase: str, target: str, known: frozenset[str]) -> Finding:
    canonical = canonical_action(target)
    suggestion = get_close_matches(canonical, sorted(known), n=1, cutoff=0.7)
    hint = f"; did you mean {suggestion[0]!r}?" if suggestion else ""
    return Finding(
        kind="dead_target",
        section=section,
        phrase=phrase,
        target=target,
        message=f"{phrase!r} -> {target!r}: {canonical!r} has no class, so nothing can execute it{hint}",
    )


def _alias_findings(
    alias: str,
    target: str,
    mapping: dict[str, str],
    aliases: dict[str, str],
    repertoire: Repertoire,
) -> list[Finding]:
    """Problems with one alias, judged by the runtime's one-hop rule."""
    if target in mapping:
        # Resolves through `command_map`, and that entry is judged on its own.
        return []

    if repertoire.spec(target) is not None:
        # `aliases: {"sleep": "lie"}` is fine when `lie` is an action; the runtime's raw pass-through
        # finds an action that way, so there is nothing to report.
        return []

    path = [alias, target]
    seen = {alias, target}
    current = target
    while current in aliases:
        current = aliases[current]
        if current in seen:
            path.append(current)
            return [
                Finding(
                    kind="alias_cycle",
                    section="aliases",
                    phrase=alias,
                    target=target,
                    message=(
                        f"{' -> '.join(path)} is a cycle, and the runtime resolves one hop: "
                        f"{alias!r} reaches {target!r} as an action name, which has no class"
                    ),
                )
            ]
        seen.add(current)
        path.append(current)

    return [
        Finding(
            kind="dead_target",
            section="aliases",
            phrase=alias,
            target=target,
            message=(
                f"{alias!r} -> {target!r}: {target!r} is not a command_map key, so the runtime "
                f"passes it through as an action name, and {canonical_action(target)!r} has no class"
            ),
        )
    ]


def _shadowed(mapping: dict[str, str]) -> list[Finding]:
    """Keys that can capture a phrase meant for a longer key, when the two disagree on the action.

    `optional/voice.py:168-170` falls back to "is this key inside what was said", so a short key
    nested in a longer one can award the wrong action. When both spell the same action there is
    nothing to see, and the shipped map is full of those pairs on purpose (`wag` / `wag tail`).
    """
    findings: list[Finding] = []
    for short, short_target in mapping.items():
        for long_key, long_target in mapping.items():
            if short == long_key or short not in long_key:
                continue
            if canonical_action(short_target) == canonical_action(long_target):
                continue
            findings.append(
                Finding(
                    kind="shadowed_key",
                    section="command_map",
                    phrase=long_key,
                    target=long_target,
                    message=(
                        f"{short!r} is inside {long_key!r} but maps to {short_target!r}, not "
                        f"{long_target!r}: the substring fallback can award the wrong action"
                    ),
                )
            )
    return findings


def check(settings: Any) -> list[Finding]:
    """Every finding for a `settings` mapping, errors first."""
    section = _voice_section(settings)
    mapping = _phrase_map(section.get("command_map"))
    aliases = _phrase_map(section.get("aliases"))
    repertoire = repertoire_from_settings(settings)
    known = repertoire.known()

    findings: list[Finding] = []
    for phrase, target in mapping.items():
        if repertoire.spec(target) is None:
            findings.append(_dead_action("command_map", phrase, target, known))
    for alias, target in aliases.items():
        findings.extend(_alias_findings(alias, target, mapping, aliases, repertoire))
    findings.extend(_shadowed(mapping))
    return sorted(findings, key=lambda f: (f.severity != "error", f.kind, f.phrase, f.target))


def validate(settings: Any, as_json: bool = False) -> int:
    """Print the verdict for `settings` and return the exit code."""
    section = _voice_section(settings)
    if not _phrase_map(section.get("command_map")) and not _phrase_map(section.get("aliases")):
        print("no voice_assistant.command_map or aliases in this config; nothing to check")
        return 0

    findings = check(settings)
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = len(findings) - errors

    if as_json:
        print(
            json.dumps(
                {
                    "ok": errors == 0,
                    "errors": errors,
                    "warnings": warnings,
                    "findings": [finding.as_dict() for finding in findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if errors == 0 else 1

    for finding in findings:
        print(f"{finding.severity:7} {finding.kind:12} {finding.message}")
    print(f"\n{errors} error(s), {warnings} warning(s) in voice_assistant.command_map/aliases")
    return 0 if errors == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the voice phrase map offline")
    parser.add_argument("--config", type=str, default=None, help="settings.jsonc to check")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(exc.format())
        return 2
    except OSError as exc:
        print(f"cannot read {args.config}: {exc}")
        return 2

    return validate(config.settings or {}, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())



