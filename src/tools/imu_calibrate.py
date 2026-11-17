"""Calibrate the IMU by hand: six orientations, then save the measured bias and scale.

Why this exists: the bench dog's `~/.config/pidog/pidog.conf` held no calibration at all, so
`|acc|` read 1.50 g where gravity is 1.00 g (#258) and every angle derived from it - pitch, roll,
the tilt latch - carried the same offset. The sensor must be calibrated before any of that is worth
tuning (#259).

**Nothing here moves the dog.** You rotate it, the tool samples. `--apply` writes through the
vendor's own setters, which persist to `pidog.conf`; nothing else in the runtime calls them.

    python -m tools.imu_calibrate            # measure and print, save nothing
    python -m tools.imu_calibrate --apply    # measure and save
    python -m tools.imu_calibrate --reset    # drop the stored calibration

The method is the vendor's own: rest the dog on each of six faces, and per axis take
``bias = (max + min) / 2`` and ``scale = (max - min) / 2``. The gyro gets a **bias only**: a rate
scale needs a known angular rate, and hand rotation cannot supply one, so claiming one would be the
same kind of unmeasured value #258 was about.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

#: The sensor's sensitivity at the ranges `sh3001_init` configures (`sh3001.py:16-17`).
NOMINAL_ACC_LSB_PER_G = 16384.0
NOMINAL_GYRO_LSB_PER_DPS = 16.4

#: An axis must see at least this much of gravity, or the six poses were not really six poses.
COVERAGE_MIN_G = 0.8

#: The six faces. The order is the vendor's; the labels say what to do, because "rest it on +X"
#: means nothing to a person holding a dog.
ORIENTATIONS: tuple[str, ...] = (
    "nose down, tail up (dog standing on its front)",
    "nose up, tail down (dog standing on its rear)",
    "standing normally, on its feet",
    "upside down, on its back",
    "lying on its left side",
    "lying on its right side",
)

POSE_ORDER = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def to_raw(acc_g: Sequence[float], scale: Sequence[float]) -> list[float]:
    """g back to the counts the calibration is expressed in.

    `hal.read()` publishes g (#258), and the vendor's calibration keys are in LSB per g, so the
    round trip needs the scale the sensor is currently using - the stored one, or the nominal.
    """
    return [
        _safe_float(acc_g[index], 0.0) * _safe_float(scale[index], NOMINAL_ACC_LSB_PER_G)
        for index in range(3)
    ]


def solve(poses: Sequence[Sequence[float]]) -> dict[str, list[float]]:
    """Per-axis bias and scale from the six faces, in LSB and LSB per g."""
    if not poses:
        return {"acc_bias": [0.0, 0.0, 0.0], "acc_scale": [NOMINAL_ACC_LSB_PER_G] * 3}
    bias: list[float] = []
    scale: list[float] = []
    for axis in range(3):
        values = [_safe_float(pose[axis], 0.0) for pose in poses]
        low, high = min(values), max(values)
        bias.append(round((high + low) / 2.0, 3))
        span = (high - low) / 2.0
        # A span of zero means the axis never moved: keep the nominal scale rather than zero it.
        scale.append(round(span if span > 0 else NOMINAL_ACC_LSB_PER_G, 3))
    return {"acc_bias": bias, "acc_scale": scale}


def coverage(poses: Sequence[Sequence[float]]) -> tuple[bool, list[str]]:
    """True when every axis saw at least ``COVERAGE_MIN_G`` of gravity across the poses."""
    if not poses:
        return False, ["no samples"]
    problems: list[str] = []
    for axis, name in enumerate("XYZ"):
        values = [_safe_float(pose[axis], 0.0) for pose in poses]
        span_g = (max(values) - min(values)) / 2.0 / NOMINAL_ACC_LSB_PER_G
        if span_g < COVERAGE_MIN_G:
            problems.append(f"{name} saw {span_g:.2f} g (needs {COVERAGE_MIN_G:.2f})")
    return (not problems), problems


def magnitude_g(acc_g: Sequence[float]) -> float:
    """|acc| in g - 1.00 at rest, and the number that says whether a calibration worked."""
    return sum(_safe_float(value, 0.0) ** 2 for value in acc_g) ** 0.5


def collect(
    hal: Any,
    seconds: float,
    limit: int,
    sleep: Callable[[float], None] = time.sleep,
) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """Read the IMU until `seconds` have passed, or `limit` samples when ``seconds <= 0``."""
    collected: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
    start = time.monotonic()
    attempts = 0
    while len(collected) < limit:
        attempts += 1
        if attempts > limit * 20:  # a dead IMU must not hang the tool
            break
        snapshot = hal.read()
        acc = getattr(snapshot, "acc", None)
        gyro = getattr(snapshot, "gyro", None)
        if getattr(snapshot, "imu_valid", False) and acc is not None and gyro is not None:
            collected.append(
                (
                    (float(acc[0]), float(acc[1]), float(acc[2])),
                    (float(gyro[0]), float(gyro[1]), float(gyro[2])),
                )
            )
        if seconds <= 0.0:
            continue
        if collected and time.monotonic() - start >= seconds:
            break
        sleep(0.1)
    return collected


def _mean(rows: Sequence[Sequence[float]], axis: int) -> float:
    return sum(float(row[axis]) for row in rows) / len(rows)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.imu_calibrate",
        description="Measure and save the IMU calibration (the dog is rotated by hand)",
    )
    parser.add_argument("--apply", action="store_true", help="save what was measured")
    parser.add_argument("--reset", action="store_true", help="drop the stored calibration")
    parser.add_argument("--seconds", type=float, default=2.0, help="sampling time per pose")
    parser.add_argument("--samples", type=int, default=20, help="samples per pose")
    args = parser.parse_args(argv)
    return args


def _run(hal: Any, args: argparse.Namespace, prompt: Callable[[str], str]) -> int:
    if args.reset:
        cleared = bool(hal.reset_imu_calibration())
        print("[imu] stored calibration cleared" if cleared else "[imu] could not clear it")
        return 0 if cleared else 1

    current = hal.read_imu_calibration() or {}
    scale = current.get("acc_scale") or [NOMINAL_ACC_LSB_PER_G] * 3
    current_bias = current.get("acc_bias") or [0.0, 0.0, 0.0]
    print(
        "[imu] current: bias "
        f"{', '.join(f'{value:.1f}' for value in current_bias)} LSB, "
        f"scale {', '.join(f'{value:.0f}' for value in scale)} LSB/g"
        + ("" if current else " (no calibration saved)")
    )

    poses: list[list[float]] = []
    gyros: list[list[float]] = []
    for index, label in enumerate(ORIENTATIONS):
        try:
            prompt(
                f"[imu] pose {index + 1}/{len(ORIENTATIONS)} ({POSE_ORDER[index]}): {label}. "
                "Press Enter when it is still "
            )
        except (EOFError, KeyboardInterrupt):
            print("\n[imu] cancelled; nothing saved")
            return 1
        samples = collect(hal, args.seconds, max(1, args.samples))
        if not samples:
            print(f"[imu] no IMU reading for {POSE_ORDER[index]}; nothing saved")
            return 1
        acc_rows = [item[0] for item in samples]
        gyro_rows = [item[1] for item in samples]
        acc_mean = [_mean(acc_rows, axis) for axis in range(3)]
        poses.append(to_raw(acc_mean, scale))
        gyros.append([_mean(gyro_rows, axis) for axis in range(3)])
        print(f"[imu]   {POSE_ORDER[index]}: |acc| {magnitude_g(acc_mean):.2f} g")

    covered, problems = coverage(poses)
    if not covered:
        print("[imu] coverage too small - " + "; ".join(problems))
        print("[imu] every pose must put a different axis under gravity; nothing saved")
        return 1

    solution = solve(poses)
    gyro_bias = [
        round(_mean(gyros, axis) * NOMINAL_GYRO_LSB_PER_DPS, 3) for axis in range(3)
    ]
    print("[imu] axis   measured bias.  scale      proposed bias.  scale")
    for axis, name in enumerate("XYZ"):
        print(
            f"[imu]   {name}    {current_bias[axis]:9.1f}  {scale[axis]:7.0f}   "
            f"{solution['acc_bias'][axis]:9.1f}  {solution['acc_scale'][axis]:7.0f}"
        )
    print(
        "[imu] gyro bias (LSB): "
        + ", ".join(f"{value:.1f}" for value in gyro_bias)
        + " - bias only; a rate scale needs a known rotation and was not measured"
    )

    if not args.apply:
        print("[imu] dry run: nothing saved. Re-run with --apply to write it.")
        return 0

    saved = bool(
        hal.set_imu_calibration(
            acc_bias=solution["acc_bias"],
            acc_scale=solution["acc_scale"],
            gyro_bias=gyro_bias,
        )
    )
    if not saved:
        print("[imu] the HAL refused the calibration; nothing was written")
        return 1

    snapshot = hal.read()
    acc = getattr(snapshot, "acc", None)
    if acc is not None:
        print(f"[imu] saved. |acc| now {magnitude_g(acc):.2f} g (1.00 g at rest)")
    else:
        print("[imu] saved. The IMU did not answer, so |acc| could not be re-checked")
    return 0


def main(
    argv: list[str] | None = None,
    hal: Any = None,
    prompt: Callable[[str], str] = input,
) -> int:
    """Measure and save the IMU calibration. `hal` is the injection seam.

    A HAL this tool opened is this tool's to **start and close**. `PidogHAL.start()` is what opens the
    dog and starts its action queue, and without `close()` the vendor's sensor threads outlive the
    process and keep the GPIO pins claimed — which is exactly how the next run ended up reporting
    `GPIO busy` and losing the sound sensor (seen on the dog, 2026-11-17).
    """
    args = _parse_args(argv)
    owned = hal is None
    if hal is None:
        from houndmind_ai.hal.vendor import PidogHAL

        vendor_hal = PidogHAL(settings={})
        try:
            vendor_hal.start()
        except Exception as exc:  # noqa: BLE001 - a missing vendor package is the report
            print(f"[imu] pidog unavailable: {exc}", file=sys.stderr)
            return 2
        hal = vendor_hal
    try:
        return _run(hal, args, prompt)
    finally:
        if owned:
            try:
                hal.close()
            except Exception:  # noqa: BLE001 - nothing left to recover at exit
                print("[imu] close failed", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
