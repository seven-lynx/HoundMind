#!/usr/bin/env python3
"""
Find Open Space Behavior (Converted)

Scans left/right/forward distances and turns toward the most open direction,
then advances. Cooperative and sim-safe. Uses CanineConfig values if present.
"""
from __future__ import annotations
import asyncio
from typing import Optional, Tuple

from canine_core.core.interfaces import Behavior, BehaviorContext, Event


class FindOpenSpaceBehavior(Behavior):
    name = "find_open_space"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        self._running = True
        ctx.logger.info("FindOpenSpace starting")
        # Optional LED cue
        rgb = getattr(ctx.hardware, "rgb", None)
        enable_emotions = getattr(ctx.config, "ENABLE_EMOTIONAL_SYSTEM", getattr(ctx.config, "enable_emotional_system", False))
        if rgb is not None and enable_emotions:
            try:
                rgb.set_color((0, 128, 255))  # blue-ish for exploration
                getattr(rgb, "breathe", lambda x: None)(1)
            except Exception:
                pass
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

    def _scan(self) -> Tuple[float, float, float]:
        assert self._ctx is not None
        dog = getattr(self._ctx.hardware, "dog", None)
        if dog is None:
            return (1000.0, 1000.0, 1000.0)
        try:
            head_range = getattr(self._ctx.config, "HEAD_SCAN_RANGE", 45)
            head_speed = getattr(self._ctx.config, "HEAD_SCAN_SPEED", 70)
            # left
            dog.head_move([[-head_range, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            left = float(dog.read_distance() or 1000.0)
            # right
            dog.head_move([[head_range, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            right = float(dog.read_distance() or 1000.0)
            # forward
            dog.head_move([[0, 0, 0]], speed=head_speed)
            dog.wait_head_done()
            fwd = float(dog.read_distance() or 1000.0)
            return (fwd, left, right)
        except Exception:
            return (1000.0, 1000.0, 1000.0)

    async def _loop(self) -> None:
        assert self._ctx is not None
        ctx = self._ctx
        dog = getattr(ctx.hardware, "dog", None)
        cfg = ctx.config
        scan_delay = max(0.2, float(getattr(cfg, "OBSTACLE_SCAN_INTERVAL", 0.5)))
        TURN_STEPS_LARGE = getattr(cfg, "TURN_STEPS_LARGE", 4)
        TURN_STEPS_NORMAL = getattr(cfg, "TURN_STEPS_NORMAL", 2)
        SPEED_TURN_NORMAL = getattr(cfg, "SPEED_TURN_NORMAL", 200)
        SPEED_NORMAL = getattr(cfg, "SPEED_NORMAL", 120)
        WALK_STEPS_LONG = getattr(cfg, "WALK_STEPS_LONG", 3)
        while self._running:
            fwd, left, right = self._scan()
            # Choose most open direction
            choices = {"forward": fwd, "left": left, "right": right}
            best = max(choices.items(), key=lambda kv: kv[1])[0]
            ctx.logger.info(f"OpenSpace scan mm fwd={fwd:.0f} left={left:.0f} right={right:.0f} -> {best}")
            if dog is None:
                ctx.logger.info(f"[Sim] open-space action: {best}")
                await asyncio.sleep(scan_delay)
                continue
            try:
                if best == "forward":
                    dog.do_action("forward", step_count=WALK_STEPS_LONG, speed=SPEED_NORMAL)
                elif best == "left":
                    dog.do_action("turn_left", step_count=TURN_STEPS_LARGE, speed=SPEED_TURN_NORMAL)
                else:
                    dog.do_action("turn_right", step_count=TURN_STEPS_LARGE, speed=SPEED_TURN_NORMAL)
                dog.wait_all_done()
            except Exception as e:
                ctx.logger.warning(f"Move failed: {e}")
            await asyncio.sleep(scan_delay)


BEHAVIOR_CLASS = FindOpenSpaceBehavior
