#!/usr/bin/env python3
"""
CanineCore Idle Behavior (Converted)

This is a first-class Behavior implementation for the idle behavior.
It cooperatively runs in the CanineCore orchestrator, using the provided
BehaviorContext services where available, and gracefully degrades when
hardware isn't present (e.g., on a dev machine).
"""
from __future__ import annotations
import asyncio
import random
from typing import Optional

from canine_core.core.interfaces import Behavior, BehaviorContext, Event


class IdleBehavior(Behavior):
    name = "idle_behavior"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        self._running = True
        # Try to set mode to idle (validated)
        try:
            ctx.state.set("active_mode", "idle")
        except Exception:
            pass
        # Light neutral if hardware present
        if getattr(ctx.hardware, "rgb", None):
            try:
                ctx.hardware.rgb.set_color((255, 255, 255))
            except Exception:
                pass
        ctx.logger.info("IdleBehavior starting")
        self._task = asyncio.create_task(self._loop())

    async def on_event(self, event: Event) -> None:
        # For now, ignore events in idle; future: react to sound/user events
        return

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except asyncio.TimeoutError:
                pass
        if self._ctx and getattr(self._ctx.hardware, "dog", None):
            try:
                # Return to a safe standing state
                self._ctx.hardware.dog.do_action("stand", speed=80)
                self._ctx.hardware.dog.wait_all_done()
            except Exception:
                pass
        if self._ctx and getattr(self._ctx.hardware, "rgb", None):
            try:
                self._ctx.hardware.rgb.set_color((255, 255, 255))
            except Exception:
                pass
        if self._ctx:
            self._ctx.logger.info("IdleBehavior stopped")

    async def _loop(self) -> None:
        assert self._ctx is not None
        ctx = self._ctx
        dog = getattr(ctx.hardware, "dog", None)
        rgb = getattr(ctx.hardware, "rgb", None)
        actions = [
            ("wag_tail", 1.0),
            ("sit", 1.0),
            ("tilting_head", 1.0),
            ("bark", 0.6),
            ("stand", 1.0),
        ]
        while self._running:
            # pick action by simple weighted choice
            name = random.choices([a for a, _ in actions], weights=[w for _, w in actions])[0]
            if dog is None:
                ctx.logger.info(f"[Sim] idle action: {name}")
                await asyncio.sleep(random.uniform(1.0, 2.5))
            else:
                try:
                    if rgb:
                        rgb.set_color((255, 255, 255))
                    # map to PiDog actions
                    if name == "tilting_head":
                        dog.head_move([[random.randint(-20, 20), 0, 0]], speed=80)
                        dog.wait_head_done()
                    else:
                        dog.do_action(name, speed=100)
                        dog.wait_all_done()
                except Exception as e:
                    ctx.logger.warning(f"Idle action '{name}' failed: {e}")
                await asyncio.sleep(random.uniform(1.0, 2.5))


# Expose class for orchestrator auto-detection
BEHAVIOR_CLASS = IdleBehavior
