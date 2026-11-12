from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class RegisteredBehavior:
    name: str
    handler: Callable[[], str]


class BehaviorRegistry:
    def __init__(self) -> None:
        self._items: dict[str, RegisteredBehavior] = {}
        self._sequence: list[str] = []
        self._sequence_idx = 0

    # Items are registered as `<mode>_behavior` (`behavior/fsm.py`, where the six are bound to the
    # library's pickers), while `settings.behavior.autonomy_modes` names the *mode*. The two
    # vocabularies meet here and nowhere else: asking `pick_weighted` for `["patrol"]` finds no item
    # and silently returns None, which is how every autonomy mode but `idle` became unreachable (#82).
    MODE_SUFFIX = "_behavior"

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
        for name, weight in zip(eligible, weight_list, strict=False):
            acc += weight
            if roll <= acc:
                return name
        return eligible[-1]

    def pick_mode(self, modes: list[str], weights: dict[str, float]) -> str | None:
        """Pick one of `modes` — bare mode names — by weight, returning the mode or None.

        The bridge `autonomy_modes` needs: weights are keyed by mode (that is how the config and the
        personality multipliers write them), items are keyed by `<mode>_behavior`, and a mode with no
        registered item is dropped rather than guessed at.
        """
        items = [f"{mode}{self.MODE_SUFFIX}" for mode in modes]
        item_weights = {
            f"{mode}{self.MODE_SUFFIX}": float(weights.get(mode, 1.0)) for mode in modes
        }
        choice = self.pick_weighted(items, item_weights)
        if choice is None or not choice.endswith(self.MODE_SUFFIX):
            return choice
        return choice[: -len(self.MODE_SUFFIX)]

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
