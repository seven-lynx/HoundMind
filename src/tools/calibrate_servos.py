"""Servo trim: read it, adjust it, and save it through the HAL.

`settings.calibration.request: "servo_zero"` only *reads* the trim the dog already has
(`hal/iface.py::DogHAL.read_offsets`), and `auto_apply_servo_offsets` replays what was read. Until
this tool nothing in HoundMind could measure or save a trim, so every install needed the vendor's
interactive script - outside the HAL and outside any test (#142).

Four modes, and the default writes nothing:

- no arguments: print the 12 joints and the offset loaded for each;
- `--set joint=deg` (repeatable): print the list that *would* be written, then exit 0;
- `--set ... --apply`: save it through `DogHAL.apply_offsets`, which merges over the loaded values,
  clamps to `SERVO_OFFSET_LIMIT_DEG` and lands on the pose the dog is already in;
- `--interactive`: walk the joints one at a time, stepping the trim with the arrow keys and watching
  the dog until each one looks straight. **This mode moves the dog** - it is the only one that does,
  and it says so before it starts.

The preview used to be refused here on the grounds that nudging a servo belongs to
`act/interlock.py` alone. That is true of the *runtime*; a calibration tool is not a gait. What the
preview needs instead is a primitive that cannot become one: `DogHAL.nudge_joint` moves a single joint
by at most `NUDGE_LIMIT_DEG` at calibration speed, writes no trim of its own, and is called by nothing
that ticks. `--interactive` additionally refuses to start while the runtime is running, because two
writers on twelve servos is not a calibration.

The vendor's own `examples/0_calibration.py` is GPL-2.0-only and this tree is GPL-3.0 (#259), so this
pass is a reimplementation against `DogHAL`, not a copy.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from houndmind_ai.hal.iface import (
    SERVO_GROUP_OF,
    SERVO_GROUPS,
    SERVO_NAMES,
    SERVO_OFFSET_LIMIT_DEG,
    DogHAL,
)

__all__ = ["TerminalKeys", "describe_offsets", "main", "parse_set"]

#: One arrow press. The vendor's own script steps 0.44 deg, which is fine enough to see and coarse
#: enough to reach 5 deg in a dozen presses.
INTERACTIVE_STEP_DEG = 0.44

#: Right arrow arrives as ESC [ C, left as ESC [ D; the letters are there for keyboards that swallow
#: escape sequences (a serial console, a terminal in vi mode).
_INCREASE_KEYS = frozenset({"\x1b[C", "+", "=", "d", "D"})
_DECREASE_KEYS = frozenset({"\x1b[D", "-", "_", "a", "A"})
_ACCEPT_KEYS = frozenset({"\r", "\n", " "})
_SKIP_KEYS = frozenset({"s", "S"})
_QUIT_KEYS = frozenset({"q", "Q"})



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



class TerminalKeys:
    """One keystroke at a time from a POSIX terminal, with the terminal restored on exit."""

    def __init__(self, stream: Any = None) -> None:
        self._stream = stream if stream is not None else sys.stdin
        self._fd: int | None = None
        self._saved: Any = None

    def __enter__(self) -> TerminalKeys:
        try:
            import termios
            import tty
        except ImportError as exc:  # pragma: no cover - the Pi has it; a workstation may not
            raise RuntimeError("interactive trim needs a POSIX terminal (termios)") from exc
        try:
            self._fd = self._stream.fileno()
            self._saved = termios.tcgetattr(self._fd)  # type: ignore[attr-defined]
        except (AttributeError, OSError) as exc:
            raise RuntimeError("stdin is not a terminal; run this on the dog") from exc
        # `termios` and `tty` are POSIX-only, so the stubs mypy resolves off a Linux host lack these.
        tty.setcbreak(self._fd)  # type: ignore[attr-defined]
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._fd is None or self._saved is None:
            return
        import termios

        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)  # type: ignore[attr-defined]

    def read(self) -> str:
        char = self._stream.read(1)
        if char == "\x1b":
            # An arrow key is ESC then "[C" or "[D". A bare ESC would block here, which is why
            # quitting is `q` rather than ESC.
            char += self._stream.read(2)
        return char


def runtime_running(host: str = "127.0.0.1", port: int = 8420, timeout: float = 0.3) -> bool:
    """True when the control plane answers: the runtime is up and owns the servos."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _restore(hal: DogHAL, original: Mapping[str, float], touched: Sequence[str]) -> None:
    """Put back every joint this pass changed, so an abort is not a half-applied trim."""
    for name in touched:
        try:
            hal.apply_offsets({name: original[name]})
        except Exception:  # noqa: BLE001 - nothing else is left to try at this point
            print(f"[tune] could not restore {name}", file=sys.stderr)


