"""The hardware boundary.

Every vendor import (``pidog``, ``robot_hat``, ``picamera2``, ``vilib``) belongs behind this
module. Anything above ``hal/`` talks to :class:`DogHAL` and the frozen dataclasses below —
never to a vendor object, never to a raw dict.

Keeping the boundary this narrow is what makes the rest of the platform testable on CI with
no dog attached.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "DOG_ACTIONS",
    "HEAD_SERVO_NAMES",
    "LEG_SERVO_NAMES",
    "SERVO_GROUPS",
    "SERVO_GROUP_OF",
    "SERVO_NAMES",
    "SERVO_OFFSET_LIMIT_DEG",
    "NUDGE_LIMIT_DEG",
    "SERVO_ANGLE_LIMIT_DEG",
    "TAIL_SERVO_NAMES",
    "DogHAL",
    "SensorSnapshot",
    "as_float",
    "as_int",
]

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
        "sound",
        "speak",
    }
)

# The joints whose trim the vendor stores, in the order the vendor's own lists use
# (`docs/pidog/HARDWARE.md:59-70`): eight leg angles — shoulder then leg, front-left first —
# head `[yaw, roll, pitch]`, then one tail. The order is positional because
# `~/.config/pidog/pidog.conf` stores three lists (`legs_servo_offset_list`,
# `head_servo_offset_list`, `tail_servo_offset_list`), not a mapping; these names are the
# translation both adapters and the calibration tool share.
LEG_SERVO_NAMES: tuple[str, ...] = (
    "lf_shoulder",
    "lf_leg",
    "rf_shoulder",
    "rf_leg",
    "lh_shoulder",
    "lh_leg",
    "rh_shoulder",
    "rh_leg",
)
HEAD_SERVO_NAMES: tuple[str, ...] = ("head_yaw", "head_roll", "head_pitch")
TAIL_SERVO_NAMES: tuple[str, ...] = ("tail",)
SERVO_GROUPS: Mapping[str, tuple[str, ...]] = {
    "legs": LEG_SERVO_NAMES,
    "head": HEAD_SERVO_NAMES,
    "tail": TAIL_SERVO_NAMES,
}
SERVO_NAMES: tuple[str, ...] = LEG_SERVO_NAMES + HEAD_SERVO_NAMES + TAIL_SERVO_NAMES
SERVO_GROUP_OF: Mapping[str, str] = {
    name: group for group, names in SERVO_GROUPS.items() for name in names
}
# `robot_hat.Robot.set_offset` clamps a saved trim to ±20°, so the HAL clamps first and never
# leaves the vendor to reject a value the workflow computed (`docs/pidog/HARDWARE.md:227`).
SERVO_OFFSET_LIMIT_DEG: float = 20.0

# One nudge of a single joint is a calibration probe, not a gait: the step is capped here so a tool
# cannot ask the HAL for a move nobody reviewed, and the command angle is capped like a servo.
NUDGE_LIMIT_DEG: float = 3.0
SERVO_ANGLE_LIMIT_DEG: float = 90.0


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
        """Action names this HAL can execute (its own, plus whatever the vendor reports)."""
        ...

    def action(self, name: str, params: dict[str, Any]) -> None:
        """Execute one catalog action. Raises only if the HAL itself is broken.

        `name` is the canonical spelling (`turn_left`), never the vendor one. `params` carries
        the details the runtime uses, all optional:

        - gait and posture: ``{"speed": int, "steps": int, "wait": bool}``. With no params the
          action is queued and returns immediately; with any of them it is executed directly
          and `wait` means "block until the servos are done".
        - ``head``: ``{"yaw": float, "pitch": float, "speed": int, "wait": bool}``
        - ``rgb``: ``{"style": str, "color": str, "brightness": float, "bps": float}`` —
          ``bps`` is the effect's animation rate; dropping it means every effect runs at the
          vendor's default rate, which is a bug this parameter exists to prevent
        - ``rpy``: ``{"roll": float, "pitch": float, "yaw": float}``
        - ``sound`` / ``speak``: ``{"name"|"text": str, "volume": int}``
        """
        ...

    def sound(self, name: str, volume: int = 70) -> None:
        """Play one of the dog's built-in sound effects, volume 0-100.

        The effect names are the vendor's (`docs/PIDOG_PROGRAMMING_GUIDE.md` §4.1), so they stay
        free-form strings here and are not validated: a build with fewer of them must still work.
        """
        ...

    def speak(self, text: str, volume: int = 70) -> None:
        """Say `text` through the vendor's speech path, volume 0-100.

        Deliberately separate from :meth:`sound` so a routine can talk without the optional
        `voice` module being enabled.
        """
        ...

    def sample_distance(self, samples: int, between_reads_s: float) -> float | None:
        """Take a fresh distance estimate (median of `samples`), or None if it failed.

        Separate from :meth:`read` because a head scan needs the distance *after* the head
        moved, not the last polled value.
        """
        ...

    def read_offsets(self) -> dict[str, float]:
        """The servo zero offsets currently loaded on the hardware, name -> signed degrees.

        The vendor's own file (`~/.config/pidog/pidog.conf`) is the authority; this reports what
        it loaded. A joint whose value could not be read is **absent**, never reported as ``0.0``
        — "not measured" is not "measured straight".
        """
        ...

    def apply_offsets(
        self,
        offsets: Mapping[str, float],
        pose: Mapping[str, float] | None = None,
    ) -> None:
        """Save servo zero offsets, clamped to :data:`SERVO_OFFSET_LIMIT_DEG`.

        The calibration workflow and `hal/motors.py` supply these; nothing invents them. A name this
        HAL does not know is ignored, and a group whose current values cannot be read is not written
        at all — replacing a whole vendor list with zeros would be user data nobody measured.

        The vendor has no silent-save path: every setter re-poses as it saves (#263). So a legs write
        lands on the pose the dog is **already in**, which is the only way "save this trim" does not
        also mean "drive eight servos to zero". `pose` overrides that with angles the caller chose,
        and passing it is a motion request: only the interactive trim tools do.
        """
        ...

    def nudge_joint(self, name: str, degrees: float) -> None:
        """Move one joint by `degrees` relative to where it is now. **This moves the dog.**

        Calibration only, and never on a tick: the trim tools use it to see the effect of a change
        one joint at a time. The step is capped at :data:`NUDGE_LIMIT_DEG` and the result at
        :data:`SERVO_ANGLE_LIMIT_DEG`. It writes no offset — the trim is saved separately — so a
        probe can always be undone by nudging back.
        """
        ...

    def read_imu_calibration(self) -> dict[str, list[float]] | None:
        """The IMU calibration the hardware loaded, or ``None`` when it cannot report one.

        Keys are the vendor's own — ``acc_bias``, ``acc_scale``, ``gyro_bias``, ``gyro_scale`` —
        each a 3-item list in the sensor's units (LSB, LSB per g, LSB, LSB per deg/s). ``None``
        means "this HAL cannot say", never zeros: an absent calibration is a measurement, and a
        fabricated one would hide an uncalibrated sensor behind a plausible-looking list (#258).
        """
        ...

    def set_imu_calibration(
        self,
        acc_bias: Sequence[float] | None = None,
        acc_scale: Sequence[float] | None = None,
        gyro_bias: Sequence[float] | None = None,
        gyro_scale: Sequence[float] | None = None,
    ) -> bool:
        """Persist a measured IMU calibration; ``True`` when the hardware accepted it.

        This is user data written into the vendor's own config file, so the caller passes numbers
        it actually measured and leaves the rest ``None`` — an omitted argument must leave that key
        untouched rather than reset it. Nothing in the runtime calls this on its own.
        """
        ...

    def reset_imu_calibration(self) -> bool:
        """Drop the stored IMU calibration, back to the datasheet nominal values."""
        ...

    def stop(self) -> None:
        """Stop all actuators immediately. Must be safe to call at any time, repeatedly."""
        ...

    def close(self) -> None:
        """Release hardware resources. Idempotent."""
        ...