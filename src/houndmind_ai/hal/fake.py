"""Deterministic in-memory :class:`~houndmind_ai.hal.iface.DogHAL`.

Used by every test that needs a dog. It never sleeps, never imports a vendor package, and
records what it was asked to do so a test can assert on behaviour instead of timing.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from houndmind_ai.hal.iface import DOG_ACTIONS, DogHAL, SensorSnapshot

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
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.distance_samples: list[tuple[int, float]] = []
        self.offsets_applied: list[dict[str, float]] = []
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

    def set_sound(self, direction: int | None) -> None:
        self._sound_detected = direction is not None
        self._sound_direction = direction
        self._sound_valid = direction is not None

    def set_battery(self, volts: float | None) -> None:
        self._battery_v = volts
        self._battery_valid = volts is not None

    def set_actions(self, actions: frozenset[str]) -> None:
        self._actions = actions

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
        self.calls.append((name, dict(params)))

    def sample_distance(self, samples: int, between_reads_s: float) -> float | None:
        self.distance_samples.append((samples, between_reads_s))
        return self._distance_cm

    def apply_offsets(self, offsets: Mapping[str, float]) -> None:
        self.offsets_applied.append(dict(offsets))

    def stop(self) -> None:
        self.stop_count += 1
        self.calls.append(("stop", {}))

    def close(self) -> None:
        self.closed = True


# Fail at type-check time if the fake ever drifts from the protocol.
if TYPE_CHECKING:
    _protocol_check: type[DogHAL] = FakeDogHAL