"""Motionless smoke test: the runtime runs, the sensors answer, and nothing moves.

`scanning` is in `MOTIONLESS_MODULES` because it drives the head straight through the HAL rather
than through `hal_motors` (`navigation/scanning.py:178-182`) - leaving it enabled is how this tool
swept the head while the guide said nothing could move (#184). `vision_pi4` is here for the same
class of reason: it is the camera module `main.build_registry` actually registers on a Pi 4, so
disabling only `vision` left the camera opening during a run that printed `vision` as off (#205).
The set is a hand-kept copy of that registry, so the run prints the names it really switched off
and calls out any name the config does not declare.
"""

from __future__ import annotations

import argparse
import sys

from houndmind_ai.core.config import load_config
from houndmind_ai.core.instance import BusBusy, RunLock
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.hal.iface import DogHAL
from houndmind_ai.main import build_modules

# Everything that can move the dog: the motor module, the two that scan and walk, the behaviour FSM
# that publishes intent, and the safety stack that reacts to it. `scanning` is here for the reason in
# the module docstring. `mapping` is deliberately absent - it consumes a scan rather than producing
# one, so a motionless run leaves it with nothing to publish rather than with something to move.
MOTIONLESS_MODULES = frozenset(
    {
        "hal_motors",
        "scanning",
        "navigation",
        "behavior",
        "watchdog",
        "safety",
        "vision",
        "vision_pi4",
        "voice",
    }
)


def _disable_modules(config, names: frozenset[str]) -> tuple[list[str], list[str]]:
    """Switch off every name the config declares, and hand back the ones it did not.

    Returns ``(disabled, missing)``. The second list is the point (#205): this set is a hand-kept
    copy of the registrations in `main.build_registry`, so a module can be renamed or added there
    and leave this run motion-capable while it prints a list of things it never touched. That is
    what `vision_pi4` - the module that actually opens the camera on a Pi 4 - was doing while the
    run reported `vision` as disabled in its place.
    """
    disabled: list[str] = []
    missing: list[str] = []
    modules = config.modules
    for name in sorted(names):
        if name not in modules:
            missing.append(name)
            continue
        entry = modules[name]
        if not hasattr(entry, "enabled"):
            missing.append(name)
            continue
        entry.enabled = False
        disabled.append(name)
    return disabled, missing


def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Automated PiDog smoke test: sensors only by default, "
            "plus scan and mapping with --include-motion"
        )
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to settings.jsonc"
    )
    parser.add_argument(
        "--cycles", type=int, default=20, help="Runtime cycles to execute"
    )
    parser.add_argument("--tick-hz", type=int, default=5, help="Runtime tick rate")
    parser.add_argument(
        "--include-motion",
        action="store_true",
        help="Allow navigation/motor actions (default: disabled)",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    config.loop.tick_hz = max(1, int(args.tick_hz))
    config.loop.max_cycles = max(1, int(args.cycles))

    motionless = not args.include_motion
    if motionless:
        disabled, missing = _disable_modules(config, MOTIONLESS_MODULES)
    else:
        disabled, missing = [], []

    # A run against the real dog owns the servo bus, so it takes the one-instance lock (#213). A
    # run handed a fake HAL owns nothing: the test suite passes `hal=`, and it must not touch the
    # home directory or wait on a runtime that is not there.
    lock: RunLock | None = None
    if hal is None:
        lock = RunLock()
        try:
            lock.acquire("smoke_test")
        except BusBusy as exc:
            print(f"[smoke] {exc}", file=sys.stderr)
            print("[smoke] stop it first: systemctl stop houndmind", file=sys.stderr)
            return 3

    try:
        runtime = HoundMindRuntime(config, build_modules(config, hal=hal))
        runtime.run()
    finally:
        if lock is not None:
            lock.release()

    context = runtime.context
    sensor_ok = context.get("sensor_reading") is not None
    scan_ok = context.get("scan_latest") is not None
    mapping_ok = context.get("mapping_openings") is not None

    print("[smoke] sensor_reading:", "OK" if sensor_ok else "MISSING")
    if motionless:
        # Neither key can appear in this mode: `scanning` is off, so no scan exists, and `mapping`
        # publishes from a scan. Printing MISSING would report a fault in a run that is working
        # exactly as designed, and the guide would then have to explain away its own output.
        print("[smoke] scan_latest: SKIPPED (scanning is disabled in the motionless run)")
        print("[smoke] mapping_openings: SKIPPED (nothing to consume without a scan)")
        # What was really switched off, not what the constant hoped for (#205).
        print("[smoke] disabled:", ", ".join(disabled) if disabled else "none")
        if missing:
            print("[smoke] not declared by this config:", ", ".join(missing))
        ok = sensor_ok
    else:
        print("[smoke] scan_latest:", "OK" if scan_ok else "MISSING")
        print("[smoke] mapping_openings:", "OK" if mapping_ok else "MISSING")
        ok = sensor_ok and scan_ok and mapping_ok

    print("[smoke] PASS" if ok else "[smoke] FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

