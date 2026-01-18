"""
Simple in-process pub/sub event bus for CanineCore.
"""

from __future__ import annotations
import asyncio
from typing import Callable, Dict, List
from .interfaces import Event


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable[[Event], None]]] = {}
        self._queue: asyncio.Queue[Event] = asyncio.Queue()

    def subscribe(self, event_type: str, handler: Callable[[Event], None]) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def publish(self, event: Event) -> None:
        self._queue.put_nowait(event)

    async def run(self) -> None:
        while True:
            event = await self._queue.get()
            for handler in self._subscribers.get(event.type, []):
                try:
                    handler(event)
                except Exception as e:
                    # best-effort; real logging will be in LoggingService
                    print(f"[EventBus] handler error: {e}")
