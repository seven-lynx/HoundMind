"""The hardware boundary.

Every vendor import (``pidog``, ``robot_hat``, ``picamera2``, ``vilib``) belongs behind this
module. Anything above ``hal/`` talks to :class:`DogHAL` and the frozen dataclasses below —
never to a vendor object, never to a raw dict.

Keeping the boundary this narrow is what makes the rest of the platform testable on CI with
no dog attached.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = ["DOG_ACTIONS", "DogHAL", "SensorSnapshot", "as_float", "as_int"]

# The actions the HAL implements itself. Anything else in `config/actions.jsonc` is a vendor
# `ActionFlow` name that is passed through, so this list describes the contract, not the whole
# repertoire: the dog knows more tricks than the runtime has opinions about.
DOG_ACTIONS: frozenset[str] = frozenset(
    {
        "forward",
        "backward",
        "turn_left",
        "turn_right",
        "stop",
        "stand",
        "sit",
        "lie",
        "stretch",
        "wag_tail",
        "bark",
        "head",
        "rgb",
        "rpy",
    }
)


def as_float(value: Any, default: float) -> float:
    """Coerce a vendor/JSON value to float, falling back to `default`.

    Vendor structs are untyped and config values are user input. Never call bare
    ``float()`` on either.
    """
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    # NaN is "missing", not "almost zero".
    if result != result:  # noqa: PLR0124 - NaN check without importing math
        return default
    return result


def as_int(value: Any, default: int) -> int:
    """Coerce a vendor/JSON value to int, falling back to `default`."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SensorSnapshot:
    """One immutable sensor reading.

    A reading is usable only when its validity flag is true. Consumers **must** branch on
    the flag before the value: ``distance_cm=100.0`` with ``distance_valid=False`` means
    "no measurement", not "clear at one metre".
    """

    ts: float
    distance_cm: float | None = None
    distance_valid: bool = False
    touch: str = "N"
    touch_valid: bool = False
    sound_detected: bool = False
    sound_direction: int | None = None
    sound_valid: bool = False
    # Raw IMU. `acc` is a 3-tuple in g, `gyro` a 3-tuple in deg/s; both None when the IMU
    # could not be read, which is why they are not defaulted to zeros.
    acc: tuple[float, float, float] | None = None
    gyro: tuple[float, float, float] | None = None
    pitch_deg: float | None = None
    roll_deg: float | None = None
    imu_valid: bool = False
    battery_v: float | None = None
    battery_valid: bool = False

    @property
    def tilted(self) -> bool:
        """True only when the IMU is valid *and* the reported angles exist."""
        return self.imu_valid and self.pitch_deg is not None and self.roll_deg is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "ts": self.ts,
            "distance_cm": self.distance_cm,
            "distance_valid": self.distance_valid,
            "touch": self.touch,
            "touch_valid": self.touch_valid,
            "sound_detected": self.sound_detected,
            "sound_direction": self.sound_direction,
            "sound_valid": self.sound_valid,
            "acc": self.acc,
            "gyro": self.gyro,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "imu_valid": self.imu_valid,
            "battery_v": self.battery_v,
            "battery_valid": self.battery_valid,
        }


@runtime_checkable
class DogHAL(Protocol):
    """The only interface the rest of the runtime is allowed to use to reach hardware.

    Implementations: :class:`houndmind_ai.hal.fake.FakeDogHAL` for tests and CI, and
    :class:`houndmind_ai.hal.vendor.PidogHAL` on a real dog. Adding a method here means adding
    an implementation to the fake in the same change.

    The HAL owns the *hardware* and its signal conditioning (multi-sample distance, debounce,
    EMA, IMU low-pass) because those are properties of the sensors. Modules own cadence,
    history and fan-out. That split is what lets a fake drive the whole loop.
    """

    def read(self) -> SensorSnapshot:
        """Return the latest snapshot. Must never block longer than one poll interval."""
        ...

    def actions(self) -> frozenset[str]:
        """Action names this HAL can execute."""
        ...

    def action(self, name: str, params: dict[str, Any]) -> None:
        """Execute one catalog action. Raises only if the HAL itself is broken.

        `name` is the canonical spelling (`turn_left`), never the vendor one. `params` carries
        the details the runtime uses, all optional:

        - gait and posture: ``{"speed": int, "steps": int, "wait": bool}``. With no params the
          action is queued and returns immediately; with any of them it is executed directly
          and `wait` means "block until the servos are done".
        - ``head``: ``{"yaw": float, "pitch": float, "speed": int, "wait": bool}``
        - ``rgb``: ``{"style": str, "color": str, "brightness": float}``
        - ``rpy``: ``{"roll": float, "pitch": float, "yaw": float}``
        """
        ...

    def sample_distance(self, samples: int, between_reads_s: float) -> float | None:
        """Take a fresh distance estimate (median of `samples`), or None if it failed.

        Separate from :meth:`read` because a head scan needs the distance *after* the head
        moved, not the last polled value.
        """
        ...

    def apply_offsets(self, offsets: Mapping[str, float]) -> None:
        """Apply servo zero offsets. The calibration workflow writes these; nothing invents them."""
        ...

    def stop(self) -> None:
        """Stop all actuators immediately. Must be safe to call at any time, repeatedly."""
        ...

    def close(self) -> None:
        """Release hardware resources. Idempotent."""
        ...