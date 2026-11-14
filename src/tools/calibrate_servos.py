"""Servo trim: read it, adjust it, and save it through the HAL.

`settings.calibration.request: "servo_zero"` only *reads* the trim the dog already has
(`hal/iface.py::DogHAL.read_offsets`), and `auto_apply_servo_offsets` replays what was read. Until
this tool nothing in HoundMind could measure or save a trim, so every install needed the vendor's
interactive script - outside the HAL and outside any test (#142).

Three modes, and the default writes nothing:

- no arguments: print the 12 joints and the offset loaded for each;
- `--set joint=deg` (repeatable): print the list that *would* be written, then exit 0;
- `--set ... --apply`: save it through `DogHAL.apply_offsets`, which merges over the loaded values,
  clamps to `SERVO_OFFSET_LIMIT_DEG` and never re-poses the dog.

Saving a trim is not a move. There is deliberately no interactive preview: nudging a servo while
trimming needs a raw per-group angle write, and that primitive belongs to `act/interlock.py` alone.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping

from houndmind_ai.hal.iface import (
    SERVO_GROUPS,
    SERVO_NAMES,
    SERVO_OFFSET_LIMIT_DEG,
    DogHAL,
)

__all__ = ["describe_offsets", "main", "parse_set"]


def parse_set(pairs: list[str]) -> dict[str, float]:
    """Turn `joint=degrees` pairs into a mapping, or raise `ValueError` naming the offender."""
    values: dict[str, float] = {}
    for pair in pairs:
        name, separator, raw = pair.partition("=")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"expected JOINT=DEGREES, got {pair!r}")
        if name not in SERVO_NAMES:
            raise ValueError(f"unknown joint {name!r}; the joints are {', '.join(SERVO_NAMES)}")
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(f"{name}: {raw.strip()!r} is not a number") from None
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{name}: {raw.strip()!r} is not a finite number")
        values[name] = value
    return values


def _clamp(value: float) -> float:
    return max(-SERVO_OFFSET_LIMIT_DEG, min(SERVO_OFFSET_LIMIT_DEG, value))


def describe_offsets(
    current: Mapping[str, float], proposed: Mapping[str, float]
) -> list[str]:
    """One line per joint, in the vendor's group order, with what would be saved."""
    lines = ["[tune] joint        current  proposed"]
    for group, names in SERVO_GROUPS.items():
        lines.append(f"[tune] {group}")
        for name in names:
            now = current.get(name)
            after = proposed.get(name)
            # A joint the HAL could not read is absent, never 0.0: "not measured" is not
            # "measured straight" (`hal/iface.py::DogHAL.read_offsets`).
            now_text = f"{now:+.1f}" if now is not None else "unread"
            after_text = f"{after:+.1f}" if after is not None else "unread"
            marker = "" if now == after else "  <- set"
            lines.append(f"[tune]   {name:<12} {now_text:>8} {after_text:>9}{marker}")
    return lines



def _run(hal: DogHAL, requested: Mapping[str, float], apply: bool) -> int:
    current = hal.read_offsets()
    if not current:
        print(
            "[tune] the hardware reported no servo offsets; nothing to read or save",
            file=sys.stderr,
        )
        return 2

    proposed = dict(current)
    for name, value in requested.items():
        if name not in current:
            # `apply_offsets` refuses a joint with no baseline, because saving its group would
            # invent the other values in that vendor list.
            print(
                f"[tune] {name}: the dog reported no current value, so it will not be written",
                file=sys.stderr,
            )
            continue
        proposed[name] = _clamp(value)

    for line in describe_offsets(current, proposed):
        print(line)

    changed = {name: value for name, value in proposed.items() if value != current.get(name)}
    if not changed:
        print("[tune] nothing to save")
        return 0
    if not apply:
        print(f"[tune] dry run: {len(changed)} joint(s) would change; re-run with --apply to save")
        return 0

    hal.apply_offsets(changed)
    kept = hal.read_offsets()
    unconfirmed = sorted(
        name for name, value in changed.items() if abs(kept.get(name, value) - value) > 1e-6
    )
    print(f"[tune] saved {len(changed) - len(unconfirmed)}/{len(changed)} joint(s)")
    if unconfirmed:
        # A silent no-op is the failure #142 is about: the vendor save is logged, not raised, so
        # the tool has to read the hardware back to know whether anything stuck.
        print(f"[tune] the hardware did not keep: {', '.join(unconfirmed)}", file=sys.stderr)
        return 1
    return 0



def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    """Read, adjust and (with `--apply`) save the trim. `hal` is the injection seam."""
    parser = argparse.ArgumentParser(
        description="PiDog servo trim: read it, adjust it, save it through the HAL (dry by default)"
    )
    parser.add_argument(
        "--set",
        metavar="JOINT=DEG",
        action="append",
        default=[],
        help=f"offset for one joint, repeatable; clamped to +/-{SERVO_OFFSET_LIMIT_DEG:.0f} degrees",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="save the result; without this flag nothing is written",
    )
    args = parser.parse_args(argv)

    try:
        requested = parse_set(args.set)
    except ValueError as exc:
        print(f"[tune] {exc}", file=sys.stderr)
        return 2

    owned = hal is None
    if hal is None:
        # Imported here, not at module scope: the vendor package is only needed on a dog, and a
        # missing one must read as a reportable failure rather than an import traceback.
        from houndmind_ai.hal.vendor import PidogHAL

        vendor_hal = PidogHAL()
        try:
            vendor_hal.start()
        except Exception as exc:  # noqa: BLE001 - a missing vendor package is the report
            print(f"[tune] pidog unavailable: {exc}", file=sys.stderr)
            return 2
        hal = vendor_hal

    try:
        return _run(hal, requested, args.apply)
    finally:
        # Only a HAL this tool opened is the tool's to close; an injected fake belongs to its test.
        if owned:
            try:
                hal.close()
            except Exception:  # noqa: BLE001 - nothing left to recover at exit
                print("[tune] close failed", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
