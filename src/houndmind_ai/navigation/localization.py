"""Pick the best pose the dog can honestly offer, and say why when it degrades.

The dog cannot always localize itself. This module publishes one key, `localization`, whose pose
comes from the best source currently available, and whose `reason` names what stopped it being
better. The ladder, best first:

- ``slam`` - the pose from `slam_pose` (rtabmap, or a LAN backend). Drops out when the backend is
  absent or ``stub``, when there is no heartbeat, when the pose is stale, or when its confidence is
  below the floor.
- ``place`` - odometry re-anchored at a place `place_recognition` recognised from the camera (#297).
  It outranks dead reckoning because a confirmed view match is an absolute fix: the dog knows which
  room it is in, and the odometry origin has just been moved to that place. It drops out when the fix
  goes stale, and it is never reported from one frame alone - `place_recognition` requires two.
- ``user`` - odometry re-anchored at a point a human dragged the dog to on the console map (M5). It
  sits above every measurement because it is the one source that can say *the map's frame is wrong*:
  someone looking at the dog and the plan is disputing the sources above, and honouring that is the
  whole point of the correction. It decays like any anchor - bounded in age, restarted by the next
  absolute fix, and never reported without a pose behind it.
- ``dead_reckoning`` - the pose from `odometry` (heading x counted steps). Drops out when there is
  no heading, no step it can place, or when its drift confidence decays past the floor.
- ``reactive`` - no pose at all, sonar and head scan only. The floor; it cannot drop further.

The tier is for *ambition*, not correctness: a consumer that needs a pose checks whether it got
one. A transition publishes `localization_event` once, so "it drifted" and "it fell back" are
distinguishable in the logs instead of identical.

Why the stub is not the `slam` tier: `settings.slam_pi4.backend = "stub"` integrates the gyro and
publishes a pose that never leaves the origin, and `docs/FEATURES_GUIDE.md` says not to build a
navigation feature on it. It is dead reckoning under another name, so it is reported as nothing at
all rather than promoted.

Publishes `localization`::

    {"ts": float, "tier": "slam" | "place" | "user" | "dead_reckoning" | "reactive",
     "frame": "slam" | "odometry" | None,
     "pose": {"x": float, "y": float, "yaw_deg": float} | None,
     "confidence": float, "age_s": float, "reason": str | None}

`frame` is not decoration: an `odometry` pose is in **centimetres** from the origin the dog was
reset at, while a `slam` pose is in whatever unit the backend uses (rtabmap reports metres). The
two are never mixed in one key without saying which it is.
"""

from __future__ import annotations

import logging
import time
from enum import StrEnum
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)

__all__ = ["LocalizationModule", "LocalizationTier"]

#: `backend` values that are not SLAM. `stub` is the gyro integrator, whose pose never moves;
#: treating it as the top tier would tell every consumer it is localized when it is not.
NON_SLAM_BACKENDS = ("", "stub")

#: How long a position a human confirmed keeps the top tier. Not a config key: it bounds a claim
#: rather than tuning a feature, and an age nobody can lengthen is what stops a stale declaration
#: from outliving the moment it was true. Thirty seconds is a slow walk across a room.
USER_FIX_MAX_AGE_S = 30.0


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


class LocalizationTier(StrEnum):
    SLAM = "slam"
    PLACE = "place"
    USER = "user"
    DEAD_RECKONING = "dead_reckoning"
    REACTIVE = "reactive"


