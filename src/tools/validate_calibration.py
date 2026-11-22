#!/usr/bin/env python3
"""Check the saved servo trim without starting the runtime (VD2, #258, #259).

`calibration/workflow.py:170-183` writes `data/calibration.json` and `hal/motors.py:606-622` applies it
at boot when the config carries no offsets of its own. Nothing between them checks the file: the reader
wraps its whole body in `except Exception` and logs at debug, so a payload of the wrong shape and an
uncalibrated dog look exactly alike — the dog stands crooked and nothing says why.

What this tool reads is what that reader reads: `last_result.servo_zero_offsets`, not a top-level map.
A payload with no `last_result` is a finding, not a clean pass, because the workflow always writes one
(`workflow.py:176`) and a file without it is not a calibration file at all.

A partial map is legal. `hal/iface.py:238-245` makes a joint whose value could not be read *absent*
rather than `0.0`, so fewer than the twelve names in `SERVO_NAMES` is a note and not a finding — "not
measured" is not "measured straight". An unknown channel, a value that is not a number, and an offset
beyond `SERVO_OFFSET_LIMIT_DEG` (20.0, the clamp the vendor applies itself, `iface.py:85-87`) are
findings, each naming the channel.

The offsets in this file are what the owner measured with `calibrate_servos`, so the file is read and
never written: repairing a trim is a measurement, not a text edit.

Usage:
    python -m tools.validate_calibration
    python -m tools.validate_calibration --file bench-calibration.json
    python -m tools.validate_calibration --config bench-settings.jsonc --json

Exit codes: `0` the trim is consistent, or the file does not exist (that is a note, because an
uncalibrated dog is legal), `1` at least one finding, `2` the config would not load or the file could
not be read.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from houndmind_ai.core.config import load_config
from houndmind_ai.hal.iface import SERVO_NAMES, SERVO_OFFSET_LIMIT_DEG, as_float
from houndmind_ai.kernel.config_schema import ConfigError

__all__ = ["Finding", "calibration_path", "check", "main", "validate"]

_DEFAULT_PERSIST_PATH = "data/calibration.json"

# `calibration/workflow.py:174-175` and `hal/motors.py:612-613` resolve a relative `persist_path`
# against the repository root, three levels above their own file (`src/houndmind_ai/calibration/`,
# `src/houndmind_ai/hal/`). This tool sits one directory shallower, so the same root is two levels up.
# Resolving against the CWD instead would call a calibrated dog uncalibrated from anywhere else.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Findings that describe a legal state rather than a defect: printed, and they do not set the exit
# code. An uncalibrated dog and a half-read trim both work; only a payload nothing can apply does not.
_NOTE_KINDS = frozenset({"not_calibrated", "no_servo_trim", "partial_trim"})

_CHANNEL_WIDTH = max(len(name) for name in SERVO_NAMES) + 1


@dataclass(frozen=True)
class Finding:
    """One thing wrong with the saved trim, and the channel it was found on."""

    kind: str
    channel: str
    message: str

    @property
    def severity(self) -> str:
        return "note" if self.kind in _NOTE_KINDS else "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "channel": self.channel,
            "message": self.message,
        }


def _last_result(payload: Any) -> Mapping[str, Any] | None:
    """`payload.last_result` — the envelope `calibration/workflow.py:176` writes."""
    if not isinstance(payload, Mapping):
        return None
    section = payload.get("last_result")
    return section if isinstance(section, Mapping) else None


def _offsets(payload: Any) -> Mapping[str, Any]:
    """`last_result.servo_zero_offsets` — the only key `hal/motors.py:618` reads."""
    section = _last_result(payload)
    if section is None:
        return {}
    raw = section.get("servo_zero_offsets")
    return raw if isinstance(raw, Mapping) else {}


def _offset(value: Any) -> float | None:
    """The value as a signed number of degrees, or None when it is not one.

    `as_float` is the boundary coercion the HAL itself uses, so a numeric string reads the way
    `apply_offsets` would read it. `bool` is refused before it gets there: JSON `true` would arrive as
    `1.0` and look like a measured degree.
    """
    if isinstance(value, bool):
        return None
    coerced = as_float(value, math.nan)
    return None if math.isnan(coerced) else coerced


def check(
    payload: Any,
    names: Sequence[str] = SERVO_NAMES,
    limit: float = SERVO_OFFSET_LIMIT_DEG,
) -> list[Finding]:
    """Every finding for a persisted payload, errors first.

    `names` is the HAL's channel list and `limit` its clamp; both are injected so a test can judge a
    payload against a shorter list without the tool growing a second channel table.
    """
    known = tuple(names)
    section = _last_result(payload)
    if section is None:
        return [
            Finding(
                kind="missing_section",
                channel="",
                message=(
                    "no last_result object: calibration/workflow.py:176 always writes one, so nothing "
                    "the workflow wrote looks like this and hal/motors.py:618 reads nothing from it"
                ),
            )
        ]

    raw = section.get("servo_zero_offsets")
    if not isinstance(raw, Mapping):
        request = section.get("request", "unknown")
        return [
            Finding(
                kind="no_servo_trim",
                channel="",
                message=(
                    f"last_result is a {request!r} run and carries no servo_zero_offsets: there is "
                    f"no trim in this file to check"
                ),
            )
        ]

    findings: list[Finding] = []
    for name, value in raw.items():
        channel = str(name)
        if channel not in known:
            suggestion = get_close_matches(channel, list(known), n=1, cutoff=0.7)
            hint = f"; did you mean {suggestion[0]!r}?" if suggestion else ""
            findings.append(
                Finding(
                    kind="unknown_channel",
                    channel=channel,
                    message=(
                        f"{channel!r} is not a HAL servo channel: hal/motors.py:618 still hands it to "
                        f"apply_offsets and hal/iface.py:254-255 ignores the name{hint}"
                    ),
                )
            )
            continue
        offset = _offset(value)
        if offset is None:
            findings.append(
                Finding(
                    kind="not_numeric",
                    channel=channel,
                    message=f"{channel!r} is {value!r}, which is not a number of degrees",
                )
            )
        elif abs(offset) > limit:
            findings.append(
                Finding(
                    kind="out_of_range",
                    channel=channel,
                    message=(
                        f"{channel!r} is {offset:+.1f} deg, beyond the vendor clamp of "
                        f"+/-{limit:.1f} (hal/iface.py:87): the HAL would save {limit:+.1f} instead"
                    ),
                )
            )

    absent = [name for name in known if name not in raw]
    if absent:
        findings.append(
            Finding(
                kind="partial_trim",
                channel="",
                message=(
                    f"{len(known) - len(absent)} of {len(known)} channels present; absent: "
                    f"{', '.join(absent)}; hal/iface.py:238-245 makes an unreadable joint absent, "
                    f"so this is how a half-read trim looks"
                ),
            )
        )

    return sorted(findings, key=lambda f: (f.severity != "error", f.kind, f.channel))


def calibration_path(settings: Any) -> Path:
    """Where this config says the trim is persisted, resolved the way both readers resolve it.

    `calibration.persist_path` is the key (`config/settings.jsonc:1140`); a relative value is resolved
    against the repository root, never against the CWD (`workflow.py:174-175`, `motors.py:612-613`).
    """
    section = settings.get("calibration") if isinstance(settings, Mapping) else None
    raw = section.get("persist_path") if isinstance(section, Mapping) else None
    path = Path(str(raw or _DEFAULT_PERSIST_PATH)).expanduser()
    return path if path.is_absolute() else _REPO_ROOT / path


def validate(path: Path, as_json: bool = False) -> int:
    """Print the verdict for the file at `path` and return the exit code. Never writes."""
    findings: list[Finding] = []
    present: Mapping[str, Any] = {}

    if not path.exists():
        findings = [
            Finding(
                kind="not_calibrated",
                channel="",
                message=(
                    f"no calibration file at {path}: the dog has no saved trim, which is legal "
                    f"(hal/motors.py:614 returns without applying anything)"
                ),
            )
        ]
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"cannot read {path}: {exc}")
            return 2
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            # The path is right and the bytes are wrong, which is a finding the operator can act on;
            # it is what the boot-time reader swallows as a debug line.
            findings = [
                Finding(kind="malformed_json", channel="", message=f"{path} is not JSON: {exc}")
            ]
        else:
            findings = check(payload)
            present = _offsets(payload)

    errors = sum(1 for finding in findings if finding.severity == "error")
    notes = len(findings) - errors
    # Known channels only: an unknown name is a finding of its own and is not one of the twelve, so
    # counting it would let "12 of 12 present" print over a file that is missing a real joint.
    known_present = sum(1 for name in SERVO_NAMES if name in present)

    if as_json:
        # Even an empty answer is JSON: a consumer that parses this must not get prose for the one
        # file that is missing.
        print(
            json.dumps(
                {
                    "ok": errors == 0,
                    "path": str(path),
                    "channels": known_present,
                    "errors": errors,
                    "notes": notes,
                    "findings": [finding.as_dict() for finding in findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if errors == 0 else 1

    print(f"file     {path}")
    # The diff against the HAL's own list, in the HAL's order: a channel missing from the middle of
    # the leg sequence is not the same reading as one missing from the end.
    for name in SERVO_NAMES:
        if name not in present:
            if present:
                print(f"absent   {name:<{_CHANNEL_WIDTH}} -")
            continue
        offset = _offset(present[name])
        shown = f"{offset:+.1f} deg" if offset is not None else repr(present[name])
        print(f"present  {name:<{_CHANNEL_WIDTH}} {shown}")
    for finding in findings:
        print(f"{finding.severity:7} {finding.kind:15} {finding.message}")
    print(
        f"\n{errors} error(s), {notes} note(s); "
        f"{known_present} of {len(SERVO_NAMES)} channel(s) present"
    )
    return 0 if errors == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the saved servo trim offline")
    parser.add_argument("--file", type=str, default=None, help="calibration JSON to check")
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="settings.jsonc to read calibration.persist_path from",
    )
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

    settings = config.settings or {}
    path = Path(args.file).expanduser() if args.file else calibration_path(settings)
    return validate(path, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())

