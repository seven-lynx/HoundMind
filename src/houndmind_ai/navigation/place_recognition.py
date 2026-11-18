"""Recognise a taught place from a camera frame, and correct the pose when two frames agree (#297, #298).

Three rules shape it.

1. **The matcher never runs on the tick's critical path.** At most one frame per `interval_s`, and a
   frame already scored is skipped by its own timestamp, so a 5 Hz tick and a 30 Hz camera do not
   become thirty matches a second.
2. **A refusal is published too.** `place_match` carries `valid: false` with the score that lost, so
   "no idea, best 0.31" is a state a client can show instead of silence that looks like a dead module.
3. **One frame never moves the pose.** Two consecutive frames naming the same place set
   `odometry_reset` and publish `place_fix`; a frame naming a different place starts the count again,
   and a place that has already anchored this visit does not re-anchor on every pair.

`place_match` is only written while the module runs: it ships off, `start()` returns before anything
is published, and a disabled module therefore leaves no stale key behind.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.perception.place_views import (
    PlaceView,
    load_views,
    match_frame,
)

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_MIN_SCORE", "DEFAULT_VIEWS_DIR", "PlaceRecognitionModule"]

#: Where a teach request leaves a view. Beside the places file, so a user who moves
#: `settings.places.path` finds the views next to it.
DEFAULT_VIEWS_DIR = "~/.houndmind/places/views"

#: The shipped threshold. ORB on a 320x240 frame separates rooms; anything lower starts calling two
#: doorways the same room, which is what the two-frame confirmation exists to catch.
DEFAULT_MIN_SCORE = 0.45


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default

class PlaceRecognitionModule(Module):
    """Score the latest camera frame against the stored views, and anchor the pose when it is sure."""

    def __init__(
        self, name: str, enabled: bool = True, required: bool = False, **kwargs: object
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._views: tuple[PlaceView, ...] = ()
        self._views_dir = DEFAULT_VIEWS_DIR
        self._last_frame_ts: float | None = None
        self._last_scored_at = 0.0
        self._pending: str | None = None
        self._agreements = 0
        self._anchored_place: str | None = None
        self._clock = time.monotonic

    def _section(self, context) -> dict:
        section = (context.get("settings") or {}).get("place_recognition", {})
        return section if isinstance(section, dict) else {}

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        try:
            # A camera with no OpenCV is a missing wheel, not a broken dog.
            import cv2  # noqa: F401
        except ImportError as exc:
            self.disable(f"missing dependency: {exc.name or 'opencv'}")
            return
        settings = self._section(context)
        self._views_dir = str(settings.get("views_dir") or DEFAULT_VIEWS_DIR)
        self._views = load_views(self._views_dir)
        context.set("place_match_candidates", [view.place_id for view in self._views])
        if self._views:
            logger.info(
                "Place recognition ready: %d view(s) from %s", len(self._views), self._views_dir
            )
        else:
            logger.info(
                "Place recognition has no views in %s: nothing can be recognised until a place is "
                "taught",
                self._views_dir,
            )
        super().start(context)


    def tick(self, context) -> None:
        settings = self._section(context)
        interval_s = max(0.0, _safe_float(settings.get("interval_s"), 1.0))
        min_score = _safe_float(settings.get("min_score"), DEFAULT_MIN_SCORE)
        confirm = max(1, _safe_int(settings.get("confirm_frames"), 2))

        frame = context.get("vision_frame")
        if frame is None:
            return
        frame_ts = _safe_float(context.get("vision_frame_ts"), 0.0)
        if frame_ts == self._last_frame_ts:
            return
        now = self._clock()
        if now - self._last_scored_at < interval_s:
            return
        self._last_frame_ts = frame_ts
        self._last_scored_at = now

        try:
            result = match_frame(frame, self._views, min_score)
        except Exception as exc:  # noqa: BLE001 - a malformed frame is reported, not raised
            context.set(
                "place_match",
                {
                    "valid": False,
                    "place_id": None,
                    "score": 0.0,
                    "reason": f"frame could not be read: {exc}",
                    "frame_ts": frame_ts,
                },
            )
            self._forget()
            return

        context.set("place_match", {**result.to_dict(), "frame_ts": frame_ts})
        self._confirm(
            context,
            result.place_id if result.valid else None,
            result.score,
            frame_ts,
            confirm,
        )

    def _confirm(
        self, context, place_id: str | None, score: float, frame_ts: float, confirm: int
    ) -> None:
        """Turn agreement between frames into a pose fix, and nothing less into nothing."""
        if place_id is None:
            self._forget()
            return
        if place_id != self._pending:
            self._pending, self._agreements = place_id, 1
        else:
            self._agreements += 1
        if self._agreements < confirm or self._anchored_place == place_id:
            return
        context.set("odometry_reset", True)
        context.set(
            "place_fix",
            {
                "ts": time.time(),
                "place_id": place_id,
                "confidence": round(score, 3),
                # Monotonic, from the frame that earned it: an identity for `localization` to notice
                # without comparing two clock domains.
                "frame_ts": frame_ts,
            },
        )
        self._anchored_place = place_id
        logger.info("Place recognised: %s (score %.2f)", place_id, score)

    def _forget(self) -> None:
        self._pending = None
        self._agreements = 0
        self._anchored_place = None