class LocalizationModule(Module):
    """Choose a pose source, publish it with a confidence, and announce every change of tier."""

    def __init__(
        self, name: str, enabled: bool = True, required: bool = False, **kwargs: object
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._tier: LocalizationTier | None = None
        self._slam_beat: object | None = None
        self._slam_seen_at: float | None = None
        self._place_stamp: object | None = None
        self._place_seen_at: float | None = None
        self._user_stamp: object | None = None
        self._user_seen_at: float | None = None
        self._corrected_at = time.monotonic()
        self._corrected_travelled_cm = 0.0
        self._clock = time.monotonic

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("localization", {}) or {}
        max_age_s = _safe_float(settings.get("slam_max_age_s", 2.0), 2.0)
        min_confidence = _safe_float(settings.get("slam_min_confidence", 0.2), 0.2)
        scale_m = _safe_float(settings.get("dead_reckoning_scale_m", 10.0), 10.0)
        horizon_s = _safe_float(settings.get("dead_reckoning_horizon_s", 120.0), 120.0)
        floor = _safe_float(settings.get("confidence_floor", 0.15), 0.15)
        place_max_age_s = _safe_float(settings.get("place_max_age_s", 30.0), 30.0)

        now = self._clock()
        raw_odometry = context.get("odometry")
        odometry = raw_odometry if isinstance(raw_odometry, dict) else {}

        slam_pose, slam_reason = self._read_slam(context, now, max_age_s, min_confidence)
        place_id, place_confidence, place_reason = self._read_place(
            context, now, place_max_age_s, odometry
        )
        user_anchor = self._read_user(odometry, now)
        if (
            user_anchor is not None
            and self._drift_confidence(now, odometry, scale_m, horizon_s) < floor
        ):
            # The correction expired by the same measure that expires dead reckoning: it stops being
            # a tier rather than becoming a stale claim stated with confidence.
            user_anchor = None
        if user_anchor is not None:
            tier = LocalizationTier.USER
            frame: str | None = "odometry"
            pose: dict | None = {
                "x": _safe_float(odometry.get("x_cm"), 0.0),
                "y": _safe_float(odometry.get("y_cm"), 0.0),
                "yaw_deg": _safe_float(odometry.get("yaw_deg"), 0.0),
            }
            confidence = self._drift_confidence(now, odometry, scale_m, horizon_s)
            reason = f"position confirmed on the map ({user_anchor.get('source') or 'user'})"
        elif slam_pose is not None:
            tier = LocalizationTier.SLAM
            frame = "slam"
            pose = {
                "x": _safe_float(slam_pose.get("x"), 0.0),
                "y": _safe_float(slam_pose.get("y"), 0.0),
                "yaw_deg": _safe_float(slam_pose.get("yaw"), 0.0),
            }
            confidence = max(0.0, min(1.0, _safe_float(slam_pose.get("confidence"), 0.0)))
            reason = None
            # An absolute fix is what expires dead reckoning, so it restarts the drift clock.
            self._corrected_at = now
            self._corrected_travelled_cm = _safe_float(odometry.get("travelled_cm"), 0.0)
        elif place_id is not None:
            # The origin *is* the place: `place_recognition` set `odometry_reset` when it confirmed
            # the match, so the pose odometry publishes is measured from the anchor the view was
            # taught at. The tier says which place, because "you are somewhere" and "you are in the
            # kitchen" are different answers to a client.
            tier = LocalizationTier.PLACE
            frame = "odometry"
            pose = {
                "x": _safe_float(odometry.get("x_cm"), 0.0),
                "y": _safe_float(odometry.get("y_cm"), 0.0),
                "yaw_deg": _safe_float(odometry.get("yaw_deg"), 0.0),
            }
            confidence = place_confidence
            reason = place_id
            self._corrected_at = now
            self._corrected_travelled_cm = _safe_float(odometry.get("travelled_cm"), 0.0)
        elif bool(odometry.get("pose_valid")):
            confidence = self._drift_confidence(now, odometry, scale_m, horizon_s)
            if confidence < floor:
                tier = LocalizationTier.REACTIVE
                frame = None
                pose = None
                reason = (
                    f"dead reckoning expired (confidence {confidence:.2f} < {floor:.2f}); "
                    f"{slam_reason or 'no absolute fix'}"
                )
            else:
                tier = LocalizationTier.DEAD_RECKONING
                frame = "odometry"
                pose = {
                    "x": _safe_float(odometry.get("x_cm"), 0.0),
                    "y": _safe_float(odometry.get("y_cm"), 0.0),
                    "yaw_deg": _safe_float(odometry.get("yaw_deg"), 0.0),
                }
                # Losing a place fix is as much a reason as having no SLAM: a client that saw
                # `place` and now sees `dead_reckoning` needs to know which fix expired.
                parts = [str(place_reason or ""), str(slam_reason or "")]
                reason = "; ".join(part for part in parts if part) or None
        else:
            tier = LocalizationTier.REACTIVE
            frame = None
            pose = None
            confidence = 0.0
            # Both halves are worth keeping: "no heading" and "no SLAM backend" are different
            # faults, and a client debugging a pose it did not get needs to see both.
            parts = [
                str(odometry.get("reason") or ""),
                str(slam_reason or ""),
                str(place_reason or ""),
            ]
            reason = "; ".join(part for part in parts if part) or "no pose source"

        self._publish(context, tier, frame, pose, confidence, reason, now)

    def _read_place(
        self, context, now: float, max_age_s: float, odometry: dict
    ) -> tuple[str | None, float, str | None]:
        """The place a confirmed view match anchored, while the fix is fresh and a pose exists.

        Freshness is an identity comparison — did `frame_ts` change — not a clock subtraction: the
        fix carries a monotonic stamp and an epoch `ts`, and mixing those two is how a fresh fix
        reads ancient. `docs/CONTROL_API.md` makes the same point about `ts`.
        """
        fix = context.get("place_fix")
        if not isinstance(fix, dict):
            # No fix at all is not a fault worth naming on every tick; a fix that *was* rejected is.
            return None, 0.0, None
        stamp = fix.get("frame_ts")
        if stamp != self._place_stamp:
            self._place_stamp = stamp
            self._place_seen_at = now
        seen_at = self._place_seen_at if self._place_seen_at is not None else now
        age_s = max(0.0, now - seen_at)
        if age_s > max_age_s:
            return None, 0.0, f"place fix stale ({age_s:.0f}s > {max_age_s:.0f}s)"
        place_id = str(fix.get("place_id") or "")
        if not place_id:
            return None, 0.0, "place fix names no place"
        if not bool(odometry.get("pose_valid")):
            return None, 0.0, "place fix with no odometry pose behind it"
        return (
            place_id,
            max(0.0, min(1.0, _safe_float(fix.get("confidence"), 0.0))),
            None,
        )


    def _read_user(self, odometry: dict, now: float) -> dict | None:
        """The point a human confirmed on the map, while it is fresh and has a pose behind it (M5).

        Freshness is an identity comparison on `frame_ts`, the rule `_read_place` already uses and for
        the same reason: the anchor carries a wall-clock stamp while this loop runs on a monotonic
        one, so subtracting the two would make a fresh correction read as ancient.

        A new correction restarts the drift clock here, once. Restarting it on every tick that reads
        the anchor would hold the confidence at 1.0 forever, which is how a correction turns into a
        claim the dog never has to give up.
        """
        anchor = odometry.get("anchor")
        if not isinstance(anchor, dict):
            return None
        if not bool(odometry.get("pose_valid")):
            # A correction with no heading behind it is a position without a pose, and this module
            # does not report one - the same refusal a place fix with no odometry behind it gets.
            return None
        stamp = anchor.get("frame_ts")
        if stamp != self._user_stamp:
            self._user_stamp = stamp
            self._user_seen_at = now
            self._corrected_at = now
            self._corrected_travelled_cm = _safe_float(odometry.get("travelled_cm"), 0.0)
        seen_at = self._user_seen_at if self._user_seen_at is not None else now
        if max(0.0, now - seen_at) > USER_FIX_MAX_AGE_S:
            return None
        return anchor

    def _read_slam(
        self, context, now: float, max_age_s: float, min_confidence: float
    ) -> tuple[dict | None, str | None]:
        """The SLAM pose when it is genuinely SLAM and demonstrably alive, else the reason not."""
        status = context.get("slam_status")
        backend = str((status or {}).get("backend") or "") if isinstance(status, dict) else ""
        if backend in NON_SLAM_BACKENDS:
            return None, f"no SLAM backend ({backend or 'none'})"

        # Freshness comes from the slam module's heartbeat *changing*, not from comparing its
        # timestamp with ours: those are different clock domains, and a bounded difference is the
        # only comparison that survives that.
        beat = context.get("module_heartbeat:slam_pi4")
        if beat is None:
            return None, "slam heartbeat missing"
        if beat != self._slam_beat:
            self._slam_beat = beat
            self._slam_seen_at = now
        seen_at = self._slam_seen_at if self._slam_seen_at is not None else now
        age_s = max(0.0, now - seen_at)
        if age_s > max_age_s:
            return None, f"slam pose stale ({age_s:.1f}s > {max_age_s:.1f}s)"

        pose = context.get("slam_pose")
        if not isinstance(pose, dict):
            return None, "slam published no pose"
        confidence = _safe_float(pose.get("confidence"), 0.0)
        if confidence < min_confidence:
            return None, f"slam confidence {confidence:.2f} < {min_confidence:.2f}"
        return pose, None

    def _drift_confidence(
        self, now: float, odometry: dict, scale_m: float, horizon_s: float
    ) -> float:
        """Dead reckoning decays with the distance walked and the age since the last absolute fix."""
        if scale_m <= 0.0 or horizon_s <= 0.0:
            return 0.0
        travelled_m = max(
            0.0, (_safe_float(odometry.get("travelled_cm"), 0.0) - self._corrected_travelled_cm)
        ) / 100.0
        age_s = max(0.0, now - self._corrected_at)
        return max(0.0, min(1.0, 1.0 - travelled_m / scale_m - age_s / horizon_s))

    def _publish(
        self, context, tier, frame, pose, confidence, reason, now: float
    ) -> None:
        context.set(
            "localization",
            {
                "ts": time.time(),
                "tier": str(tier),
                "frame": frame,
                "pose": pose,
                "confidence": round(confidence, 3),
                "age_s": round(max(0.0, now - self._corrected_at), 3),
                "reason": reason,
            },
        )
        if tier == self._tier:
            return
        previous = str(self._tier) if self._tier is not None else None
        self._tier = tier
        # One record per change, not per tick: the event is the interesting part, the key is state.
        context.set(
            "localization_event",
            {"ts": time.time(), "from": previous, "to": str(tier), "reason": reason},
        )
        logger.info("Localization tier %s -> %s (%s)", previous, tier, reason)
