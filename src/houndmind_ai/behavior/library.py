from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterable
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

    def pick_idle_action(
        self,
        *,
        extra: Iterable[str] = (),
        bias: dict[str, float] | None = None,
    ) -> str:
        """Pick an idle action from the whole `idle` bucket, plus whatever the caller adds.

        #37: this used to return `idle_actions[0]` on nineteen calls out of twenty, which made a
        fourteen-entry bucket a constant. The "does an idle action happen at all" decision belongs to
        the tick, not to the picker — it lives in `behavior/fsm.py::_select_idle_behavior`, next to
        the clock that can pace it.

        `extra` and `bias` are the energy band's inputs (P3 L5): the FSM decides that a tired dog may
        also show a `rest` action while idle, and how much that action should outrank the bucket. They
        arrive as arguments because this file knows nothing about energy, thresholds or which catalog
        bucket an action came from — it only weighs what it is given.
        """
        return self._pick(self.config.idle_actions, "stand", extra=extra, bias=bias)

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

    def _pick(
        self,
        actions: list[str],
        default: str,
        extra: Iterable[str] = (),
        bias: dict[str, float] | None = None,
    ) -> str:
        """Draw from `actions` (+ `extra`), weighted by recency and then by `bias`.

        Three cases, in order:

        1. nothing in the bucket → `default`, the same action the FSM falls back to when the library
           is absent (`behavior/fsm.py:161-167`), so an empty bucket degrades instead of raising;
        2. some candidate is outside its cooldown → weighted draw over those, each used action's
           weight rising from the floor to full over one window past its release;
        3. every candidate is inside its cooldown → the least recently used one, because a bucket
           smaller than the cooldown must answer rather than hang (the one-action pool in P3 L4's
           exit criteria is this case with no escape).

        `extra` joins the candidates after the bucket, deduped, so a caller can widen the pool without
        being able to replace it. `bias` multiplies the recency weight — a missing key is 1.0, so an
        unweighted draw is exactly L4's — and it cannot resurrect an action recency excluded, because
        multiplying zero leaves zero.
        """
        candidates = [str(a) for a in actions if isinstance(a, str) and a.strip()]
        if extra:
            seen = set(candidates)
            for name in extra:
                if not isinstance(name, str) or not name.strip() or name in seen:
                    continue
                candidates.append(name)
                seen.add(name)
        if not candidates:
            return default

        bias = bias or {}
        now = self._clock()
        cooldown = max(0.0, float(self.config.reuse_cooldown_s))
        weights: dict[str, float] = {}
        for name in candidates:
            last = self._last_used.get(name)
            if last is None or cooldown <= 0.0:
                weight = 1.0
            else:
                elapsed = max(0.0, now - last)
                if elapsed < cooldown:
                    weight = 0.0
                else:
                    slowly = min(1.0, (elapsed - cooldown) / max(cooldown, _MIN_SPAN))
                    weight = _WEIGHT_FLOOR + (1.0 - _WEIGHT_FLOOR) * slowly
            if weight > 0.0:
                weight *= self._bias_factor(bias, name)
            weights[name] = weight

        if not any(weight > 0.0 for weight in weights.values()):
            oldest = min(candidates, key=lambda name: self._last_used.get(name, float("-inf")))
            self._last_used[oldest] = now
            return oldest

        pick = self._weighted(weights)
        self._last_used[pick] = now
        return pick

    @staticmethod
    def _bias_factor(bias: dict[str, float], name: str) -> float:
        """The caller's multiplier for `name`: 1.0 when absent or unusable, never negative."""
        try:
            return max(0.0, float(bias.get(name, 1.0)))
        except (TypeError, ValueError):
            return 1.0

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

