from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
import asyncio


@dataclass
class VoiceConfig:
    wake_word: str = "pidog"
    enabled: bool = True


class VoiceService:
    """Lightweight voice input facade.

    Real audio I/O is optional; this provides a cooperative async generator
    of commands. In non-audio environments, it can be extended to poll a
    queue or simulate commands.
    """

    def __init__(self, wake_word: str = "pidog", enabled: bool = True) -> None:
        self.wake_word = wake_word.lower()
        self.enabled = enabled
        self._running = False
        self._provider: Optional[Callable[[], asyncio.Future]] = None

    def set_provider(self, provider: Callable[[], asyncio.Future]) -> None:
        """Inject an async provider that resolves to a raw transcript string."""
        self._provider = provider

    async def listen_commands(self):
        """Async generator yielding parsed commands.

        A command is a simple string like 'sit', 'stand', 'turn left', 'walk'.
        """
        self._running = True
        while self._running:
            if not self.enabled:
                await asyncio.sleep(0.5)
                continue
            text = None
            try:
                if self._provider:
                    text = await self._provider()
            except Exception:
                text = None
            if not text:
                await asyncio.sleep(0.3)
                continue
            t = text.strip().lower()
            # Require wake word prefix if present
            if self.wake_word and not t.startswith(self.wake_word):
                # allow commands without wake word for simpler modes
                cmd = t
            else:
                cmd = t[len(self.wake_word):].lstrip(" ,:")
            yield cmd

    def stop(self) -> None:
        self._running = False