def _interactive(
    hal: DogHAL,
    read_key: Callable[[], str],
    joints: Sequence[str],
    step: float,
) -> int:
    """Walk the joints one at a time. Every press is written, so an abort undoes what it changed."""
    current = hal.read_offsets()
    if not current:
        print(
            "[tune] the hardware reported no servo offsets; nothing to trim",
            file=sys.stderr,
        )
        return 2

    selected = [name for name in joints if name in current]
    for name in joints:
        if name not in current:
            # `apply_offsets` refuses a joint with no baseline, so there is nothing to step here.
            print(f"[tune] {name}: no current value from the hardware, skipping", file=sys.stderr)
    if not selected:
        print("[tune] nothing trimmable", file=sys.stderr)
        return 2

    print(
        f"[tune] interactive trim, {len(selected)} joint(s), {step:.2f} deg per press.\n"
        "[tune] right or + raises, left or - lowers, Enter accepts, s skips, q quits and undoes.\n"
        "[tune] each press is written to the dog as you make it. Keep clear of it."
    )

    proposed = dict(current)
    # What each joint was last written to. A joint is only "touched" once a step has been saved,
    # and a skip has to walk it back if the operator stepped it first.
    touched: dict[str, float] = {}
    for index, name in enumerate(selected, start=1):
        value = current[name]
        group = SERVO_GROUP_OF.get(name, "?")
        print(f"\n[tune] {index}/{len(selected)}  {name} ({group})  now {value:+.2f}")
        while True:
            key = read_key()
            if key in _QUIT_KEYS:
                print("\n[tune] quitting; restoring what this pass changed")
                _restore(hal, current, list(touched))
                return 2
            if key in _ACCEPT_KEYS:
                break
            if key in _SKIP_KEYS:
                value = current[name]
                print(f"\r[tune]   {name} {value:+.2f} deg (unchanged)   ")
                break
            if key in _INCREASE_KEYS:
                value = _clamp(value + step)
            elif key in _DECREASE_KEYS:
                value = _clamp(value - step)
            else:
                continue
            print(f"\r[tune]   {name} {value:+.2f} deg   ", end="", flush=True)
            # The write is the preview: the servo moves with it, which is what makes the pass useful.
            hal.apply_offsets({name: value})
            touched[name] = value
        if name in touched and touched[name] != value:
            hal.apply_offsets({name: value})
            touched[name] = value
        if value == current[name]:
            # Walked home or skipped: the trim is where it started, so there is nothing to report.
            touched.pop(name, None)
        proposed[name] = value
        print()

    if not touched:
        print("[tune] nothing changed")
        return 0

    kept = hal.read_offsets()
    unconfirmed = sorted(
        name for name in touched if abs(kept.get(name, proposed[name]) - proposed[name]) > 1e-6
    )
    print(f"[tune] trimmed {len(touched)} joint(s):")
    for name in touched:
        print(f"[tune]   {name:<12} {current[name]:+6.2f} -> {proposed[name]:+6.2f}")
    if unconfirmed:
        print(f"[tune] the hardware did not keep: {', '.join(unconfirmed)}", file=sys.stderr)
        return 1
    return 0


def main(
    argv: list[str] | None = None,
    hal: DogHAL | None = None,
    read_key: Callable[[], str] | None = None,
    runtime_up: Callable[[], bool] | None = None,
) -> int:
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
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="walk the joints by hand with the arrow keys; this moves the dog",
    )
    parser.add_argument(
        "--only",
        metavar="JOINT",
        action="append",
        default=[],
        help=f"restrict --interactive to one joint, repeatable; defaults to all {len(SERVO_NAMES)}",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=INTERACTIVE_STEP_DEG,
        help=f"degrees per keypress in --interactive (default {INTERACTIVE_STEP_DEG})",
    )
    args = parser.parse_args(argv)

    if args.interactive and args.set:
        print("[tune] --interactive and --set are different passes; choose one", file=sys.stderr)
        return 2

    joints = list(SERVO_NAMES)
    if args.only:
        unknown = [name for name in args.only if name not in SERVO_NAMES]
        if unknown:
            print(f"[tune] unknown joint(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        joints = list(dict.fromkeys(args.only))

    if args.interactive:
        checker = runtime_up if runtime_up is not None else runtime_running
        if checker():
            print(
                "[tune] the control plane is answering on 127.0.0.1:8420, so the runtime owns the "
                "servos; stop the houndmind service before trimming",
                file=sys.stderr,
            )
            return 2

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
        if not args.interactive:
            return _run(hal, requested, args.apply)
        if read_key is not None:
            return _interactive(hal, read_key, joints, args.step)
        try:
            with TerminalKeys() as keys:
                return _interactive(hal, keys.read, joints, args.step)
        except RuntimeError as exc:
            print(f"[tune] {exc}", file=sys.stderr)
            return 2
    finally:
        # Only a HAL this tool opened is the tool's to close; an injected fake belongs to its test.
        if owned:
            try:
                hal.close()
            except Exception:  # noqa: BLE001 - nothing left to recover at exit
                print("[tune] close failed", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
