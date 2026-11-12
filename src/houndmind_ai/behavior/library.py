from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# The weight an action carries the moment its reuse cooldown expires: possible, not probable. It
# climbs back to 1.0 over one more window, so a bucket turns over instead of cycling in pairs.
_WEIGHT_FLOOR = 0.05
# One second of slack in the fade arithmetic, so a cooldown of 0 does not divide by zero.
_MIN_SPAN = 1e-9


@dataclass
class BehaviorLibraryConfig:
    """Configuration for behavior sequences and weights."""

    idle_actions: list[str]
    alert_actions: list[str]
    avoid_actions: list[str]
    play_actions: list[str]
    rest_actions: list[str]
    patrol_actions: list[str]
    explore_actions: list[str]
    interact_actions: list[str]
    # Seconds before the same action may be drawn again. 0 disables recency entirely, which is the
    # pre-L4 behaviour (a uniform draw) and the escape hatch if a bucket turns out too small.
    reuse_cooldown_s: float = 0.0


class BehaviorLibrary:
    """Reusable behavior patterns that rely on PiDog ActionFlow actions.

    Every pick is a weighted draw over the whole bucket, with recently used actions excluded inside
    their cooldown and faded back in afterwards (`_pick`). The clock is injectable because recency is
    the one thing here a test cannot fake with a seed: `clock=...` lets a test step time instead of
    sleeping.
    """

    def __init__(
        self, config: BehaviorLibraryConfig, clock: Callable[[], float] | None = None
    ) -> None:
        self.config = config
        self._clock: Callable[[], float] = clock or (lambda: time.time())
        self._last_used: dict[str, float] = {}

    def pick_idle_action(self) -> str:
        """Pick an idle action from the whole `idle` bucket.

        #37: this used to return `idle_actions[0]` on nineteen calls out of twenty, which made a
        fourteen-entry bucket a constant. The "does an idle action happen at all" decision belongs to
        the tick, not to the picker — it lives in `behavior/fsm.py::_select_idle_behavior`, next to
        the clock that can pace it.
        """
        return self._pick(self.config.idle_actions, "stand")

    def pick_alert_action(self) -> str:
        return self._pick(self.config.alert_actions, "bark")

    def pick_avoid_action(self) -> str:
        return self._pick(self.config.avoid_actions, "backward")

    def pick_play_action(self) -> str:
        return self._pick(self.config.play_actions, "stretch")

    def pick_rest_action(self) -> str:
        return self._pick(self.config.rest_actions, "lie")

    def pick_patrol_action(self) -> str:
        return self._pick(self.config.patrol_actions, "forward")

    def pick_explore_action(self) -> str:
        return self._pick(self.config.explore_actions, "forward")

    def pick_interact_action(self) -> str:
        return self._pick(self.config.interact_actions, "wag tail")

    def _pick(self, actions: list[str], default: str) -> str:
        """Draw from `actions`, weighted so the least recently used win.

        Three cases, in order:

        1. nothing in the bucket → `default`, the same action the FSM falls back to when the library
           is absent (`behavior/fsm.py:161-167`), so an empty bucket degrades instead of raising;
        2. some candidate is outside its cooldown → weighted draw over those, each used action's
           weight rising from the floor to full over one window past its release;
        3. every candidate is inside its cooldown → the least recently used one, because a bucket
           smaller than the cooldown must answer rather than hang (the one-action pool in P3 L4's
           exit criteria is this case with no escape).
        """
        candidates = [str(a) for a in actions if isinstance(a, str) and a.strip()]
        if not candidates:
            return default

        now = self._clock()
        cooldown = max(0.0, float(self.config.reuse_cooldown_s))
        weights: dict[str, float] = {}
        for name in candidates:
            last = self._last_used.get(name)
            if last is None or cooldown <= 0.0:
                weights[name] = 1.0
                continue
            elapsed = max(0.0, now - last)
            if elapsed < cooldown:
                weights[name] = 0.0
            else:
                slowly = min(1.0, (elapsed - cooldown) / max(cooldown, _MIN_SPAN))
                weights[name] = _WEIGHT_FLOOR + (1.0 - _WEIGHT_FLOOR) * slowly

        if not any(weight > 0.0 for weight in weights.values()):
            oldest = min(candidates, key=lambda name: self._last_used.get(name, float("-inf")))
            self._last_used[oldest] = now
            return oldest

        pick = self._weighted(weights)
        self._last_used[pick] = now
        return pick

    @staticmethod
    def _weighted(weights: dict[str, float]) -> str:
        """One draw from `weights`, in insertion order, falling back to the last entry."""
        names = [name for name, weight in weights.items() if weight > 0.0]
        total = sum(weights[name] for name in names)
        roll = random.random() * total
        acc = 0.0
        for name in names:
            acc += weights[name]
            if roll <= acc:
                return name
        return names[-1]

