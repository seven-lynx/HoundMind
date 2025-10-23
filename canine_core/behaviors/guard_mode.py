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

from canine_core.core.interfaces import Behavior, BehaviorContext, Event


class GuardBehavior(Behavior):
    name = "guard_mode"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

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
        DETECT_MM = getattr(ctx.config, "GUARD_DETECT_MM", 100.0)
        interval = 0.5
        while self._running:
            dist = self._read_distance()
            ctx.logger.info(f"Guard scan: {dist:.0f} mm")
            if dist < DETECT_MM:
                await self._alert()
            await asyncio.sleep(interval)


BEHAVIOR_CLASS = GuardBehavior
