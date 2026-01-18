from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Callable


@dataclass
class RegisteredBehavior:
    name: str
    handler: Callable[[], str]


class BehaviorRegistry:
    def __init__(self) -> None:
        self._items: dict[str, RegisteredBehavior] = {}
        self._sequence: list[str] = []
        self._sequence_idx = 0

    def register(self, name: str, handler: Callable[[], str]) -> None:
        self._items[name] = RegisteredBehavior(name=name, handler=handler)
        if name not in self._sequence:
            self._sequence.append(name)

    def has(self, name: str) -> bool:
        return name in self._items

    def pick_weighted(
        self, choices: list[str], weights: dict[str, float]
    ) -> str | None:
        eligible = [c for c in choices if c in self._items]
        if not eligible:
            return None
        weight_list = [max(0.0, float(weights.get(name, 1.0))) for name in eligible]
        total = sum(weight_list)
        if total <= 0:
            return random.choice(eligible)
        roll = random.random() * total
        acc = 0.0
        for name, weight in zip(eligible, weight_list):
            acc += weight
            if roll <= acc:
                return name
        return eligible[-1]

    def pick_sequential(self, choices: list[str]) -> str | None:
        eligible = [c for c in choices if c in self._items]
        if not eligible:
            return None
        if self._sequence_idx >= len(eligible):
            self._sequence_idx = 0
        name = eligible[self._sequence_idx]
        self._sequence_idx += 1
        return name

    def run(self, name: str) -> str | None:
        entry = self._items.get(name)
        if entry is None:
            return None
        return entry.handler()
