"""Level the body by trimming the leg servos, measured against the IMU.

Put the dog on a flat hard surface, in its resting pose, and this finds the servo trim that makes it
sit level. Nothing is guessed: for each of the eight leg joints it nudges the joint by a small step,
reads how far the body tipped, nudges it back, and solves the resulting 2x8 system for the trim that
shoulders the tilt.

Two prerequisites, both checked before anything moves:

1. **The IMU must be calibrated** (`python -m tools.imu_calibrate --apply`). This tool trims servos to
   cancel a *body* tilt; with an uncalibrated accelerometer it would cancel the sensor's own offset
   and call the result level (#258, #262).
2. **The trim store must already exist.** A joint with no baseline cannot be merged into, and
   inventing the other seven would be user data nobody measured.

    python -m tools.servo_level            # checks the prerequisites, prints the plan, moves nothing
    python -m tools.servo_level --apply    # probe the joints and save the trim

**`--apply` is what makes it move.** There is no measure-only mode: the measurement *is* a sequence of
small moves. The saves go through `apply_offsets` without a `pose`, so they land on the angles the dog
already holds rather than resetting the legs (#263).
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from houndmind_ai.hal.iface import LEG_SERVO_NAMES, SERVO_OFFSET_LIMIT_DEG

#: Probe step. Large enough to clear IMU noise, small enough that a wrong sign cannot hurt the dog.
PROBE_DEG = 2.0
#: Time for the body to stop swaying after a probe, before the IMU is read.
SETTLE_S = 0.6
#: Reads averaged per measurement.
SAMPLES = 10
#: Stop iterating once the body is this level.
TARGET_DEG = 1.0
#: A trim beyond the vendor's own limit is a mechanical problem, not a calibration.
MAX_TRIM_DEG = SERVO_OFFSET_LIMIT_DEG
#: How far |acc| may sit from 1 g before the IMU is judged uncalibrated.
ACC_TOLERANCE_G = 0.15


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def clamp_deg(value: float, limit: float = MAX_TRIM_DEG) -> float:
    return max(-limit, min(limit, value))


def read_tilt(
    hal: Any,
    samples: int = SAMPLES,
    sleep: Callable[[float], None] = time.sleep,
    between_s: float = 0.05,
) -> tuple[float, float] | None:
    """Mean (roll, pitch) in degrees, or None when the IMU does not answer."""
    rolls: list[float] = []
    pitches: list[float] = []
    for _ in range(max(1, samples)):
        snapshot = hal.read()
        if getattr(snapshot, "imu_valid", False):
            roll = getattr(snapshot, "roll_deg", None)
            pitch = getattr(snapshot, "pitch_deg", None)
            if roll is not None and pitch is not None:
                rolls.append(_safe_float(roll, 0.0))
                pitches.append(_safe_float(pitch, 0.0))
        sleep(between_s)
    if not rolls:
        return None
    return (sum(rolls) / len(rolls), sum(pitches) / len(pitches))


def trim_solution(
    jacobian: Sequence[tuple[float, float]],
    error: tuple[float, float],
    damping: float = 1e-3,
) -> list[float]:
    """Minimum-norm trim that shoulders `error`, from one column per joint.

    Eight joints and two measurements make the system underdetermined, so the minimum-norm solution is
    the one that spreads the correction instead of dumping it on a single servo. `damping` keeps a
    joint that moved nothing from producing a wild number.
    """
    a11 = sum(column[0] * column[0] for column in jacobian) + damping
    a12 = sum(column[0] * column[1] for column in jacobian)
    a22 = sum(column[1] * column[1] for column in jacobian) + damping
    determinant = a11 * a22 - a12 * a12
    if not jacobian or abs(determinant) < 1e-9:
        return [0.0] * len(jacobian)
    bx, by = -error[0], -error[1]
    x = (a22 * bx - a12 * by) / determinant
    y = (-a12 * bx + a11 * by) / determinant
    return [column[0] * x + column[1] * y for column in jacobian]


def next_offsets(
    current: Mapping[str, float],
    trim: Sequence[float],
    names: Sequence[str] = LEG_SERVO_NAMES,
    limit: float = MAX_TRIM_DEG,
) -> dict[str, float]:
    """The current trim shifted by `trim`, clamped to the vendor's own limit."""
    return {
        name: clamp_deg(_safe_float(current.get(name), 0.0) + delta, limit)
        for name, delta in zip(names, trim, strict=True)
    }


def probe_joint(
    hal: Any,
    name: str,
    probe_deg: float,
    settle_s: float,
    samples: int,
    sleep: Callable[[float], None],
) -> tuple[float, float] | None:
    """Tip the body by `probe_deg` at one joint and measure the tilt per degree, then undo it."""
    before = read_tilt(hal, samples, sleep)
    if before is None:
        return None
    hal.nudge_joint(name, probe_deg)
    sleep(settle_s)
    after = read_tilt(hal, samples, sleep)
    hal.nudge_joint(name, -probe_deg)
    sleep(settle_s)
    if after is None:
        return None
    return ((after[0] - before[0]) / probe_deg, (after[1] - before[1]) / probe_deg)


