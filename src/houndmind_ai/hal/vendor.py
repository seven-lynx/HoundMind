"""The vendor-backed :class:`~houndmind_ai.hal.iface.DogHAL`.

This is the only module in the tree that imports `pidog` to drive the dog. Everything above
`hal/` sees a `DogHAL`, which is what makes the loop testable on a machine with no hardware:
`hal/fake.FakeDogHAL` is swapped in and nothing else changes.

Two things live here that used to live one layer up:

- The sensor signal conditioning (multi-sample distance with median and outlier rejection,
  touch debounce, EMA, IMU low-pass). Those are properties of the ultrasonic, the touch pads
  and the IMU, not of the loop, and keeping them next to the reads is the only way the vendor
  object stays in one file.
- The vendor call for head, LED and posture, which three modules used to make themselves by
  reaching into `context["pidog"]` (`attention.py`, `led_manager.py`, `balance.py`).

`import pidog` happens inside :meth:`PidogHAL._ensure_dog`, so importing this module costs
nothing on a workstation and a missing vendored package produces one clear failure instead of a
`ModuleNotFoundError` at interpreter start.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import warnings
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as dist_version
from typing import Any, cast

from houndmind_ai.hal.iface import (
    DOG_ACTIONS,
    NUDGE_LIMIT_DEG,
    SERVO_ANGLE_LIMIT_DEG,
    SERVO_GROUP_OF,
    SERVO_GROUPS,
    SERVO_OFFSET_LIMIT_DEG,
    SensorSnapshot,
    as_float,
    as_int,
)

# A pure spelling helper from the command vocabulary: `ActionFlow` names come back spaced
# ("turn left") and everything above the HAL compares canonical names. `kernel/commands.py`
# imports nothing but the stdlib, so this does not drag the runtime into the HAL.
from houndmind_ai.kernel.commands import canonical_action

logger = logging.getLogger(__name__)

__all__ = ["PidogHAL"]

# The installer clones the vendor tree at its default branch, so two installs can disagree about
# the `Pidog` API. When a sub-device cannot be used, the warning names the revision the HAL was
# talking to (#183): "sound does not work" is unactionable, "no `ears` on pidog 2.4.1" is a pairing
# bug someone can fix.
def _pidog_version() -> str:
    try:
        import pidog  # type: ignore[import-not-found]
    except ImportError:
        return "not importable"
    version = getattr(pidog, "__version__", None)
    if version:
        return str(version)
    try:
        return dist_version("pidog")
    except PackageNotFoundError:
        return "unknown version"


# One vendor entry point per offset group. They replace the whole list, which is why
# `apply_offsets` reads the current values before it writes.
_GROUP_SETTERS = {
    "legs": "set_leg_offsets",
    "head": "set_head_offsets",
    "tail": "set_tail_offset",
}

# Where each group's last commanded angles live on the vendor object. `Pidog` keeps them itself and
# updates them on every move (`pidog.py:387`), which is what makes a nudge relative to "now" possible.
_ANGLE_ATTRS = {
    "legs": "leg_current_angles",
    "head": "head_current_angles",
    "tail": "tail_current_angles",
}

# A calibration probe moves slowly: one joint, dog standing still, nothing to gain from gait speed.
_NUDGE_SPEED = 30


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


#: The SH3001's sensitivity at the ranges `sh3001_init` configures, taken from the vendor's own
#: `sh3001.py:16-17`. `Pidog.accData`/`gyroData` are raw counts: the driver thread reads
#: `_sh3001_getimudata()` (`pidog.py:461`), not `get_calibrated_data()`.
ACC_LSB_PER_G = 16384.0
GYRO_LSB_PER_DPS = 16.4


def _axis_value(scale: Any, index: int, nominal: float) -> float:
    """One axis of a scalar-or-triple conversion factor, or `nominal` when it is unusable."""
    try:
        value = float(scale[index] if isinstance(scale, (list, tuple)) else scale)
    except (TypeError, ValueError, IndexError, KeyError):
        return nominal
    return value


def to_physical(
    raw: tuple[float, float, float],
    scale: Any,
    nominal: float,
    bias: Any = None,
) -> tuple[float, float, float]:
    """Raw IMU counts to physical units, per axis.

    `scale` is the vendor's LSB-per-unit (`Sh3001.acc_scale`/`gyro_scale`), a scalar or a
    3-item sequence, and `bias` is its matching offset. This is the same arithmetic the vendor
    applies in `sh3001.py:686-694`; it exists here because the HAL publishes `Pidog.accData`
    and receives g and deg/s from every consumer, while `Pidog` hands out counts.

    A missing, zero or unreadable divisor falls back to `nominal`: dividing by zero would put
    infinities into the heading integrator, which is worse than a nominal-scale reading.
    """
    converted: list[float] = []
    for index in range(3):
        divisor = _axis_value(scale, index, nominal)
        if abs(divisor) < 1e-6:
            divisor = nominal
        offset = _axis_value(bias, index, 0.0)
        converted.append((float(raw[index]) - offset) / divisor)
    return (converted[0], converted[1], converted[2])


def _safe_int(val: Any, default: int) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


class PidogHAL:
    """`DogHAL` on a real PiDog.

    `settings` is the whole `settings` table: the constructor picks the `sensors` section for
    its filtering knobs.
    """

    def __init__(
        self,
        settings: Mapping[str, Any] | None = None,
        dog: Any | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = dict(settings or {})
        self._sensor_cfg = dict(self._settings.get("sensors", {}) or {})
        self._dog = dog
        self._dog_owned = dog is None
        self._clock = clock or time.time
        self._action_flow: Any | None = None
        # Audio runs on its own worker: one pending utterance, latest wins — the same shape as
        # `vision_inference_scheduler`. Created lazily, so a runtime that never plays a sound
        # never starts a thread.
        self._audio: queue.Queue[tuple[str, int] | None] = queue.Queue(maxsize=1)
        self._audio_lock = threading.Lock()
        self._audio_thread: threading.Thread | None = None
        # Names the vendor could not find, reported once each: a cue that fires on every entry
        # into a state must not turn one missing effect into a log flood (#81). Only the audio
        # worker thread touches this, so it needs no lock.
        self._warned_sounds: set[str] = set()
        # Why the sound sub-device is unusable, if it is (#183). `None` means "not known to be
        # broken"; once set, the per-tick read returns invalid without retrying and without a
        # traceback nobody reads, and the reason is in the one WARNING that set it.
        self._sound_reason: str | None = None
        # The vendor's action list, read once (see `_read_vendor_actions`).
        self._vendor_action_names: frozenset[str] | None = None
        self._closed = False
        # One I2C bus, and now more than one caller: the loop executes gaits, the scan worker moves
        # the head and samples distance, the attention module turns the head toward a sound, and
        # the vendor action queue is not thread-safe. Two of those interleaved is a servo command
        # arriving mid-step. Re-entrant because `action("stop")` delegates to `stop()`.
        #
        # The cost is latency, and it is deliberate: a `read()` can wait for a sampling sequence
        # (~0.1 s) and an emergency stop can wait for the servo call in progress. Both callers are
        # workers, never the decision loop, and an interleaved I2C transaction is the worse bug.
        self._bus = threading.RLock()

        # Signal-conditioning state, carried across reads like it always was.
        self._last_touch = "N"
        self._last_touch_ts = 0.0
        self._last_distance: float | None = None
        self._last_distance_ts = 0.0
        self._ema_distance: float | None = None
        self._acc_lpf: tuple[float, float, float] | None = None
        self._gyro_lpf: tuple[float, float, float] | None = None
        # The pack voltage is an ADC read on the bus the servos share, so it runs on its own slower
        # cadence (`sensors.battery_poll_s`) and the last good value is what gets reported in
        # between. `None` means "no reading", never "0 V", which would look like a flat pack.
        self._battery_v: float | None = None
        self._battery_ts = 0.0

    # ------------------------------------------------------------------ setup

    def _ensure_dog(self) -> Any:
        if self._dog is None:
            from pidog import Pidog  # type: ignore[import-not-found]

            self._dog = Pidog()
        return self._dog

    def _ensure_action_flow(self) -> Any:
        if self._action_flow is None:
            from pidog.action_flow import ActionFlow  # type: ignore[import-not-found]

            flow = ActionFlow(self._ensure_dog())
            flow.start()
            self._action_flow = flow
        return self._action_flow

    def start(self, *, animate: bool = True) -> None:
        """Open the dog and, unless `animate` is false, start its action queue.

        `ActionFlow` is **not passive**: its standby loop plays `waiting` and `feet_left_right` every
        2-6 seconds on its own (`action_flow.py:230-243`), which moves the head and legs with nothing
        asking it to. That is fine for the runtime and wrong for anything that needs the dog still -
        on the dog, the head jittered through a six-face IMU run and spoiled it, so a calibration
        tool passes `animate=False`.
        """
        self._probe_sound(self._ensure_dog())
        if animate:
            self._ensure_action_flow()

    # ----------------------------------------------------------------- sensors

    def read(self) -> SensorSnapshot:
        now = self._clock()
        with self._bus:
            dog = self._ensure_dog()

            distance_cm, distance_valid = self._read_distance(dog, now)
            touch, touch_valid = self._read_touch(dog, now)
            sound_detected, sound_direction, sound_valid = self._read_sound(dog)
            acc, gyro, imu_valid = self._read_imu(dog)
            battery_v, battery_valid = self._read_battery(dog, now)

        return SensorSnapshot(
            ts=now,
            distance_cm=distance_cm,
            distance_valid=distance_valid,
            touch=touch,
            touch_valid=touch_valid,
            sound_detected=sound_detected,
            sound_direction=sound_direction,
            sound_valid=sound_valid,
            acc=acc,
            gyro=gyro,
            imu_valid=imu_valid,
            battery_v=battery_v,
            battery_valid=battery_valid,
        )

    def sample_distance(self, samples: int, between_reads_s: float) -> float | None:
        """Median of `samples` fresh reads, clamped to the configured range.

        The whole sequence holds the bus: a head move slipping in between two samples means the
        median describes two different directions.
        """
        with self._bus:
            dog = self._ensure_dog()
            values = self._raw_distance_samples(dog, samples, between_reads_s)
        if not values:
            return None
        values.sort()
        return values[len(values) // 2]

    def _raw_distance_samples(
        self, dog: Any, samples: int, between_reads_s: float
    ) -> list[float]:
        min_cm = _safe_float(self._sensor_cfg.get("distance_min_cm", 2), 2.0)
        max_cm = _safe_float(self._sensor_cfg.get("distance_max_cm", 200), 200.0)
        delay = max(0.0, _safe_float(between_reads_s, 0.0))
        values: list[float] = []
        for _ in range(max(1, samples)):
            try:
                if hasattr(dog, "read_distance"):
                    value = float(dog.read_distance())
                else:
                    value = float(dog.ultrasonic.read_distance())
            except Exception:  # noqa: BLE001 - one bad sample is not a broken sensor
                logger.debug("Distance sample failed", exc_info=True)
                value = None
            if value is not None and min_cm <= value <= max_cm:
                values.append(value)
            if delay:
                time.sleep(delay)
        return values

    def _read_distance(self, dog: Any, now: float) -> tuple[float | None, bool]:
        debounce_s = max(
            0.0, _safe_float(self._sensor_cfg.get("distance_debounce_s", 0.0), 0.0)
        )
        if debounce_s > 0 and self._last_distance is not None:
            if (now - self._last_distance_ts) < debounce_s:
                return self._last_distance, True

        samples = max(1, _safe_int(self._sensor_cfg.get("distance_samples", 3), 3))
        delay = max(
            0.0, _safe_float(self._sensor_cfg.get("distance_sample_delay_s", 0.03), 0.03)
        )
        use_median = bool(self._sensor_cfg.get("distance_use_median", True))
        outlier_z = _safe_float(
            self._sensor_cfg.get("distance_outlier_reject_z", 0.0), 0.0
        )
        ema_alpha = _safe_float(self._sensor_cfg.get("distance_ema_alpha", 0.0), 0.0)

        values = self._raw_distance_samples(dog, samples, delay)
        if outlier_z > 0.0 and len(values) >= 3:
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = variance**0.5
            if std > 0.0:
                kept = [v for v in values if abs(v - mean) <= outlier_z * std]
                if kept:
                    values = kept
        if not values:
            return None, False

        values.sort()
        result = values[len(values) // 2] if use_median else sum(values) / len(values)
        if 0.0 < ema_alpha <= 1.0:
            if self._ema_distance is None:
                self._ema_distance = result
            else:
                self._ema_distance = (
                    1 - ema_alpha
                ) * self._ema_distance + ema_alpha * result
            result = self._ema_distance
        self._last_distance = result
        self._last_distance_ts = now
        return result, True

    def _read_touch(self, dog: Any, now: float) -> tuple[str, bool]:
        debounce_s = max(
            0.0, _safe_float(self._sensor_cfg.get("touch_debounce_s", 0.05), 0.05)
        )
        try:
            raw = dog.dual_touch.read() or "N"
        except Exception:  # noqa: BLE001
            logger.debug("Touch read failed", exc_info=True)
            return self._last_touch, False
        if raw != self._last_touch and (now - self._last_touch_ts) >= debounce_s:
            self._last_touch = raw
            self._last_touch_ts = now
        return self._last_touch, True

    def _probe_sound(self, dog: Any) -> None:
        """Name the reason the sound sub-device is unusable, once, at start (#183).

        The vendor constructor prints `sound_direction init ... fail` and swallows whatever raised
        there, so on a real Pi the only evidence was a `sound_valid: False` snapshot plus a DEBUG
        traceback per tick. One WARNING that names the attribute and the `pidog` revision is what
        separates "the sensor is not seated" from "this vendor build has no `ears`".
        """
        if getattr(dog, "ears", None) is None:
            self._record_sound_failure("Pidog has no 'ears' attribute")

    def _record_sound_failure(self, reason: str) -> None:
        if self._sound_reason is not None:
            return
        self._sound_reason = f"{reason} (pidog {_pidog_version()})"
        logger.warning(
            "Sound sensor unavailable: %s; sound_valid stays False for this session",
            self._sound_reason,
        )

    def _read_sound(self, dog: Any) -> tuple[bool, int | None, bool]:
        if self._sound_reason is not None:
            return False, None, False
        ears = getattr(dog, "ears", None)
        if ears is None:
            self._record_sound_failure("Pidog has no 'ears' attribute")
            return False, None, False
        only_on_detect = bool(self._sensor_cfg.get("sound_direction_on_detect", True))
        try:
            detected = bool(ears.isdetected())
        except AttributeError as exc:
            # The attribute is there but the method is not: a vendor revision this HAL was not
            # written against, not a transient bus error. Latch it and report once.
            self._record_sound_failure(f"{type(exc).__name__}: {exc}")
            return False, None, False
        except Exception:  # noqa: BLE001
            logger.debug("Sound detect failed", exc_info=True)
            return False, None, False
        if not detected and only_on_detect:
            return False, None, True
        try:
            direction = int(ears.read())
        except Exception:  # noqa: BLE001
            logger.debug("Sound direction read failed", exc_info=True)
            return detected, None, False
        return detected, direction, True

    def _read_battery(self, dog: Any, now: float) -> tuple[float | None, bool]:
        """Pack voltage, cached for `sensors.battery_poll_s`.

        Three decisions live here. The read is an ADC transaction on the bus the servos share, so it
        runs slower than the snapshot and the last good value is what gets reported in between. A
        value outside 3-60 V is a sense line that is not there (a floating input reads near 0), not a
        flat pack, so it is reported invalid rather than refusing every motion for the session. And
        the vendor's `Pidog.get_battery_voltage` forwards to a deprecated `robot_hat` shim that warns
        on every call, so the warning is suppressed here instead of flooding the log at poll rate.
        """
        poll_s = max(0.0, _safe_float(self._sensor_cfg.get("battery_poll_s", 2.0), 2.0))
        if self._battery_v is not None and poll_s > 0 and (now - self._battery_ts) < poll_s:
            return self._battery_v, True
        reader = getattr(dog, "get_battery_voltage", None)
        if not callable(reader):
            return None, False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                volts = as_float(reader(), -1.0)
        except Exception:  # noqa: BLE001 - one failed ADC read is not a broken dog
            logger.debug("Battery read failed", exc_info=True)
            return self._battery_v, False
        # The timestamp moves on every completed read, so a dead feed is polled at the same slow
        # cadence as a live one instead of being retried every tick.
        self._battery_ts = now
        if not 3.0 <= volts <= 60.0:
            logger.debug("Battery reading %.2f V is out of range; reporting no reading", volts)
            self._battery_v = None
            return None, False
        self._battery_v = volts
        return volts, True

    def _read_imu(
        self, dog: Any
    ) -> tuple[tuple[float, float, float] | None, tuple[float, float, float] | None, bool]:
        try:
            acc_raw = dog.accData
            gyro_raw = dog.gyroData
            imu = getattr(dog, "imu", None)
            acc = to_physical(
                (
                    _safe_float(acc_raw[0], 0.0),
                    _safe_float(acc_raw[1], 0.0),
                    _safe_float(acc_raw[2], 0.0),
                ),
                getattr(imu, "acc_scale", ACC_LSB_PER_G),
                ACC_LSB_PER_G,
                getattr(imu, "acc_bias", None),
            )
            gyro = to_physical(
                (
                    _safe_float(gyro_raw[0], 0.0),
                    _safe_float(gyro_raw[1], 0.0),
                    _safe_float(gyro_raw[2], 0.0),
                ),
                getattr(imu, "gyro_scale", GYRO_LSB_PER_DPS),
                GYRO_LSB_PER_DPS,
                getattr(imu, "gyro_bias", None),
            )
        except Exception:  # noqa: BLE001
            logger.debug("IMU read failed", exc_info=True)
            return None, None, False

        alpha = _safe_float(self._sensor_cfg.get("imu_lpf_alpha", 0.0), 0.0)
        if 0.0 < alpha <= 1.0:
            self._acc_lpf = self._low_pass(self._acc_lpf, acc, alpha)
            self._gyro_lpf = self._low_pass(self._gyro_lpf, gyro, alpha)
            acc = self._acc_lpf
            gyro = self._gyro_lpf
        return acc, gyro, True

    @staticmethod
    def _low_pass(
        previous: tuple[float, float, float] | None,
        current: tuple[float, float, float],
        alpha: float,
    ) -> tuple[float, float, float]:
        if previous is None:
            return current
        return cast(
            tuple[float, float, float],
            tuple(
                (1 - alpha) * prev + alpha * cur
                for prev, cur in zip(previous, current, strict=False)
            ),
        )

    # ---------------------------------------------------------------- actions

    def actions(self) -> frozenset[str]:
        """Everything this HAL can run: its own actions plus the vendor's, read once and cached."""
        return DOG_ACTIONS | self._vendor_actions()

    def _vendor_actions(self) -> frozenset[str]:
        if self._vendor_action_names is None:
            self._vendor_action_names = self._read_vendor_actions()
        return self._vendor_action_names

    def _read_vendor_actions(self) -> frozenset[str]:
        """Best-effort read of the installed `ActionFlow`'s operation names.

        `ActionFlow` is a vendor internal, not a documented API, and the attribute holding its
        operations has moved between builds — so this probes the plausible names and reports what
        it finds. An empty result is honest: `GET /api/v1/repertoire` then falls back to the
        actions the runtime classifies, and a device run is what confirms the rest (A4). Nothing
        here may raise: a workstation has no `pidog` at all.
        """
        try:
            flow = self._ensure_action_flow()
        except Exception:  # noqa: BLE001 - no vendor package, or a vendor that failed to start
            logger.debug("Vendor action list unavailable", exc_info=True)
            return frozenset()
        names: set[str] = set()
        for attribute in ("actions", "action_dict", "action_map", "operations", "operation_map"):
            table = getattr(flow, attribute, None)
            if isinstance(table, Mapping):
                names.update(str(key) for key in table)
            elif isinstance(table, (set, frozenset, list, tuple)):
                names.update(str(item) for item in table)
        if not names:
            logger.debug("ActionFlow exposes no readable action list; the repertoire stays partial")
        return frozenset(canonical_action(name) for name in names if name)

    def action(self, name: str, params: dict[str, Any]) -> None:
        key = name.strip().lower()
        # Audio is dispatched before the servo lock is taken. The vendor plays on its own thread,
        # but that is not a promise (`_say`), and a blocking `speak()` holding the one bus a gait
        # needs would stall the tick.
        if key == "sound":
            self.sound(str(params.get("name", "")), as_int(params.get("volume"), 70))
            return
        if key == "speak":
            self.speak(str(params.get("text", "")), as_int(params.get("volume"), 70))
            return
        # The strip is not the servo bus either. `set_mode` only stores the effect the vendor's own
        # strip thread renders — attribute writes and `is_changed`, no I/O — so the lock bought
        # nothing for it and cost the caller whatever else held it: `SensorService` polls `read()`
        # off the loop (`hal/sensors.py:151`, `hal/vendor.py:247`) and that sequence owns `_bus` for
        # ~0.1-0.3 s, which made an LED write look like 0.10-0.35 s of tick time (#393). Calling
        # `set_mode` while the vendor renders is its documented usage: `pidog.py` shows frames on
        # that thread regardless of who sets the next mode.
        if key == "rgb":
            self._rgb(params)
            return
        # The bus is not re-entrant and it is not free: `do_action(wait=True)` can hold it for the
        # length of a step. Every caller that is not the decision loop already runs on its own
        # worker, so waiting here costs that worker a turn, never the tick.
        with self._bus:
            if key == "head":
                self._head(params)
            elif key == "rpy":
                self._rpy(params)
            elif key == "stop":
                self._stop_locked()
            elif {"speed", "steps", "wait"} & set(params):
                # A supervised step: the caller wants this one movement, synchronously, at a given
                # speed (closed-loop turning reads the heading between steps).
                self._direct(key, params)
            else:
                # Fire and forget: the vendor queue runs it while the loop moves on.
                self._ensure_action_flow().add_action(key.replace("_", " "))

    def _direct(self, key: str, params: Mapping[str, Any]) -> None:
        dog = self._ensure_dog()
        if not hasattr(dog, "do_action"):
            self._ensure_action_flow().add_action(key.replace("_", " "))
            return
        dog.do_action(
            key,
            step_count=max(1, as_int(params.get("steps"), 1)),
            speed=as_int(params.get("speed"), 200),
        )
        if params.get("wait") and hasattr(dog, "wait_all_done"):
            dog.wait_all_done()

    def _head(self, params: Mapping[str, Any]) -> None:
        dog = self._ensure_dog()
        if not hasattr(dog, "head_move"):
            return
        # The vendor reads a target as `[yaw, roll, pitch]`: `head_rpy_to_angle` unpacks it in
        # that order, so pitch belongs in slot 2. Sending `[yaw, pitch, 0]` rolled the head by the
        # caller's pitch and left the pitch channel at zero (#59).
        dog.head_move(
            [[as_float(params.get("yaw"), 0.0), 0.0, as_float(params.get("pitch"), 0.0)]],
            speed=as_int(params.get("speed"), 70),
        )
        if params.get("wait") and hasattr(dog, "wait_head_done"):
            dog.wait_head_done()

    def _rgb(self, params: Mapping[str, Any]) -> None:
        strip = getattr(self._ensure_dog(), "rgb_strip", None)
        if strip is None or not hasattr(strip, "set_mode"):
            return
        style = str(params.get("style", "breath"))
        color = str(params.get("color", "blue"))
        brightness = as_float(params.get("brightness"), 0.7)
        # `bps` is the effect's rate. It used to be dropped here, so every effect ran at the
        # vendor's default and no caller could make an LED breathe faster.
        bps = as_float(params.get("bps"), 1.0)
        try:
            strip.set_mode(style, color, bps=bps, brightness=brightness)
        except TypeError:
            # A vendor build whose `set_mode` predates `bps`: keep the effect, lose the rate.
            logger.debug("set_mode rejected bps; using the vendor default rate")
            strip.set_mode(style, color, brightness=brightness)

    def _rpy(self, params: Mapping[str, Any]) -> None:
        dog = self._ensure_dog()
        if not hasattr(dog, "set_rpy"):
            return
        dog.set_rpy(
            roll=as_float(params.get("roll"), 0.0),
            pitch=as_float(params.get("pitch"), 0.0),
            yaw=as_float(params.get("yaw"), 0.0),
            pid=True,
        )

    # -------------------------------------------------------------------- audio

    def sound(self, name: str, volume: int = 70) -> None:
        """Queue one of the dog's built-in effects (`docs/PIDOG_PROGRAMMING_GUIDE.md` §4.1)."""
        self._say(str(name), volume)

    def speak(self, text: str, volume: int = 70) -> None:
        """Queue `text` for the vendor's speech path."""
        self._say(str(text), volume)

    def _say(self, text: str, volume: int) -> None:
        """Hand one utterance to the audio worker.

        Nothing here touches the servo bus, and nothing here waits: whether the vendor's call
        blocks is unverified (A5), so the tick is never allowed to find out. One utterance is
        pending at a time and a newer one replaces it — a pet that queues six barks is a pet that
        barks six times, late.
        """
        if not text or self._closed:
            return
        self._ensure_audio_thread()
        payload = (text, max(0, min(_safe_int(volume, 70), 100)))
        try:
            self._audio.put_nowait(payload)
        except queue.Full:
            try:
                self._audio.get_nowait()
            except queue.Empty:  # pragma: no cover - another thread drained it
                pass
            try:
                self._audio.put_nowait(payload)
            except queue.Full:  # pragma: no cover - another thread refilled it
                logger.debug("Audio queue busy; dropped %r", text)

    def _ensure_audio_thread(self) -> None:
        with self._audio_lock:
            if self._audio_thread is not None and self._audio_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._audio_worker, name="houndmind-audio", daemon=True
            )
            self._audio_thread = thread
            thread.start()

    def _audio_worker(self) -> None:
        while True:
            item = self._audio.get()
            if item is None:
                return
            self._play(*item)

    def _play(self, text: str, volume: int) -> None:
        """One blocking vendor call, on the audio thread, with every failure contained."""
        try:
            speaker = getattr(self._ensure_dog(), "speak", None)
            if not callable(speaker):
                logger.debug("Vendor exposes no speak(); %r dropped", text)
                return
            try:
                played = speaker(text, volume=volume)
            except TypeError:
                # Older vendor builds take the text only.
                played = speaker(text)
            # `False` is the vendor's way of saying it could not find the effect
            # (`docs/pidog/PIDOG-EXPRESSION.md:81`), and it is the only signal there is: `sound()`
            # and `speak()` return `None` either way, so a typo in a cue name would otherwise be a
            # no-op with no trace anywhere an operator can read (#81).
            if played is False:
                self._warn_missing_sound(text)
        except Exception:  # noqa: BLE001 - audio is cosmetic and must not kill the worker
            logger.warning("Audio output failed", exc_info=True)

    def _warn_missing_sound(self, name: str) -> None:
        """Name the missing effect once; a repeated cue then stays silent about it."""
        if name in self._warned_sounds:
            return
        self._warned_sounds.add(name)
        logger.warning("Sound %r not found in the vendor's sounds directory", name)

    def _stop_audio(self) -> None:
        """Wake the worker so it can exit; it is a daemon, so it never blocks shutdown."""
        try:
            self._audio.get_nowait()
        except queue.Empty:
            pass
        try:
            self._audio.put_nowait(None)
        except queue.Full:  # pragma: no cover - the drain above made room
            pass

    # ------------------------------------------------------------- calibration

    def read_offsets(self) -> dict[str, float]:
        """The trim the vendor loaded from its own config file, name -> signed degrees."""
        with self._bus:
            return self._read_offsets_locked(self._ensure_dog())

    def _read_offsets_locked(self, dog: Any) -> dict[str, float]:
        """`Robot.offset` for each group, translated to joint names. Absent, never zeroed."""
        offsets: dict[str, float] = {}
        for group, names in SERVO_GROUPS.items():
            values = getattr(getattr(dog, group, None), "offset", None)
            if not isinstance(values, (list, tuple)) or len(values) != len(names):
                logger.debug("No readable %s offset list on the vendor object", group)
                continue
            for name, value in zip(names, values, strict=True):
                try:
                    offsets[name] = float(value)
                except (TypeError, ValueError):
                    logger.debug("Unreadable %s offset %r", name, value)
        return offsets

    def apply_offsets(
        self,
        offsets: Mapping[str, float],
        pose: Mapping[str, float] | None = None,
    ) -> None:
        """Save the trim group by group, merged over what the hardware already has.

        The vendor's setters replace a whole list, so an offset for one joint must never zero the
        other seven: the current values are read first, the requested ones merged in, and the full
        list written. Each setter also *re-poses* — `reset_list=None` is the vendor's "drive the legs
        to zero" branch (`pidog.py:686-692`) — so a legs write lands on the angles the dog already
        holds (#263), and `pose` lets a calibration tool choose them instead. Nothing in the runtime
        passes `pose`.
        """
        with self._bus:
            dog = self._ensure_dog()
            current = self._read_offsets_locked(dog)
            merged: dict[str, dict[str, float]] = {}
            for name, value in (offsets or {}).items():
                group = SERVO_GROUP_OF.get(name)
                if group is None:
                    logger.warning("Ignoring unknown servo offset %r", name)
                    continue
                if name not in current:
                    # No baseline for this joint: writing the group would invent the rest of it.
                    logger.warning("No current %s offset for %r; not writing it", group, name)
                    continue
                number = as_float(value, current[name])
                clamped = max(-SERVO_OFFSET_LIMIT_DEG, min(SERVO_OFFSET_LIMIT_DEG, number))
                if clamped != number:
                    logger.warning("Servo offset %s=%.2f clamped to %.2f", name, number, clamped)
                merged.setdefault(group, {})[name] = clamped

            for group, values in merged.items():
                names = SERVO_GROUPS[group]
                if any(name not in current for name in names):
                    logger.warning("Incomplete %s offsets; not writing that group", group)
                    continue
                self._write_group(
                    dog,
                    group,
                    [values.get(name, current[name]) for name in names],
                    pose,
                )

    def _write_group(
        self,
        dog: Any,
        group: str,
        values: list[float],
        pose: Mapping[str, float] | None = None,
    ) -> None:
        """Save one group through its own vendor entry point; no invented values, no reset pose."""
        setter_name = _GROUP_SETTERS[group]
        setter = getattr(dog, setter_name, None)
        if not callable(setter):
            logger.warning("Vendor exposes no %s(); %s offsets not saved", setter_name, group)
            return
        try:
            if group == "legs":
                angles = self._pose_values(dog, group, pose)
                if angles is None:
                    # `reset_list=None` would drive all eight leg servos to zero: skip this save.
                    logger.warning("No readable %s angles; not saving that group", group)
                    return
                setter(values, reset_list=angles)
            else:
                # The vendor's head and tail setters re-pose unconditionally and upstream has no
                # stored-pose path, which is why the contract no longer promises otherwise (#263).
                setter(values)
        except Exception:  # noqa: BLE001 - a vendor save failure is logged, not fatal
            logger.warning("Failed to save %s offsets", group, exc_info=True)

    def _pose_values(
        self,
        dog: Any,
        group: str,
        pose: Mapping[str, float] | None,
    ) -> list[float] | None:
        """The angles a legs write leaves the dog in: the caller's, else where it already is."""
        names = SERVO_GROUPS[group]
        if pose is not None:
            requested: list[float] = []
            for name in names:
                raw = pose.get(name)
                if raw is None:
                    logger.warning("Pose is missing %r; not saving %s offsets", name, group)
                    return None
                try:
                    requested.append(float(raw))
                except (TypeError, ValueError):
                    logger.warning("Unreadable pose for %r; not saving %s offsets", name, group)
                    return None
            return requested
        return self._current_angles_locked(dog, group)

    def _current_angles_locked(self, dog: Any, group: str) -> list[float] | None:
        """The angles the vendor last commanded for the group, or None when it cannot say."""
        names = SERVO_GROUPS[group]
        attribute = _ANGLE_ATTRS[group]
        group_object = getattr(dog, group, None)
        for owner in (dog, group_object):
            values = getattr(owner, attribute, None)
            if not isinstance(values, (list, tuple)) or len(values) != len(names):
                continue
            try:
                return [float(value) for value in values]
            except (TypeError, ValueError):
                continue
        return None

    def nudge_joint(self, name: str, degrees: float) -> None:
        """Move one joint by `degrees` from where it is now, slowly, capped at the nudge limit.

        A calibration probe: the trim tools step one joint and watch the IMU. No offset is written
        here, so nudging back restores the pose exactly.
        """
        group = SERVO_GROUP_OF.get(name)
        if group is None:
            raise ValueError(f"unknown joint {name!r}")
        index = SERVO_GROUPS[group].index(name)
        delta = as_float(degrees, 0.0)
        delta = max(-NUDGE_LIMIT_DEG, min(NUDGE_LIMIT_DEG, delta))
        if delta == 0.0:
            return
        with self._bus:
            dog = self._ensure_dog()
            angles = self._current_angles_locked(dog, group)
            if angles is None:
                raise RuntimeError(f"current {group} angles are unreadable; refusing to guess")
            commanded = angles[index] + delta
            angles[index] = max(
                -SERVO_ANGLE_LIMIT_DEG, min(SERVO_ANGLE_LIMIT_DEG, commanded)
            )
            if angles[index] != commanded:
                logger.warning("Nudge of %s clamped to %.1f deg", name, angles[index])
            if group == "legs":
                dog.legs_move([angles], immediately=True, speed=_NUDGE_SPEED)
            elif group == "head":
                # `head_move_raw` takes servo angles; `head_move` would read them as yaw/roll.
                dog.head_move_raw([angles], immediately=True, speed=_NUDGE_SPEED)
            else:
                dog.tail_move([angles], immediately=True, speed=_NUDGE_SPEED)

    def read_imu_calibration(self) -> dict[str, list[float]] | None:
        """What the vendor loaded for the IMU, or None when it cannot say (#259).

        Includes `acc_offset`/`gyro_offset`, which are **not** part of the stored calibration: they
        are the shift `Pidog` computes once at startup under the assumption that the dog is level with
        its X axis pointing down (`pidog.py:474-479`), and adds to every sample (`:490-495`). A PiDog
        boots lying down, so that assumption is usually false and the shift is a constant lie in the
        data - a caller that measures the sensor has to know whether it is in force.
        """
        with self._bus:
            dog = self._ensure_dog()
            imu = getattr(dog, "imu", None)
            if imu is None:
                return None
            found: dict[str, list[float]] = {}
            for key in ("acc_bias", "acc_scale", "gyro_bias", "gyro_scale"):
                values = getattr(imu, key, None)
                if not isinstance(values, (list, tuple)) or len(values) != 3:
                    logger.debug("No readable IMU %s on the vendor object", key)
                    continue
                try:
                    found[key] = [float(value) for value in values]
                except (TypeError, ValueError):
                    logger.debug("Unreadable IMU %s: %r", key, values)
            for key, attribute in (
                ("acc_offset", "imu_acc_offset"),
                ("gyro_offset", "imu_gyro_offset"),
            ):
                values = getattr(dog, attribute, None)
                if not isinstance(values, (list, tuple)) or len(values) != 3:
                    continue
                try:
                    found[key] = [float(value) for value in values]
                except (TypeError, ValueError):
                    continue
            return found or None

    def set_imu_calibration(
        self,
        acc_bias: Sequence[float] | None = None,
        acc_scale: Sequence[float] | None = None,
        gyro_bias: Sequence[float] | None = None,
        gyro_scale: Sequence[float] | None = None,
    ) -> bool:
        """Persist through the vendor's own setters, which write `pidog.conf` themselves.

        An omitted argument is passed as None, and the vendor's setters ignore None, so a caller
        that measured only the accelerometer cannot silently zero the gyroscope's calibration.
        """
        if all(value is None for value in (acc_bias, acc_scale, gyro_bias, gyro_scale)):
            return False
        with self._bus:
            dog = self._ensure_dog()
            imu = getattr(dog, "imu", None)
            if imu is None:
                logger.warning("No vendor IMU object; the calibration was not saved")
                return False
            saved = True
            if acc_bias is not None or acc_scale is not None:
                saved = self._call_calibration_setter(
                    imu, "set_acc_calibration", acc_bias, acc_scale
                ) and saved
            if gyro_bias is not None or gyro_scale is not None:
                saved = self._call_calibration_setter(
                    imu, "set_gyro_calibration", gyro_bias, gyro_scale
                ) and saved
            # The vendor's startup offset double-counts against `calibrate_*` and was computed from a
            # false assumption, so saving a calibration clears it - persisted, so the next boot does
            # not re-invent one from whatever pose the dog happened to be in.
            saved = self._clear_runtime_offsets(dog) and saved
            return saved

    @staticmethod
    def _clear_runtime_offsets(dog: Any) -> bool:
        """Zero `imu_acc_offset`/`imu_gyro_offset` and persist it, so the sensor speaks for itself."""
        setter = getattr(dog, "set_imu_offsets", None)
        if not callable(setter):
            logger.warning("Vendor exposes no set_imu_offsets(); the startup offset stays in force")
            return False
        try:
            setter(acc_offset=[0, 0, 0], gyro_offset=[0, 0, 0])
        except Exception:  # noqa: BLE001 - a vendor write failure is reported, not fatal
            logger.warning("Vendor rejected zeroed IMU runtime offsets", exc_info=True)
            return False
        return True

    @staticmethod
    def _call_calibration_setter(
        imu: Any,
        name: str,
        bias: Sequence[float] | None,
        scale: Sequence[float] | None,
    ) -> bool:
        setter = getattr(imu, name, None)
        if not callable(setter):
            logger.warning("Vendor exposes no %s(); the calibration was not saved", name)
            return False
        try:
            setter(bias=bias, scale=scale)
        except Exception:  # noqa: BLE001 - a vendor save failure is reported, not fatal
            logger.warning("Vendor rejected %s", name, exc_info=True)
            return False
        return True

    def reset_imu_calibration(self) -> bool:
        """Clear the stored calibration and the vendor's startup offset; back to the datasheet."""
        with self._bus:
            dog = self._ensure_dog()
            imu = getattr(dog, "imu", None)
            resetter = getattr(imu, "reset_calibration", None)
            if not callable(resetter):
                logger.warning("Vendor exposes no reset_calibration(); nothing cleared")
                return False
            try:
                resetter()
            except Exception:  # noqa: BLE001 - report, do not crash a calibration run
                logger.warning("Vendor failed to reset the IMU calibration", exc_info=True)
                return False
            # Clearing a calibration has to clear the startup shift too, or the next measurement is
            # taken through an offset nobody can see.
            self._clear_runtime_offsets(dog)
            return True

    def stop(self) -> None:
        """Stop motion now: clear the queued actions, then ask the vendor to halt."""
        with self._bus:
            self._stop_locked()

    def _stop_locked(self) -> None:
        flow = self._action_flow
        if flow is not None and hasattr(flow, "clear_actions"):
            try:
                flow.clear_actions()
            except Exception:  # noqa: BLE001
                logger.debug("Failed to clear the action queue", exc_info=True)
        dog = self._dog
        if dog is None:
            return
        for method in ("emergency_stop", "stop", "stop_all", "halt", "standby"):
            if hasattr(dog, method):
                try:
                    getattr(dog, method)()
                    logger.warning("Hardware stop via %s", method)
                    return
                except Exception:  # noqa: BLE001
                    logger.debug("Hardware stop via %s failed", method, exc_info=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_audio()
        flow = self._action_flow
        if flow is not None and hasattr(flow, "stop"):
            try:
                flow.stop()
            except Exception:  # noqa: BLE001
                logger.debug("Failed to stop the action queue", exc_info=True)
        self._action_flow = None
        if self._dog is not None and self._dog_owned:
            try:
                self._dog.close()
            except Exception:  # noqa: BLE001
                logger.warning("Failed to close Pidog", exc_info=True)
            finally:
                # The vendor's close() hijacks SIGINT with a handler that only prints "Please wait"
                # and arms a five second SIGALRM it never cancels (pidog.py:277-286, with the cancel
                # commented out at :326). Left alone, Ctrl-C stops working in a process that looks
                # hung - the natural reaction is to start it again - and the alarm fires later,
                # inside whatever runs next, including our own exit.
                try:
                    import signal

                    # `signal.alarm` is POSIX-only, so the stubs mypy resolves here lack it.
                    signal.alarm(0)  # type: ignore[attr-defined]
                    signal.signal(signal.SIGINT, signal.SIG_DFL)
                except (ImportError, AttributeError, ValueError, OSError):
                    logger.debug("Could not restore the signal state after close", exc_info=True)
        self._dog = None