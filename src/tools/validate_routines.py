#!/usr/bin/env python3
"""Validate a routines directory without starting the runtime (#408).

A broken routine used to be found by watching the dog do the wrong thing: the loader quarantines a
file and the runtime boots anyway, which is the right behaviour at boot and the wrong way to learn
about a typo. This tool runs the same loader over the same directory and prints the same refusals,
file by file, so a broken routine is a message instead of a behaviour.

It uses `kernel/routine_store.py::RoutineStore`, not a second validator: the quarantine rule and the
repertoire the runtime is actually using are what make the answer true, and a copy of them would be
a second opinion that can disagree.

Usage:
    python -m tools.validate_routines
    python -m tools.validate_routines --dir ~/.houndmind/routines
    python -m tools.validate_routines --config bench-settings.jsonc --dir ./my-routines

Exit codes: `0` every file loaded, `1` at least one file was refused (each one is printed with its
path and reason), `2` the directory does not exist or the config would not load.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from houndmind_ai.core.config import load_config
from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.config_schema import ConfigError
from houndmind_ai.kernel.routine_store import RoutineStore, routines_dir


def validate(directory: Path, settings: dict | None = None) -> int:
    """Load `directory` the way the runtime does and print the verdict per file."""
    repertoire = repertoire_from_settings(settings or {})
    report = RoutineStore(directory).load(repertoire)

    for routine_id in report.ids():
        print(f"ok       {routine_id}")
    for name, problems in sorted(report.refusals.items()):
        for problem in problems:
            print(f"refused  {name}: {problem.path}: {problem.message}")

    total = len(report.ids()) + report.refused
    if total == 0:
        print(f"no routine files in {directory}")
        return 0
    print(f"\n{len(report.ids())} loaded, {report.refused} refused, {total} file(s) in {directory}")
    return 0 if report.refused == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a routines directory offline")
    parser.add_argument("--dir", type=str, default=None, help="directory to check")
    parser.add_argument("--config", type=str, default=None, help="settings.jsonc to read the repertoire from")
    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config) if args.config else None)
    except ConfigError as exc:
        print(exc.format())
        return 2

    settings = config.settings or {}
    directory = Path(args.dir).expanduser() if args.dir else Path(routines_dir(settings)).expanduser()
    if not directory.is_dir():
        print(f"not a directory: {directory}")
        return 2
    return validate(directory, settings)


if __name__ == "__main__":
    raise SystemExit(main())
