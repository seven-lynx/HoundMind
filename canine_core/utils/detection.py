"""
Lightweight detection utilities for smoothing, confirmation, and cooldown logic.

These helpers are self-contained and safe to import anywhere in CanineCore.
"""
from __future__ import annotations
import time
from collections import deque
from typing import Deque


class Ema:
    """Simple exponential moving average.

    ema = (1 - alpha) * ema + alpha * value
    """

    def __init__(self, alpha: float, initial: float | None = None) -> None:
        self.alpha = max(0.0, min(1.0, float(alpha)))
        self.value = float(initial) if initial is not None else None

    def update(self, x: float) -> float:
        x = float(x)
        if self.value is None:
            self.value = x
        else:
            a = self.alpha
            self.value = (1.0 - a) * self.value + a * x
        return self.value


class VoteWindow:
    """Fixed-size window of boolean votes with N-of-M pass check."""

    def __init__(self, size: int, threshold: int | None = None) -> None:
        self.size = max(1, int(size))
        self.threshold = max(1, int(threshold)) if threshold is not None else max(1, int(size // 2 + 1))
        self._buf: Deque[bool] = deque(maxlen=self.size)

    def add(self, v: bool) -> None:
        self._buf.append(bool(v))

    def passed(self, threshold: int | None = None) -> bool:
        th = max(1, int(threshold)) if threshold is not None else self.threshold
        return sum(1 for b in self._buf if b) >= th

    def clear(self) -> None:
        self._buf.clear()


class Cooldown:
    """Simple wall-clock cooldown timer."""

    def __init__(self, seconds: float) -> None:
        self.seconds = max(0.0, float(seconds))
        self._last: float = 0.0

    def ready(self) -> bool:
        now = time.monotonic()
        return (now - self._last) >= self.seconds

    def touch(self) -> None:
        self._last = time.monotonic()
