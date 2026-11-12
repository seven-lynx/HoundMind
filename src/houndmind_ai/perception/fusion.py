"""The fused snapshot behaviour, navigation and attention all read.

Every key here is a *measurement*, so every measurement can fail, and a failed read has to stay
distinguishable from a real one (`20-hardware.md`). `perception["obstacle"]` is not "a wall is
close"; it is derived from a sonar answer that may not exist. Occupancy is the same bargain struck
with a camera.

Occupancy (`P4 PL3`) is the one key this module does not measure itself. A detector publishes
`context["faces"]` (`optional/face_recognition.py:169-174`) and this module turns it into a fact
with hysteresis:

- **no detector, no frame, or a payload older than `max_age_s`** -> `occupancy = None`,
  `occupancy_valid = False`. Unknown, never "nobody".
- **a fresh frame with nobody in it** -> `False` at once from an unknown start: claiming an empty
  room is not a claim about a person.
- **a fresh frame with somebody in it** -> `True` after `min_frames` consecutive frames, and the
  claim is dropped only after `release_frames` of an empty room, so a blink does not flap it.
- **a republished frame** (same `timestamp`) counts once. `faces` stays in the context between
  frames, and counting it again would let the counter announce a person the camera saw once.

`perception` is written from `tick` and from the sensor subscription, so the dict is assembled in
exactly one place (`_update_from_reading`) and occupancy is merged there: two writers to one key is
how a snapshot starts flapping.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

from houndmind_ai.core.module import Module

__all__ = [
    "DEFAULT_OCCUPANCY_MAX_AGE_S",
    "DEFAULT_OCCUPANCY_MIN_FRAMES",
    "DEFAULT_OCCUPANCY_RELEASE_FRAMES",
    "PerceptionModule",
]

logger = logging.getLogger(__name__)

# A frame older than this says nothing about now. One second: the shipped loop is 5 Hz, and a
# detector running slower than that reports its own staleness through `timestamp` anyway.
DEFAULT_OCCUPANCY_MAX_AGE_S = 1.0
# Frames needed to claim somebody is there, and to stop claiming it.
DEFAULT_OCCUPANCY_MIN_FRAMES = 3
DEFAULT_OCCUPANCY_RELEASE_FRAMES = 5


def _safe_float(v: Any, default: float = 0.0) -> float:
    """A float, or the default. `None`, non-numbers and NaN are all missing, never zero."""
    if v is None or isinstance(v, bool):
        return default
    try:
        value = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(value):
        return default
    return value


def _opt_float(v: Any) -> float | None:
    """The value as a float, or `None` when it is missing — for a timestamp, where 0 is a value."""
    if v is None or isinstance(v, bool):
        return None
    try:
        value = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _safe_int(v: Any, default: int) -> int:
    """An int, or the default. A string such as `"three"` is not a count and takes the default."""
    if v is None or isinstance(v, bool):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class PerceptionModule(Module):
    def __init__(
        self,
        name: str,
        enabled: bool = True,
        required: bool = False,
        clock: Callable[[], float] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        # Unknown kwargs are tolerated on purpose: `main.cfg()` hands over a whole config section,
        # and a key this module does not know must not take the runtime down (20-hardware rule).
        self._context = None
        self._sensor_service = None
        # Injectable so a test can age a frame instead of sleeping through the staleness window.
        self._clock = clock or time.time
        self._occupancy: bool | None = None
        self._occupancy_valid = False
        self._occupancy_frames = 0
        # What the recent frames say, and the frame they came from: the timestamp is how a
        # republished `faces` payload is told apart from a new one.
        self._candidate: bool | None = None
        self._last_faces_ts: float | None = None

    def start(self, context) -> None:
        self._context = context
        service = context.get("sensor_service")
        if service is not None and hasattr(service, "subscribe"):
            self._sensor_service = service
            service.subscribe(self._on_sensor_reading)

    def tick(self, context) -> None:
        # Occupancy first: it is the only key here that does not come from the sensor reading, and
        # `_update_from_reading` is where both are merged into one snapshot.
        self._update_occupancy(context)
        reading = context.get("sensor_reading")
        if reading is not None:
            self._update_from_reading(context, reading)

    def stop(self, context) -> None:
        if self._sensor_service is not None:
            try:
                self._sensor_service.unsubscribe(self._on_sensor_reading)
            except Exception:  # noqa: BLE001
                pass

    def _update_occupancy(self, context) -> None:
        """Someone in frame, with hysteresis, from whatever the detector last published.

        The unknown exits come first and on purpose: a missing detector, a missing frame and a
        stale frame are all *not readings*, and reporting them as an empty room would let a
        dropped frame argue that nobody is there (`20-hardware.md`).
        """
        settings = (context.get("settings") or {}).get("perception", {})
        cfg = settings.get("occupancy", {}) if isinstance(settings, Mapping) else {}
        max_age_s = _safe_float(cfg.get("max_age_s"), DEFAULT_OCCUPANCY_MAX_AGE_S)
        min_frames = max(1, _safe_int(cfg.get("min_frames"), DEFAULT_OCCUPANCY_MIN_FRAMES))
        release_frames = max(
            1, _safe_int(cfg.get("release_frames"), DEFAULT_OCCUPANCY_RELEASE_FRAMES)
        )

        faces = context.get("faces")
        payload = faces if isinstance(faces, Mapping) else None
        stamp = _opt_float(payload.get("timestamp")) if payload is not None else None
        if stamp is None or (max_age_s > 0 and self._clock() - stamp > max_age_s):
            self._occupancy = None
            self._occupancy_valid = False
            self._occupancy_frames = 0
            self._candidate = None
            self._last_faces_ts = None
            return

        if stamp == self._last_faces_ts:
            # The frame the last tick already counted. `faces` outlives the tick that wrote it, so
            # counting it again would fake the hysteresis this counter exists for.
            self._occupancy_valid = True
            return

        self._last_faces_ts = stamp
        self._occupancy_valid = True
        detected = payload.get("detected") if payload is not None else None
        present = bool(detected) if isinstance(detected, (list, tuple)) else False

        if present == self._candidate:
            self._occupancy_frames += 1
        else:
            self._candidate = present
            self._occupancy_frames = 1

        # Claiming somebody is there needs `min_frames` of evidence; an empty room from an unknown
        # start needs none, because there is no claim to protect yet. Once a claim exists, only
        # `release_frames` of emptiness takes it back — that window is what a blink has to survive.
        if present:
            threshold = min_frames
        else:
            threshold = 1 if self._occupancy is None else release_frames
        if self._occupancy_frames >= threshold:
            self._occupancy = present

    def _occupancy_fields(self) -> dict[str, object]:
        """Occupancy's slice of the snapshot. `occupancy` is `None` whenever nothing measured it."""
        return {
            "occupancy": self._occupancy,
            "occupancy_valid": self._occupancy_valid,
            "occupancy_frames": self._occupancy_frames,
        }

    def _on_sensor_reading(self, reading) -> None:
        if self._context is None:
            return
        self._update_from_reading(self._context, reading)

    def _update_from_reading(self, context, reading) -> None:
        distance = getattr(reading, "distance_cm", None)
        touch = getattr(reading, "touch", "N")
        sound_detected = getattr(reading, "sound_detected", False)
        sound_direction = getattr(reading, "sound_direction", None)

        settings = (context.get("settings") or {}).get("perception", {})
        obstacle_cm = settings.get("obstacle_cm", 20)

        # Minimal, lightweight localization hint using IMU heading + distance
        # This is intentionally coarse — it emits a `pose_hint` into the
        # context for downstream modules to use as a soft localization cue.
        fusion_cfg = settings.get("fusion", {}) if isinstance(settings, dict) else {}
        anchor_max_cm = _safe_float(fusion_cfg.get("fusion_anchor_distance_cm", 120), 120.0)
        min_conf = _safe_float(fusion_cfg.get("fusion_min_confidence", 0.3), 0.3)

        obstacle = False
        if isinstance(distance, (int, float)) and distance > 0:
            obstacle = distance < obstacle_cm

        context.set(
            "perception",
            {
                "obstacle": obstacle,
                "touch": touch,
                "sound": bool(sound_detected),
                "sound_direction": sound_direction,
                "distance": distance,
                # Occupancy is not a sensor-reading key, but it rides the snapshot so there is one
                # place that says what the dog currently believes rather than two that disagree.
                **self._occupancy_fields(),
            },
        )
        logger.debug("Perception: %s", context.get("perception"))

        # Emit pose_hint when distance is a reasonable anchor and IMU heading exists.
        try:
            if isinstance(distance, (int, float)) and 0 < distance <= anchor_max_cm:
                heading = context.get("current_heading") or (
                    context.get("orientation") or {}
                ).get("heading")
                if heading is not None:
                    hint = {
                        "timestamp": getattr(reading, "timestamp", None) or None,
                        "type": "anchor_distance",
                        "distance_cm": _safe_float(distance, 0.0),
                        "heading_deg": _safe_float(heading, 0.0),
                        "confidence": min(
                            1.0,
                            (anchor_max_cm - _safe_float(distance, 0.0)) / max(1.0, anchor_max_cm),
                        ),
                    }
                    # Apply min confidence filter.
                    if _safe_float(hint.get("confidence", 0.0), 0.0) >= min_conf:
                        context.set("pose_hint", hint)
        except Exception:
            logger.debug("pose_hint calc failed", exc_info=True)
