"""The hardware boundary.

Every vendor import (``pidog``, ``robot_hat``, ``picamera2``, ``vilib``) belongs behind this
module. Anything above ``hal/`` talks to :class:`DogHAL` and the frozen dataclasses below —
never to a vendor object, never to a raw dict.

Keeping the boundary this narrow is what makes the rest of the platform testable on CI with
no dog attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = ["DogHAL", "SensorSnapshot", "as_float", "as_int"]


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
    sound_direction: int | None = None
    sound_valid: bool = False
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
            "sound_direction": self.sound_direction,
            "sound_valid": self.sound_valid,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "imu_valid": self.imu_valid,
            "battery_v": self.battery_v,
            "battery_valid": self.battery_valid,
        }


@runtime_checkable
class DogHAL(Protocol):
    """The only interface the actuator gateway is allowed to call.

    Implementations: :class:`houndmind_ai.hal.fake.FakeDogHAL` for tests and CI, and the
    vendor-backed adapter for real hardware. Adding a method here means adding a fake
    implementation in the same change.
    """

    def read(self) -> SensorSnapshot:
        """Return the latest snapshot. Must never block longer than one poll interval."""
        ...

    def actions(self) -> frozenset[str]:
        """Action names this HAL can execute."""
        ...

    def action(self, name: str, params: dict[str, Any]) -> None:
        """Execute one catalog action. Raises only if the HAL itself is broken."""
        ...

    def stop(self) -> None:
        """Stop all actuators immediately. Must be safe to call at any time, repeatedly."""
        ...

    def close(self) -> None:
        """Release hardware resources. Idempotent."""
        ...