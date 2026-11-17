"""PiDog hardware checkup: one sensor snapshot, then a minimal motion run unless asked not to.

Hardware comes from :class:`~houndmind_ai.hal.iface.DogHAL` - `PidogHAL` on a dog, a fake in a
test - so the checkup reads the conditioned snapshot the runtime reads instead of opening a
`Pidog()` of its own (#11). The exit code is the verdict (#109): 0 when every sensor answered, 1
when one did not, 2 when no dog could be opened at all, 3 when another process owns the servo bus.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path
from typing import Any

from houndmind_ai.core.instance import BusBusy, RunLock
from houndmind_ai.hal.iface import DogHAL, SensorSnapshot

__all__ = ["MOTION_STEPS", "describe", "main", "run_checkup"]

# The motion sequence in HAL vocabulary, in the order the bench checklist expects
# (`docs/HARDWARE_TEST.md` section 9): stand, both turns, then the head sweep and back to centre.
# `wait` makes each step complete before the next begins, as the old direct vendor calls did.
# `speed` is the vendor's own rate for these moves, not the maximum. At 180 the leg steps pull
# enough inrush to brown out the stock pack's 5 V rail - two `Undervoltage detected!` episodes on the
# bench dog - and even 100 sat on the edge (one 6 s episode in two runs on the charger). The vendor's
# action presets use 65 for `stand` and 98 for the turns, so the checkup now asks for what the
# product asks for, and measures the servos instead of the supply (#207).
MOTION_STEPS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("stand", {"speed": 65, "steps": 1, "wait": True}),
    ("turn_left", {"speed": 98, "steps": 1, "wait": True}),
    ("turn_right", {"speed": 98, "steps": 1, "wait": True}),
    ("head", {"yaw": -30.0, "speed": 70, "wait": True}),
    ("head", {"yaw": 30.0, "speed": 70, "wait": True}),
    ("head", {"yaw": 0.0, "speed": 70, "wait": True}),
)


def describe(snapshot: SensorSnapshot) -> list[str]:
    """One line per sensor, plus the validity verdict.

    A value is printed only when its flag says it is a measurement: `None` means "no reading",
    never a fabricated number (`SensorSnapshot`, `hal/iface.py`). `sound` is the line where the
    value can be legitimately absent on a healthy dog - nothing was heard - so it needs the
    `valid:` line to be distinguishable from a sensor that did not answer.

    `battery` is the pack voltage the HAT itself measures. It is reported, never enforced: a dog
    without the sense line reads `None`, so it stays out of `_no_reading`, and the power gate in a
    bench run is `vcgencmd get_throttled` in `docs/HARDWARE_TEST.md` section 2 (#185).
    """
    distance = (
        f"{snapshot.distance_cm:.1f}"
        if snapshot.distance_valid and snapshot.distance_cm is not None
        else "None"
    )
    touch = snapshot.touch if snapshot.touch_valid else "None"
    sound = (
        f"detected={snapshot.sound_detected} dir={snapshot.sound_direction}"
        if snapshot.sound_valid
        else "detected=None dir=None"
    )
    if snapshot.imu_valid and snapshot.acc is not None:
        acc = (
            f"({snapshot.acc[0]:.3f}, {snapshot.acc[1]:.3f}, {snapshot.acc[2]:.3f}) g"
        )
    else:
        acc = "None"
    if snapshot.imu_valid and snapshot.gyro is not None:
        gyro = (
            f"({snapshot.gyro[0]:.2f}, {snapshot.gyro[1]:.2f}, {snapshot.gyro[2]:.2f}) deg/s"
        )
    else:
        gyro = "None"
    battery = (
        f"{snapshot.battery_v:.2f} V"
        if snapshot.battery_valid and snapshot.battery_v is not None
        else "None"
    )
    valid = (
        f"distance={snapshot.distance_valid} touch={snapshot.touch_valid} "
        f"sound={snapshot.sound_valid} imu={snapshot.imu_valid}"
    )
    return [
        f"[checkup] distance_cm: {distance}",
        f"[checkup] touch: {touch}",
        f"[checkup] sound: {sound}",
        f"[checkup] acc: {acc}",
        f"[checkup] gyro: {gyro}",
        f"[checkup] battery: {battery}",
        f"[checkup] valid: {valid}",
        *_sound_hint(snapshot),
        *_gravity_hint(snapshot),
    ]


#: How far `|acc|` may sit from 1 g before the reading is called uncalibrated.
GRAVITY_TOLERANCE_G = 0.25


def _gravity_hint(snapshot: SensorSnapshot) -> list[str]:
    """One line when the accelerometer does not measure gravity (#258).

    At rest `|acc|` is 1 g. An uncalibrated sensor reads something else, and every angle derived
    from it - pitch, roll, and the tilt latch in `safety` - carries the same offset. This is the
    detector only: the vendor's `examples/imu_calibration.py` writes the `calibrate_*` values that
    fix it, and the warning names the command rather than changing calibration behind the user's
    back.
    """
    if not snapshot.imu_valid or snapshot.acc is None:
        return []
    magnitude = math.sqrt(sum(float(axis) ** 2 for axis in snapshot.acc))
    if abs(magnitude - 1.0) <= GRAVITY_TOLERANCE_G:
        return []
    return [
        f"[checkup] imu_gravity: {magnitude:.2f} g at rest, expected 1.00 g "
        f"(+-{GRAVITY_TOLERANCE_G:.2f}) - the accelerometer is uncalibrated, so pitch/roll and "
        "the tilt latch are biased; see the IMU calibration example in docs/pidog (#258)"
    ]


def _spi_missing() -> bool:
    """True when this looks like a Pi whose SPI interface was never enabled (#204).

    Both halves matter: no `/dev/spidev0.0` on a Pi (a `config.txt` exists) means the interface is
    off, while the same absence on a workstation means nothing at all and must not produce a hint.
    """
    return not Path("/dev/spidev0.0").exists() and Path("/boot/firmware/config.txt").exists()


def _sound_hint(snapshot: SensorSnapshot) -> list[str]:
    """Point at the reason when the sound sensor did not answer (#183).

    The vendor constructor prints `sound_direction init ... fail` and swallows the exception, so
    this tool cannot name the cause. The HAL logs exactly one `Sound sensor unavailable: ...`
    warning with the attribute and the `pidog` revision, and this line says where to look instead
    of inventing a diagnosis from a boolean.

    The commonest cause on a fresh install is not the sensor at all: it is an SPI interface that was
    never enabled (#204), so the hint checks the device node and says so rather than sending the
    reader looking for a dead part.
    """
    if snapshot.sound_valid:
        return []
    hints = [
        '[checkup] hint: the sound sensor did not answer - look for "Sound sensor unavailable" '
        "in the log, which names the attribute and the pidog revision (#183)"
    ]
    if _spi_missing():
        hints.append(
            "[checkup] hint: this Pi has no /dev/spidev0.0 - the sound sensor is an SPI device. "
            "Enable it with `sudo raspi-config nonint do_spi 0` and reboot (docs/INSTALL.md, "
            "Prerequisites) (#204)"
        )
    return hints


def _no_reading(snapshot: SensorSnapshot) -> list[str]:
    """The sensors that did not answer, named as the `[checkup] valid:` line names them.

    A quiet room is not a failure: `sound` answered and heard nothing, which is
    `sound_valid=True` with `sound_detected=False`.
    """
    flags = (
        ("distance", snapshot.distance_valid),
        ("touch", snapshot.touch_valid),
        ("sound", snapshot.sound_valid),
        ("imu", snapshot.imu_valid),
    )
    return [name for name, valid in flags if not valid]


def run_checkup(hal: DogHAL, skip_motion: bool, pause: float) -> bool:
    """Read every sensor once; command the motion sequence only when motion is allowed.

    Returns True when every sensor answered. A failed motion step is reported on stderr and does
    not change that answer: the sensors are what the exit code is about (#109).
    """
    print("[checkup] Reading sensors...")
    snapshot = hal.read()
    for line in describe(snapshot):
        print(line)

    missing = _no_reading(snapshot)
    if missing:
        print(f"[checkup] no reading from: {', '.join(missing)}")
    else:
        print("[checkup] sensors: all answered")

    if skip_motion:
        print("[checkup] Motion skipped.")
        return not missing

    print("[checkup] Running minimal motion...")
    delay = max(0.0, pause)
    for name, params in MOTION_STEPS:
        try:
            hal.action(name, dict(params))
        except Exception as exc:  # noqa: BLE001 - one failed step must not abandon the rest
            print(f"[checkup] step {name} failed: {exc}", file=sys.stderr)
        time.sleep(delay)
    print("[checkup] Done.")
    return not missing


def _load_settings(path: str | None) -> dict[str, Any]:
    """The `settings` table, so the HAL conditions sensors the way the runtime does.

    A checkup exists to test hardware, not to fail on a config problem: a file that will not load
    degrades to the HAL's own defaults with one line saying why.
    """
    from houndmind_ai.core.config import load_config

    try:
        return dict(load_config(Path(path) if path else None).settings)
    except Exception as exc:  # noqa: BLE001 - missing file, bad JSON, or a schema problem
        print(f"[checkup] settings not loaded ({exc}); using HAL defaults", file=sys.stderr)
        return {}


def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    """Run the checkup. `hal` is the injection seam: `None` opens the real dog."""
    parser = argparse.ArgumentParser(
        description="PiDog hardware checkup (sensors + minimal motion)"
    )
    parser.add_argument(
        "--skip-motion", action="store_true", help="Do not run any motion actions"
    )
    parser.add_argument(
        "--pause", type=float, default=0.6, help="Pause between steps (seconds)"
    )
    parser.add_argument(
        "--config", type=str, default=None, help="Path to settings.jsonc"
    )
    args = parser.parse_args(argv)

    owned = hal is None
    lock: RunLock | None = None
    if hal is None:
        # One process may own the servo bus (#213): a second `Pidog()` blocks on the bus the first
        # one holds, with no output at all, so this says who has it and exits 3 rather than hanging.
        lock = RunLock()
        try:
            lock.acquire("hardware_checkup")
        except BusBusy as exc:
            print(f"[checkup] {exc}", file=sys.stderr)
            print("[checkup] stop it first: systemctl stop houndmind", file=sys.stderr)
            return 3
        # Imported here, not at module scope: the vendor package is only needed on a dog, and a
        # missing one must read as a reportable failure rather than an import traceback.
        from houndmind_ai.hal.vendor import PidogHAL

        vendor_hal = PidogHAL(_load_settings(args.config))
        try:
            vendor_hal.start()
        except Exception as exc:  # noqa: BLE001 - a missing vendor package is the report
            print(f"[checkup] pidog unavailable: {exc}", file=sys.stderr)
            return 2
        hal = vendor_hal

    try:
        sensors_ok = run_checkup(hal, args.skip_motion, args.pause)
    finally:
        # Only a HAL this tool opened is the tool's to close; an injected fake belongs to its test.
        if owned:
            try:
                hal.close()
            except Exception:  # noqa: BLE001 - nothing left to recover at exit
                print("[checkup] close failed", file=sys.stderr)
            if lock is not None:
                lock.release()
    return 0 if sensors_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
