"""The library's draw: the whole bucket, weighted by recency (P3 L4, #37).

`pick_idle_action` returned `idle_actions[0]` on nineteen calls out of twenty, so a fourteen-entry
bucket behaved as a constant. Every picker is now one weighted draw with a reuse cooldown, and the
clock is injected so these tests step time instead of sleeping.
"""

from __future__ import annotations

import random

from houndmind_ai.behavior.library import BehaviorLibrary, BehaviorLibraryConfig

IDLE = [f"action_{n:02d}" for n in range(14)]


def _library(**overrides) -> tuple[BehaviorLibrary, dict[str, float]]:
    settings = {
        "idle_actions": IDLE,
        "alert_actions": ["bark"],
        "avoid_actions": ["backward"],
        "play_actions": ["stretch"],
        "rest_actions": ["lie"],
        "patrol_actions": ["forward"],
        "explore_actions": ["forward"],
        "interact_actions": ["wag tail"],
    }
    settings.update(overrides)
    clock = {"now": 1000.0}
    library = BehaviorLibrary(BehaviorLibraryConfig(**settings), clock=lambda: clock["now"])
    return library, clock


def test_idle_draws_from_the_whole_bucket() -> None:
    """The defect was a 95% first-entry share; the fix is that every entry is reachable and none wins."""
    random.seed(11)
    library, clock = _library()
    picks = [library.pick_idle_action() for _ in range(2000)]

    assert set(picks) == set(IDLE), "every entry in the bucket is reachable"
    assert picks.count(IDLE[0]) < len(picks) * 0.15, "no single entry dominates"


def test_a_used_action_is_excluded_inside_its_cooldown() -> None:
    random.seed(3)
    library, clock = _library(reuse_cooldown_s=20.0, idle_actions=["sit", "lie", "nod"])

    first = library.pick_idle_action()
    clock["now"] += 1.0
    second = library.pick_idle_action()
    clock["now"] += 1.0
    third = library.pick_idle_action()

    assert first != second and first != third, "nothing may repeat inside the cooldown"


def test_an_action_returns_after_its_cooldown() -> None:
    random.seed(5)
    library, clock = _library(reuse_cooldown_s=10.0, idle_actions=["sit", "lie"])
    clock["now"] = 1000.0
    first = library.pick_idle_action()

    clock["now"] = 1030.0  # past the cooldown and past the fade window
    seen = set()
    for _ in range(200):
        seen.add(library.pick_idle_action())
        clock["now"] += 0.001
    assert seen == {"sit", "lie"}, f"the released action comes back; kept {first}"


def test_a_one_action_pool_answers_rather_than_hanging() -> None:
    library, clock = _library(reuse_cooldown_s=60.0, idle_actions=["only"])
    for step in range(5):
        clock["now"] = 1000.0 + step
        assert library.pick_idle_action() == "only"


def test_an_exhausted_pool_returns_the_least_recently_used() -> None:
    random.seed(2)
    library, clock = _library(reuse_cooldown_s=60.0, idle_actions=["sit", "lie"])

    first = library.pick_idle_action()
    clock["now"] += 1.0
    second = library.pick_idle_action()
    clock["now"] += 1.0
    third = library.pick_idle_action()

    assert {first, second} == {"sit", "lie"}, "the first draw takes one, the second the other"
    assert third == first, "with both inside their cooldown the older one wins"


def test_cooldown_zero_is_a_uniform_draw() -> None:
    random.seed(7)
    library, clock = _library(reuse_cooldown_s=0.0, idle_actions=["sit", "lie", "nod"])
    picks = [library.pick_idle_action() for _ in range(200)]

    assert any(a == b for a, b in zip(picks, picks[1:], strict=False)), (
        "with recency off the same action may follow itself"
    )


def test_an_empty_bucket_degrades_to_the_fsm_default() -> None:
    """An empty bucket used to raise `IndexError` inside the tick; it now names the FSM's fallback."""
    library, clock = _library(idle_actions=[], patrol_actions=[])

    assert library.pick_idle_action() == "stand"
    assert library.pick_patrol_action() == "forward"


def test_every_bucket_uses_the_same_weighted_core() -> None:
    random.seed(13)
    library, clock = _library(reuse_cooldown_s=20.0, play_actions=["stretch", "sit", "nod"])
    picks = {library.pick_play_action() for _ in range(50)}
    assert len(picks) == 3, f"the same recency rules apply outside `idle`; saw {picks}"


# ---------------------------------------------------------------- the caller's bias (L5)
# `extra` widens the pool, `bias` reweights it, and both are the caller's business: the library
# multiplies what it is handed and knows nothing about energy.

REST = ["doze off", "nod lethargy", "lie", "relax neck"]


def test_a_bias_shifts_the_draw_towards_the_actions_it_names() -> None:
    random.seed(17)
    library, clock = _library()
    biased = {name: 3.0 for name in ("action_03", "action_07")}
    picks = [library.pick_idle_action(bias=biased) for _ in range(2000)]

    share = sum(1 for p in picks if p in biased) / len(picks)
    assert share > 0.25, f"two of fourteen actions at 3x should be well above 14%; got {share:.2f}"


def test_a_bias_without_extra_is_inert() -> None:
    """A key the bucket does not contain cannot invent an action, however large its weight."""
    random.seed(19)
    library, clock = _library()
    picks = {library.pick_idle_action(bias={"doze off": 1000.0}) for _ in range(300)}

    assert picks == set(IDLE)


def test_extra_adds_actions_the_bucket_never_had() -> None:
    random.seed(23)
    library, clock = _library(idle_actions=["sit", "stand"])
    picks = [library.pick_idle_action(extra=REST) for _ in range(400)]

    assert {"doze off", "nod lethargy"} <= set(picks), "the rest bucket is reachable from idle"
    assert {"sit", "stand"} <= set(picks), "the bucket is widened, not replaced"


def test_a_zero_bias_cannot_resurrect_a_cooled_down_action() -> None:
    random.seed(29)
    library, clock = _library(reuse_cooldown_s=60.0, idle_actions=["sit", "lie"])
    first = library.pick_idle_action()

    clock["now"] += 1.0
    assert library.pick_idle_action(bias={first: 0.0}) != first, (
        "multiplying a recency zero leaves zero, whatever the bias"
    )


def test_no_arguments_reproduces_the_unbiased_draw() -> None:
    """The default path must be byte-identical to L4, not merely similar."""
    random.seed(31)
    plain, plain_clock = _library(reuse_cooldown_s=5.0)
    plain_picks = []
    for _ in range(20):
        plain_picks.append(plain.pick_idle_action())
        plain_clock["now"] += 1.0

    random.seed(31)
    explicit, explicit_clock = _library(reuse_cooldown_s=5.0)
    explicit_picks = []
    for _ in range(20):
        explicit_picks.append(explicit.pick_idle_action(extra=(), bias=None))
        explicit_clock["now"] += 1.0

    assert plain_picks == explicit_picks
