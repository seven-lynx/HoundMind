#!/usr/bin/env python3
"""Check a settings file against the schema the runtime loads it with.

A config the loader refuses is a runtime that does not start, and the two ways to find out were to
boot the dog or to PATCH a live one. Neither is available on a workstation, and `python -m
houndmind_ai --dry-run` answers it only by importing the whole runtime. This tool asks the schema
directly: it parses the file the way `core/config.py::_load_jsonc` does, runs
`kernel/config_schema.py::validate_config_tree` - the call `load_config` makes before it resolves a
profile (`core/config.py:183`) - and prints every problem with the key it was found on.

What this is not: route parity. `POST /api/v1/config/validate` validates one PATCH **body** through
`_check_config_update` -> `validate_settings_section`, one section at a time
(`kernel/config_schema.py:1398`). A whole file goes `load_config` -> `validate_config_tree`, then
through the profile overrides and `validate_config`'s cross-field rules (`core/config.py:288`). That
is the path walked here, so a clean exit means "the runtime would start from this file" - on this
host's profile, because the profile is part of the answer.

Usage:
    python -m tools.validate_config
    python -m tools.validate_config --config bench-settings.jsonc
    python -m tools.validate_config --json

Exit codes: `0` the file would load (warnings are printed and still exit `0`), `1` the schema or the
loader refused it (every problem is named, key by key), `2` the file is missing, unreadable or does
not parse - the question could not be asked, which is not the same answer as "it has findings".
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import json5

from houndmind_ai.core.config import default_config_path, load_config, validate_config
from houndmind_ai.kernel.config_schema import ConfigError, Problem, validate_config_tree

__all__ = ["Finding", "check", "main", "validate"]

# Findings that are printed but leave the exit code alone: `validate_config`'s cross-field notes are
# advice about values the schema accepts, so a file can be legal and still carry them.
_WARNING_KINDS = frozenset({"warning"})


@dataclass(frozen=True)
class Finding:
    """One thing the schema or the loader objects to, and the key it objects to."""

    kind: str
    path: str | None
    message: str
    hint: str | None = None

    @property
    def severity(self) -> str:
        return "warning" if self.kind in _WARNING_KINDS else "error"

    def rendered(self) -> str:
        """The line a human reads, in `Problem.__str__`'s shape (`config_schema.py:53`)."""
        if not self.path:
            return self.message
        suffix = f" (did you mean '{self.hint}'?)" if self.hint else ""
        return f"{self.path}: {self.message}{suffix}"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "path": self.path,
            "message": self.message,
            "hint": self.hint,
        }


def _invalid(problem: Problem) -> Finding:
    return Finding(kind="invalid", path=problem.path, message=problem.message, hint=problem.hint)


def check(raw: Any) -> list[Finding]:
    """Every problem `kernel/config_schema.py` finds in a parsed settings tree.

    `validate_config_tree` is the loader's own first step (`core/config.py:183`) and its specs are
    the ones the live-config route reuses, so a problem here is a problem at every door this file
    is opened through.
    """
    return [_invalid(problem) for problem in validate_config_tree(raw)]


def _parse(path: Path) -> Any:
    """Parse the file the way `core/config.py::_load_jsonc` does: utf-8, `json5`, path in the error.

    `json.loads` is not an option - the shipped file is JSONC - and a hand-rolled comment stripper
    would be a second parser to keep true to the first (`config.py:99-111`).
    """
    try:
        return json5.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        # `UnicodeDecodeError` is a `ValueError` too, and "this is not the text it claims to be"
        # earns the same answer as a stray brace: unreadable, not "it has findings".
        raise ValueError(f"{path}: {exc}") from exc


def _payload(findings: list[Finding], warnings: list[Finding]) -> dict[str, Any]:
    return {
        "ok": not findings,
        "errors": len(findings),
        "warnings": len(warnings),
        "findings": [finding.as_dict() for finding in findings + warnings],
    }


def _fail(kind: str, message: str, as_json: bool, path: Path) -> int:
    """Report a file that could not be read or parsed, and exit `2`.

    A traceback would be indistinguishable from a refusal, and a consumer that asked for JSON still
    gets JSON: the answer is "the question could not be asked", not "here are the findings".
    """
    if as_json:
        payload = _payload([Finding(kind=kind, path=str(path), message=message)], [])
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{kind}: {message}")
    return 2


def _report(findings: list[Finding], warnings: list[Finding], as_json: bool, path: Path) -> int:
    if as_json:
        print(json.dumps(_payload(findings, warnings), indent=2, sort_keys=True))
        return 1 if findings else 0
    for finding in findings + warnings:
        print(f"{finding.severity:7} {finding.kind:8} {finding.rendered()}")
    print(f"\n{len(findings)} error(s), {len(warnings)} warning(s) in {path}")
    return 1 if findings else 0


def validate(path: Path, as_json: bool = False) -> int:
    """Print the verdict for the file at `path` and return the exit code."""
    try:
        raw = _parse(path)
    except OSError as exc:
        return _fail("unreadable", f"cannot read {path}: {exc}", as_json, path)
    except ValueError as exc:
        return _fail("unparsable", str(exc), as_json, path)

    findings = check(raw)
    warnings: list[Finding] = []
    if not findings:
        # The tree is legal, so the loader can be asked the rest: the profile (which overrides
        # sections, so the warnings depend on it), the action catalog beside the file, and the
        # cross-field rules that need a built `Config`.
        try:
            config = load_config(path)
        except ConfigError as exc:
            findings = [_invalid(problem) for problem in exc.problems] or [
                Finding(kind="invalid", path=None, message=exc.format())
            ]
        except ValueError as exc:
            # A malformed `behavior.actions_file`: the message already names that file.
            return _fail("unparsable", str(exc), as_json, path)
        except OSError as exc:
            return _fail("unreadable", f"cannot read {path}: {exc}", as_json, path)
        else:
            warnings = [
                Finding(kind="warning", path=None, message=message)
                for message in validate_config(config)
            ]
    return _report(findings, warnings, as_json, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check a settings file against the schema the runtime loads it with"
    )
    parser.add_argument("--config", type=str, default=None, help="settings.jsonc to check")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of lines")
    args = parser.parse_args(argv)

    path = Path(args.config) if args.config else default_config_path()
    return validate(path, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
