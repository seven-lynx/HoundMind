#!/usr/bin/env python3
"""
Find Open Space Behavior

Performs a scan (left/right/forward) and turns toward the most open direction,
then advances forward. Runs cooperatively and respects config thresholds.
"""
from __future__ import annotations
import asyncio
from typing import Optional, List, Tuple

from canine_core.core.interfaces import Behavior, BehaviorContext, Event
from canine_core.core.services.scanning import ScanningService
from canine_core.utils.detection import VoteWindow


class FindOpenSpaceBehavior(Behavior):
    name = "find_open_space"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._scanner: Optional[ScanningService] = None

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        self._running = True
        try:
            ctx.state.set("active_mode", "navigate_open")
        except Exception:
            pass
        ctx.logger.info("FindOpenSpace starting")
        try:
            self._scanner = ScanningService(ctx.hardware, ctx.logger)
        except Exception:
            self._scanner = None
        self._task = asyncio.create_task(self._loop())

    async def on_event(self, event: Event) -> None:
        return

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                pass
        if self._ctx:
            self._ctx.logger.info("FindOpenSpace stopped")

    async def _loop(self) -> None:
        assert self._ctx is not None
        ctx = self._ctx
        cfg = ctx.config
        dog = getattr(ctx.hardware, 'dog', None)
        scan_delay = max(0.2, float(getattr(cfg, "OBSTACLE_SCAN_INTERVAL", 0.5)))

        yaw_max = int(getattr(cfg, "OPEN_SPACE_SCAN_YAW_MAX_DEG", 60))
        step_deg = int(getattr(cfg, "OPEN_SPACE_SCAN_STEP_DEG", 15))
        settle_s = float(getattr(cfg, "OPEN_SPACE_SCAN_SETTLE_S", 0.12))
        between_s = float(getattr(cfg, "OPEN_SPACE_BETWEEN_READS_S", 0.04))
        min_gap_width = int(getattr(cfg, "OPEN_SPACE_MIN_GAP_WIDTH_DEG", 30))
        min_score_mm = float(getattr(cfg, "OPEN_SPACE_MIN_SCORE_MM", 600.0))
        min_score_cm = (min_score_mm / 10.0)
        confirm_window = int(getattr(cfg, "OPEN_SPACE_CONFIRM_WINDOW", 2))
        confirm_threshold = int(getattr(cfg, "OPEN_SPACE_CONFIRM_THRESHOLD", 2))

        turn_speed = int(getattr(cfg, "OPEN_SPACE_TURN_SPEED", getattr(cfg, 'SPEED_TURN_NORMAL', 200)))
        forward_speed = int(getattr(cfg, 'SPEED_NORMAL', 120))
        turn_steps_small = int(getattr(cfg, 'TURN_STEPS_SMALL', 1))
        turn_steps_normal = int(getattr(cfg, 'TURN_STEPS_NORMAL', 2))
        forward_steps = int(getattr(cfg, 'OPEN_SPACE_FORWARD_STEPS', 2))

        def build_angles() -> List[int]:
            a = list(range(-yaw_max, yaw_max + 1, max(1, step_deg)))
            if not a or a[0] != -yaw_max or a[-1] != yaw_max:
                return [-60, -45, -30, -15, 0, 15, 30, 45, 60]
            return a

        def find_best_cluster(angles: List[int], dists: dict[int, float]) -> Tuple[int, float, int, int]:
            """Return (center_angle, score, start_idx, end_idx). Score = width_deg * avg_cm.
            If no cluster matches min requirements, fallback to max distance angle with score=dist.
            """
            best = (0, -1.0, 0, 0)
            i = 0
            n = len(angles)
            while i < n:
                if dists.get(angles[i], 0.0) >= min_score_cm:
                    j = i
                    total = 0.0
                    count = 0
                    while j < n and dists.get(angles[j], 0.0) >= min_score_cm:
                        total += dists.get(angles[j], 0.0)
                        count += 1
                        j += 1
                    width_deg = count * step_deg
                    if width_deg >= min_gap_width and count > 0:
                        avg = total / count
                        center_idx = i + (count // 2)
                        center_angle = angles[center_idx]
                        score = width_deg * avg
                        if score > best[1]:
                            best = (center_angle, score, i, j - 1)
                    i = j
                else:
                    i += 1
            if best[1] < 0:
                # fallback: choose single best angle
                best_angle = max(angles, key=lambda a: dists.get(a, -1.0))
                return (best_angle, dists.get(best_angle, 0.0), angles.index(best_angle), angles.index(best_angle))
            return best

        votes = VoteWindow(size=max(1, confirm_window), threshold=max(1, confirm_threshold))

        while self._running:
            angles = build_angles()
            dmap = {}
            if self._scanner is not None:
                try:
                    dmap = await self._scanner.scan_sequence(angles, settle_s, between_s, int(getattr(cfg, "HEAD_SCAN_SPEED", 70)), center_end=True)
                except Exception:
                    dmap = {}
            if not dmap:
                # minimal fallback: do nothing this cycle
                await asyncio.sleep(scan_delay)
                continue

            center_angle, score, s_idx, e_idx = find_best_cluster(angles, dmap)
            # optional confirmation
            votes.add(True)
            confirmed = votes.passed()
            if confirm_window > 1:
                # quick second pass to confirm selection consistency
                try:
                    dmap2 = await self._scanner.scan_sequence(angles, settle_s, between_s, int(getattr(cfg, "HEAD_SCAN_SPEED", 70)), center_end=True)
                    center2, score2, *_ = find_best_cluster(angles, dmap2)
                    votes.add(center2 == center_angle)
                    confirmed = votes.passed()
                except Exception:
                    pass

            ctx.logger.info(f"OpenSpace best center={center_angle}° score={score:.0f} confirmed={confirmed}")

            if dog is None:
                ctx.logger.info(f"[Sim] open-space turn {center_angle}° then forward {forward_steps} steps")
                await asyncio.sleep(scan_delay)
                continue

            try:
                if abs(center_angle) > 0:
                    # Prefer precise IMU-based turning toward the chosen angle; fallback handled by MotionService
                    tol = float(getattr(cfg, "ORIENTATION_TURN_TOLERANCE_DEG", 5.0))
                    tout = float(getattr(cfg, "ORIENTATION_MAX_TURN_TIME_S", 3.0))
                    ctx.motion.turn_by_angle(float(center_angle), turn_speed, ctx, tolerance_deg=tol, timeout_s=tout)
                dog.do_action('forward', step_count=forward_steps, speed=forward_speed)
                dog.wait_all_done()
            except Exception as e:
                ctx.logger.warning(f"OpenSpace move failed: {e}")
            await asyncio.sleep(scan_delay)


BEHAVIOR_CLASS = FindOpenSpaceBehavior
