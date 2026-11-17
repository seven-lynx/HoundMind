"""Deterministic in-memory :class:`~houndmind_ai.hal.iface.DogHAL`.

Used by every test that needs a dog. It never sleeps, never imports a vendor package, and
records what it was asked to do so a test can assert on behaviour instead of timing.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from houndmind_ai.hal.iface import (
    DOG_ACTIONS,
    SERVO_GROUP_OF,
    SERVO_OFFSET_LIMIT_DEG,
    DogHAL,
    SensorSnapshot,
    as_float,
)

__all__ = ["FakeDogHAL"]

_DEFAULT_ACTIONS = DOG_ACTIONS


class FakeDogHAL:
    """A scriptable :class:`DogHAL`.

    Sensors are set explicitly by the test; ``read()`` stamps ``ts`` from the injected clock
    so tests can drive time forward without sleeping.
    """

    def __init__(
        self,
        now: Callable[[], float] | None = None,
        actions: frozenset[str] | None = None,
    ) -> None:
        self._now = now or time.monotonic
        self._actions = actions if actions is not None else _DEFAULT_ACTIONS
        # The real adapter serialises calls on the servo bus (one I2C bus, several callers).
        # The fake does the same, so a threaded test exercises the discipline it will meet on the
        # device instead of the happy path that never happens there.
        self._bus = threading.RLock()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.distance_samples: list[tuple[int, float]] = []
        self.offsets_applied: list[dict[str, float]] = []
        # What the "hardware" currently has loaded, as the vendor file would. Empty means "no
        # trim measured yet", which is why `apply_offsets` refuses a joint it has no baseline for.
        self._offsets: dict[str, float] = {}
        # Audio is recorded rather than played: a test asserts the *choice* of effect, never
        # wall-clock timing.
        self.sounds: list[tuple[str, int]] = []
        self.speeches: list[tuple[str, int]] = []
        self.stop_count = 0
        self.closed = False

        self._distance_cm: float | None = None
        self._distance_valid = False
        self._touch = "N"
        self._touch_valid = False
        self._sound_detected = False
        self._sound_direction: int | None = None
        self._sound_valid = False
        self._acc: tuple[float, float, float] | None = None
        self._gyro: tuple[float, float, float] | None = None
        self._pitch_deg: float | None = None
        self._roll_deg: float | None = None
        self._imu_valid = False
        self._battery_v: float | None = None
        self._battery_valid = False

        # IMU calibration: None means "this fake cannot say", which is what a real dog reports
        # before anything has been saved (#258, #259).
        self._imu_calibration: dict[str, list[float]] | None = None
        self.imu_calibrations_saved: list[dict[str, Sequence[float] | None]] = []
        self.imu_calibration_resets = 0

        # Trim writes carry the pose they landed on, so a test can see that a save is not a reset.
        self.poses_applied: list[dict[str, float] | None] = []
        self.nudges: list[tuple[str, float]] = []
        self._angles: dict[str, float] = {}

    # ---- scripting helpers -------------------------------------------------

    def set_distance(self, cm: float | None) -> None:
        """Set the ultrasonic reading. ``None`` marks the sensor invalid, not "far away"."""
        self._distance_cm = cm
        self._distance_valid = cm is not None

    def set_imu(self, pitch_deg: float | None, roll_deg: float | None) -> None:
        self._pitch_deg = pitch_deg
        self._roll_deg = roll_deg
        self._imu_valid = pitch_deg is not None and roll_deg is not None

    def set_acc(self, acc: tuple[float, float, float] | None) -> None:
        """Raw accelerometer, in the same units the vendor reports (g)."""
        self._acc = acc
        self._imu_valid = acc is not None and self._gyro is not None

    def set_gyro(self, gyro: tuple[float, float, float] | None) -> None:
        """Raw gyroscope, in the same units the vendor reports (deg/s)."""
        self._gyro = gyro
        self._imu_valid = self._acc is not None and gyro is not None

    def set_touch(self, value: str) -> None:
        self._touch = value
        self._touch_valid = True

    def set_sound(self, direction: int | None, valid: bool | None = None) -> None:
        """Set the sound reading.

        `direction` is the bearing the vendor reports, or None when nothing was heard. `valid`
        separates "the sensor answered and heard nothing" (the normal quiet-room state, and what
        `PidogHAL` publishes) from "the sensor did not answer"; left out, it keeps the older
        behaviour of tying validity to having a direction.
        """
        self._sound_detected = direction is not None
        self._sound_direction = direction
        self._sound_valid = (direction is not None) if valid is None else valid

    def set_battery(self, volts: float | None) -> None:
        self._battery_v = volts
        self._battery_valid = volts is not None

    def set_actions(self, actions: frozenset[str]) -> None:
        self._actions = actions

    def set_offsets(self, offsets: Mapping[str, float]) -> None:
        """Load a servo trim the way the vendor file would, so a read has something to report."""
        self._offsets = dict(offsets)

    # ---- DogHAL ------------------------------------------------------------

    def read(self) -> SensorSnapshot:
        return SensorSnapshot(
            ts=self._now(),
            distance_cm=self._distance_cm,
            distance_valid=self._distance_valid,
            touch=self._touch,
            touch_valid=self._touch_valid,
            sound_detected=self._sound_detected,
            sound_direction=self._sound_direction,
            sound_valid=self._sound_valid,
            acc=self._acc,
            gyro=self._gyro,
            pitch_deg=self._pitch_deg,
            roll_deg=self._roll_deg,
            imu_valid=self._imu_valid,
            battery_v=self._battery_v,
            battery_valid=self._battery_valid,
        )

    def actions(self) -> frozenset[str]:
        return self._actions

    def action(self, name: str, params: dict[str, Any]) -> None:
        with self._bus:
            self.calls.append((name, dict(params)))

    def sound(self, name: str, volume: int = 70) -> None:
        with self._bus:
            self.sounds.append((name, volume))

    def speak(self, text: str, volume: int = 70) -> None:
        with self._bus:
            self.speeches.append((text, volume))

    def sample_distance(self, samples: int, between_reads_s: float) -> float | None:
        with self._bus:
            self.distance_samples.append((samples, between_reads_s))
            return self._distance_cm

    def set_imu_calibration_store(self, values: dict[str, list[float]] | None) -> None:
        """Seed what ``read_imu_calibration`` reports: a saved calibration, or None for none."""
        self._imu_calibration = values

    def read_imu_calibration(self) -> dict[str, list[float]] | None:
        with self._bus:
            if self._imu_calibration is None:
                return None
            return {key: list(value) for key, value in self._imu_calibration.items()}

    def set_imu_calibration(
        self,
        acc_bias: Sequence[float] | None = None,
        acc_scale: Sequence[float] | None = None,
        gyro_bias: Sequence[float] | None = None,
        gyro_scale: Sequence[float] | None = None,
    ) -> bool:
        """Mirror the contract: an omitted argument leaves that key alone, not zeroed."""
        supplied: dict[str, Sequence[float] | None] = {
            "acc_bias": acc_bias,
            "acc_scale": acc_scale,
            "gyro_bias": gyro_bias,
            "gyro_scale": gyro_scale,
        }
        with self._bus:
            self.imu_calibrations_saved.append(dict(supplied))
            if all(value is None for value in supplied.values()):
                return False
            store = dict(self._imu_calibration or {})
            for key, value in supplied.items():
                if value is not None:
                    store[key] = [float(item) for item in value]
            self._imu_calibration = store
            return True

    def reset_imu_calibration(self) -> bool:
        with self._bus:
            self.imu_calibration_resets += 1
            self._imu_calibration = None
            return True

    def read_offsets(self) -> dict[str, float]:
        with self._bus:
            return dict(self._offsets)

    def apply_offsets(
        self,
        offsets: Mapping[str, float],
        pose: Mapping[str, float] | None = None,
    ) -> None:
        """Mirror the contract: unknown names ignored, clamped, and no baseline means no write."""
        with self._bus:
            self.offsets_applied.append(dict(offsets))
            self.poses_applied.append(dict(pose) if pose is not None else None)
            for name, value in (offsets or {}).items():
                if name not in SERVO_GROUP_OF:
                    continue
                if name not in self._offsets:
                    continue
                number = as_float(value, self._offsets[name])
                self._offsets[name] = max(
                    -SERVO_OFFSET_LIMIT_DEG, min(SERVO_OFFSET_LIMIT_DEG, number)
                )

    def nudge_joint(self, name: str, degrees: float) -> None:
        """Record the probe and move the fake's own angles, so a tool can be driven headless."""
        if name not in SERVO_GROUP_OF:
            raise ValueError(f"unknown joint {name!r}")
        with self._bus:
            self.nudges.append((name, float(degrees)))
            self._angles[name] = self._angles.get(name, 0.0) + float(degrees)

    def stop(self) -> None:
        self.stop_count += 1
        self.calls.append(("stop", {}))

    def close(self) -> None:
        self.closed = True


# Fail at type-check time if the fake ever drifts from the protocol.
if TYPE_CHECKING:
    _protocol_check: type[DogHAL] = FakeDogHAL