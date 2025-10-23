#!/usr/bin/env python3
"""
Find Open Space Behavior

Performs a scan (left/right/forward) and turns toward the most open direction,
then advances forward. Runs cooperatively and respects config thresholds.
"""
from __future__ import annotations
import asyncio
from typing import Optional

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
        try:
            ctx.state.set("active_mode", "navigate_open")
        except Exception:
            pass
        ctx.logger.info("FindOpenSpace starting")
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
        sensors = ctx.sensors
        motion = getattr(ctx, 'motion', None) or None
        dog = getattr(ctx.hardware, 'dog', None)
        scan_delay = max(0.2, float(getattr(cfg, "OBSTACLE_SCAN_INTERVAL", 0.5)))
        while self._running:
            head_range = getattr(cfg, "HEAD_SCAN_RANGE", 45)
            head_speed = getattr(cfg, "HEAD_SCAN_SPEED", 70)
            fwd, left, right = sensors.read_distances(head_range, head_speed)
            ctx.logger.info(f"OpenSpace scan mm fwd={fwd:.0f} left={left:.0f} right={right:.0f}")
            # choose the most open direction, break ties towards forward
            best = max((('forward', fwd), ('left', left), ('right', right)), key=lambda x: x[1])
            action = best[0]
            SPEED_TURN = getattr(cfg, 'SPEED_TURN_NORMAL', 200)
            SPEED_FWD = getattr(cfg, 'SPEED_NORMAL', 120)
            steps_turn = getattr(cfg, 'TURN_STEPS_NORMAL', 2)
            walk_steps = getattr(cfg, 'WALK_STEPS_NORMAL', 2)
            if dog is None:
                ctx.logger.info(f"[Sim] open-space action: {action}")
                await asyncio.sleep(scan_delay)
                continue
            try:
                if action == 'left':
                    dog.do_action('turn_left', step_count=steps_turn, speed=SPEED_TURN)
                elif action == 'right':
                    dog.do_action('turn_right', step_count=steps_turn, speed=SPEED_TURN)
                else:
                    dog.do_action('forward', step_count=walk_steps, speed=SPEED_FWD)
                dog.wait_all_done()
            except Exception as e:
                ctx.logger.warning(f"OpenSpace move failed: {e}")
            await asyncio.sleep(scan_delay)


BEHAVIOR_CLASS = FindOpenSpaceBehavior