def prerequisite_problem(hal: Any) -> str | None:
    """Why leveling must not run yet, or None when it may."""
    from tools.imu_calibrate import magnitude_g

    calibration = hal.read_imu_calibration()
    if not calibration:
        return (
            "the IMU has no calibration; run `python -m tools.imu_calibrate --apply` first - "
            "leveling against an uncalibrated accelerometer would cancel the sensor's own offset"
        )
    snapshot = hal.read()
    if not getattr(snapshot, "imu_valid", False):
        return "the IMU did not answer; nothing can be measured"
    acc = getattr(snapshot, "acc", None)
    if acc is not None:
        magnitude = magnitude_g(acc)
        if abs(magnitude - 1.0) > ACC_TOLERANCE_G:
            return (
                f"|acc| reads {magnitude:.2f} g instead of 1.00 g; re-run "
                "`python -m tools.imu_calibrate --apply` before trimming servos against it"
            )
    offsets = hal.read_offsets()
    missing = [name for name in LEG_SERVO_NAMES if name not in offsets]
    if missing:
        return (
            f"{len(missing)} leg joints have no stored trim ({', '.join(missing[:3])}...); run "
            "`python -m tools.calibrate_servos` first so there is a baseline to merge into"
        )
    return None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.servo_level",
        description="Measure and save the leg trim that makes the dog sit level",
    )
    parser.add_argument("--apply", action="store_true", help="probe the joints and save the trim")
    parser.add_argument("--iterations", type=int, default=3, help="measure-and-trim passes")
    parser.add_argument("--probe-deg", type=float, default=PROBE_DEG, help="probe step per joint")
    parser.add_argument("--settle", type=float, default=SETTLE_S, help="seconds to settle")
    parser.add_argument("--samples", type=int, default=SAMPLES, help="IMU reads per measurement")
    parser.add_argument("--target", type=float, default=TARGET_DEG, help="level enough, in degrees")
    parser.add_argument("--max-trim", type=float, default=MAX_TRIM_DEG, help="refuse beyond this")
    args = parser.parse_args(argv)
    return args


def _run(hal: Any, args: argparse.Namespace, sleep: Callable[[float], None]) -> int:
    problem = prerequisite_problem(hal)
    if problem is not None:
        print(f"[level] refusing: {problem}")
        return 1

    offsets = hal.read_offsets()
    tilt = read_tilt(hal, args.samples, sleep)
    if tilt is None:
        print("[level] the IMU stopped answering; nothing measured")
        return 1
    print(f"[level] tilt now: roll {tilt[0]:+.1f} deg, pitch {tilt[1]:+.1f} deg")
    print(f"[level] trim now: {', '.join(f'{offsets[n]:+.1f}' for n in LEG_SERVO_NAMES)}")

    if not args.apply:
        nudges = len(LEG_SERVO_NAMES) * 2 * max(1, args.iterations)
        print(
            f"[level] dry run: {len(LEG_SERVO_NAMES)} joints per pass, {args.probe_deg:.1f} deg out "
            f"and back, up to {nudges} nudges over {args.iterations} passes. Nothing moved."
        )
        print("[level] re-run with --apply to probe and save")
        return 0

    nudges = len(LEG_SERVO_NAMES) * 2 * max(1, args.iterations)
    print(
        f"[level] moving: {nudges} nudges of {args.probe_deg:.1f} deg at speed 30, one joint at "
        "a time. Keep clear of the dog."
    )

    for iteration in range(1, max(1, args.iterations) + 1):
        tilt = read_tilt(hal, args.samples, sleep)
        if tilt is None:
            print("[level] lost the IMU; the trim is unchanged")
            return 1
        if abs(tilt[0]) <= args.target and abs(tilt[1]) <= args.target:
            print(f"[level] pass {iteration}: within {args.target:.1f} deg already, stopping")
            break

        jacobian: list[tuple[float, float]] = []
        for name in LEG_SERVO_NAMES:
            column = probe_joint(hal, name, args.probe_deg, args.settle, args.samples, sleep)
            if column is None:
                print(f"[level] lost the IMU while probing {name}; the trim is unchanged")
                return 1
            jacobian.append(column)

        trim = trim_solution(jacobian, tilt)
        biggest = max(abs(value) for value in trim)
        if biggest > args.max_trim:
            print(
                f"[level] refusing: the solve wants {biggest:.1f} deg at one joint, over the "
                f"{args.max_trim:.0f} deg limit. That is a mechanical problem, not a trim."
            )
            return 1

        offsets = next_offsets(offsets, trim, limit=args.max_trim)
        hal.apply_offsets(dict(offsets))
        after = read_tilt(hal, args.samples, sleep)
        if after is None:
            print("[level] lost the IMU after saving; check `python -m tools.hardware_checkup`")
            return 1
        print(
            f"[level] pass {iteration}: roll {tilt[0]:+.1f} -> {after[0]:+.1f}, "
            f"pitch {tilt[1]:+.1f} -> {after[1]:+.1f}"
        )

    print("[level] final trim:")
    for name in LEG_SERVO_NAMES:
        print(f"[level]   {name:<12} {offsets[name]:+6.1f} deg")
    return 0


def main(
    argv: list[str] | None = None,
    hal: Any = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Probe and level the dog. `hal` is the injection seam.

    A HAL this tool opened is this tool's to **start and close**: `start()` opens the dog, and a
    missing `close()` leaves the vendor's sensor threads holding the GPIO pins, so the next run
    reports `GPIO busy` and loses the sound sensor (seen on the dog, 2026-11-17).
    """
    args = _parse_args(argv)
    owned = hal is None
    if hal is None:
        from houndmind_ai.hal.vendor import PidogHAL

        vendor_hal = PidogHAL(settings={})
        try:
            vendor_hal.start()
        except Exception as exc:  # noqa: BLE001 - a missing vendor package is the report
            print(f"[level] pidog unavailable: {exc}", file=sys.stderr)
            return 2
        hal = vendor_hal
    try:
        return _run(hal, args, sleep)
    finally:
        if owned:
            try:
                hal.close()
            except Exception:  # noqa: BLE001 - nothing left to recover at exit
                print("[level] close failed", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
