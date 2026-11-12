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
from collections.abc import Callable, Mapping
from typing import Any, cast

from houndmind_ai.calibration.servo_calibration import apply_servo_offsets
from houndmind_ai.hal.iface import DOG_ACTIONS, SensorSnapshot, as_float, as_int

# A pure spelling helper from the command vocabulary: `ActionFlow` names come back spaced
# ("turn left") and everything above the HAL compares canonical names. `kernel/commands.py`
# imports nothing but the stdlib, so this does not drag the runtime into the HAL.
from houndmind_ai.kernel.commands import canonical_action

logger = logging.getLogger(__name__)

__all__ = ["PidogHAL"]


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


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

    def start(self) -> None:
        """Open the dog and start its action queue. Raises if the vendor package is absent."""
        self._ensure_dog()
        self._ensure_action_flow()

    @property
    def vendor(self) -> Any:
        """The raw `Pidog`. Only for `calibration/workflow.py`, which still speaks its API.

        Everything else must use the `DogHAL` methods: a second caller of this property is a
        second place that knows the vendor exists.
        """
        return self._ensure_dog()

    # ----------------------------------------------------------------- sensors

    def read(self) -> SensorSnapshot:
        now = self._clock()
        with self._bus:
            dog = self._ensure_dog()

            distance_cm, distance_valid = self._read_distance(dog, now)
            touch, touch_valid = self._read_touch(dog, now)
            sound_detected, sound_direction, sound_valid = self._read_sound(dog)
            acc, gyro, imu_valid = self._read_imu(dog)

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

    def _read_sound(self, dog: Any) -> tuple[bool, int | None, bool]:
        only_on_detect = bool(self._sensor_cfg.get("sound_direction_on_detect", True))
        try:
            detected = bool(dog.ears.isdetected())
        except Exception:  # noqa: BLE001
            logger.debug("Sound detect failed", exc_info=True)
            return False, None, False
        if not detected and only_on_detect:
            return False, None, True
        try:
            direction = int(dog.ears.read())
        except Exception:  # noqa: BLE001
            logger.debug("Sound direction read failed", exc_info=True)
            return detected, None, False
        return detected, direction, True

    def _read_imu(
        self, dog: Any
    ) -> tuple[tuple[float, float, float] | None, tuple[float, float, float] | None, bool]:
        try:
            acc_raw = dog.accData
            gyro_raw = dog.gyroData
            acc = cast(
                tuple[float, float, float],
                (
                    _safe_float(acc_raw[0], 0.0),
                    _safe_float(acc_raw[1], 0.0),
                    _safe_float(acc_raw[2], 0.0),
                ),
            )
            gyro = cast(
                tuple[float, float, float],
                (
                    _safe_float(gyro_raw[0], 0.0),
                    _safe_float(gyro_raw[1], 0.0),
                    _safe_float(gyro_raw[2], 0.0),
                ),
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
        # The bus is not re-entrant and it is not free: `do_action(wait=True)` can hold it for the
        # length of a step. Every caller that is not the decision loop already runs on its own
        # worker, so waiting here costs that worker a turn, never the tick.
        with self._bus:
            if key == "head":
                self._head(params)
            elif key == "rgb":
                self._rgb(params)
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

    def apply_offsets(self, offsets: Mapping[str, float]) -> None:
        apply_servo_offsets(self._ensure_dog(), dict(offsets or {}))

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
        self._dog = None