#!/usr/bin/env python3
"""
EventHooksDemoBehavior: demonstrates reacting to bus events via default hooks.

This behavior does not do much actively; it relies on other services to
publish events (battery_low/critical, safety_emergency_tilt). It logs start/stop
and idles for a short time to allow events to be received.
"""
from __future__ import annotations
import asyncio
from typing import Optional

from canine_core.core.interfaces import Behavior, BehaviorContext, Event


class EventHooksDemoBehavior(Behavior):
    name = "event_hooks_demo"

    def __init__(self) -> None:
        self._ctx: Optional[BehaviorContext] = None
        self._running = False

    async def start(self, ctx: BehaviorContext) -> None:
        self._ctx = ctx
        self._running = True
        ctx.logger.info("EventHooksDemo starting — waiting to observe events...")
        # Subscriptions happen in default hooks; we just idle here

    async def on_event(self, event: Event) -> None:
        # Intentionally minimal — hooks act outside behaviors
        return

    async def stop(self) -> None:
        if not self._ctx:
            return
        self._running = False
        self._ctx.logger.info("EventHooksDemo stopped")


BEHAVIOR_CLASS = EventHooksDemoBehavior
