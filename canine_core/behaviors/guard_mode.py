#!/usr/bin/env python3
"""
CanineCore Guard Mode (Converted)

Watches the forward distance periodically; when motion/close object is detected,
performs a brief alert sequence (bark + look around). LED indicates alert status
when emotions are enabled. Runs cooperatively and stops cleanly.
"""
from __future__ import annotations
import asyncio
from typing import Optional
from collections import deque

from canine_core.core.interfaces import Behavior, BehaviorContext, Event
from canine_core.core.services.scanning import ScanningService


class GuardBehavior(Behavior):
    name = "guard_mode"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # Scanning/baseline state
        self._baseline_mm: dict[int, float] = {}
        self._scan_dir: int = 1  # +1 forward sweep, -1 backward sweep
        self._last_alert_time_s: float = 0.0
        self._approach_votes: dict[int, deque[bool]] = {}
        self._scanner: Optional[ScanningService] = None

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        self._running = True
        try:
            # Use reacting as an allowed mode
            ctx.state.set("active_mode", "reacting")
        except Exception:
            pass
        # Ready posture and calm LED
        dog = getattr(ctx.hardware, "dog", None)
        rgb = getattr(ctx.hardware, "rgb", None)
        try:
            if dog is not None:
                dog.do_action("stand", speed=getattr(ctx.config, "SPEED_SLOW", 80))
                dog.wait_all_done()
        except Exception:
            pass
        try:
            if rgb is not None and getattr(ctx.config, "ENABLE_EMOTIONAL_SYSTEM", getattr(ctx.config, "enable_emotional_system", False)):
                rgb.set_color((255, 255, 255))
        except Exception:
            pass
        ctx.logger.info("GuardBehavior starting")
        # init scanner service
        try:
            self._scanner = ScanningService(ctx.hardware, ctx.logger)
        except Exception:
            self._scanner = None
        self._task = asyncio.create_task(self._loop())

    async def on_event(self, event: Event) -> None:
        # Could react to an external stop/quiet event later
        return

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                pass
        if self._ctx:
            rgb = getattr(self._ctx.hardware, "rgb", None)
            dog = getattr(self._ctx.hardware, "dog", None)
            try:
                if rgb is not None:
                    rgb.set_color((255, 255, 255))
            except Exception:
                pass
            try:
                if dog is not None:
                    dog.do_action("stand", speed=getattr(self._ctx.config, "SPEED_SLOW", 80))
                    dog.wait_all_done()
            except Exception:
                pass
            self._ctx.logger.info("GuardBehavior stopped")

    # --- internals ---
    def _read_distance(self) -> float:
        assert self._ctx is not None
        dog = getattr(self._ctx.hardware, "dog", None)
        if dog is None:
            return 1000.0
        try:
            d = dog.read_distance()
            return float(d if d is not None else 1000.0)
        except Exception:
            return 1000.0

    async def _move_head_and_read(self, yaw_deg: int, settle_s: float, move_speed: int) -> float:
        """Delegate to ScanningService with safe fallback."""
        assert self._ctx is not None
        if self._scanner is not None:
            try:
                return await self._scanner.move_and_read(yaw_deg, settle_s, move_speed)
            except Exception:
                pass
        # fallback
        await asyncio.sleep(max(0.0, settle_s * 0.5))
        return self._read_distance()

    async def _alert(self) -> None:
        assert self._ctx is not None
        ctx = self._ctx
        dog = getattr(ctx.hardware, "dog", None)
        rgb = getattr(ctx.hardware, "rgb", None)
        SPEED_SLOW = getattr(ctx.config, "SPEED_SLOW", 80)
        SPEED_TURN = getattr(ctx.config, "SPEED_TURN_NORMAL", 200)
        try:
            if rgb is not None and getattr(ctx.config, "ENABLE_EMOTIONAL_SYSTEM", getattr(ctx.config, "enable_emotional_system", False)):
                rgb.set_color((255, 0, 0))
                if hasattr(rgb, "flash"):
                    rgb.flash(1)
        except Exception:
            pass
        if dog is not None:
            try:
                dog.do_action("bark", speed=SPEED_SLOW)
                await asyncio.sleep(0.2)
                dog.do_action("turn_left", step_count=2, speed=SPEED_TURN)
                dog.wait_all_done()
                dog.do_action("turn_right", step_count=4, speed=SPEED_TURN)
                dog.wait_all_done()
                dog.do_action("turn_left", step_count=2, speed=SPEED_TURN)
                dog.wait_all_done()
            except Exception:
                pass

    async def _loop(self) -> None:
        assert self._ctx is not None
        ctx = self._ctx
        # Configurable guard parameters with conservative defaults
        yaw_max = int(getattr(ctx.config, "GUARD_SCAN_YAW_MAX_DEG", 90))
        step_deg = int(getattr(ctx.config, "GUARD_SCAN_STEP_DEG", 15))
        settle_s = float(getattr(ctx.config, "GUARD_SCAN_SETTLE_S", 0.15))
        ema_alpha = float(getattr(ctx.config, "GUARD_BASELINE_EMA", 0.2))
        delta_mm = float(getattr(ctx.config, "GUARD_DEVIATION_MM", 120.0))
        delta_pct = float(getattr(ctx.config, "GUARD_DEVIATION_PCT", 0.25))
        cooldown_s = float(getattr(ctx.config, "GUARD_ALERT_COOLDOWN_S", 3.0))
        between_reads_s = float(getattr(ctx.config, "GUARD_BETWEEN_READS_S", 0.05))
        head_speed = int(getattr(ctx.config, "SPEED_TURN_NORMAL", 200))
        confirm_window = int(getattr(ctx.config, "GUARD_CONFIRM_WINDOW", 3))
        confirm_threshold = int(getattr(ctx.config, "GUARD_CONFIRM_THRESHOLD", 2))

        # Build scan angles and ping-pong sweep
        angles = list(range(-yaw_max, yaw_max + 1, max(1, step_deg)))
        if not angles or angles[0] != -yaw_max or angles[-1] != yaw_max:
            angles = [-90, -75, -60, -45, -30, -15, 0, 15, 30, 45, 60, 75, 90]

        # Center head before starting (best effort)
        try:
            await self._move_head_and_read(0, 0.1, head_speed)
        except Exception:
            pass

        loop = asyncio.get_running_loop()
        while self._running:
            seq = angles if self._scan_dir > 0 else list(reversed(angles))
            for yaw in seq:
                if not self._running:
                    break
                dist = await self._move_head_and_read(yaw, settle_s, head_speed)
                base = self._baseline_mm.get(yaw)
                if base is None:
                    # Initialize baseline from first pass
                    self._baseline_mm[yaw] = dist
                else:
                    # EMA update
                    new_base = (1.0 - ema_alpha) * base + ema_alpha * dist
                    self._baseline_mm[yaw] = new_base

                    # Approach detection (distance decreased vs. baseline)
                    # Units: dog.read_distance() returns centimeters
                    # Convert mm threshold to centimeters for comparison
                    delta = base - dist  # cm; positive means closer than baseline
                    pct = (delta / base) if base > 1e-6 else 0.0
                    approaching = (delta >= (delta_mm / 10.0)) or (pct >= delta_pct)
                    # Record vote for this angle
                    votes = self._approach_votes.get(yaw)
                    if votes is None or votes.maxlen != max(1, confirm_window):
                        votes = deque(maxlen=max(1, confirm_window))
                        self._approach_votes[yaw] = votes
                    votes.append(bool(approaching))
                    # Check N-of-M confirmation
                    if sum(1 for v in votes if v) >= max(1, confirm_threshold):
                        now = loop.time()
                        if (now - self._last_alert_time_s) > cooldown_s:
                            ctx.logger.info(
                                f"Guard: approaching object @ {yaw}° (Δ={delta:.0f}cm, {pct*100:.0f}%, base={base:.0f}cm, now={dist:.0f}cm)"
                            )
                            await self._alert()
                            self._last_alert_time_s = now
                await asyncio.sleep(between_reads_s)
            # Reverse sweep direction for smoother motion
            self._scan_dir *= -1


BEHAVIOR_CLASS = GuardBehavior
