"""The FSM's half of L4: idle variety is paced, and the draw gate lives with the tick clock.

`behavior/library.py` cannot pace a dog — it has no tick. `_select_idle_behavior` holds the interval
and `random_idle_chance`, and these tests are that claim: the action holds inside the window, a fresh
draw happens after it, `0` never re-draws, and the action shown in `idle` comes from the idle bucket
rather than from whatever the previous state published.
"""

from __future__ import annotations

import importlib

from houndmind_ai.behavior.fsm import BehaviorModule
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.intents import IntentBoard

T0 = 1000.0
IDLE_BUCKET = ["sit", "lie", "nod"]


def _module(monkeypatch, **behavior_settings):
    mod = BehaviorModule("behavior", enabled=True)
    ctx = RuntimeContext()
    board = IntentBoard()
    ctx.set("intent_board", board)
    settings = {
        "autonomy_modes": ["idle"],
        "catalog": {"idle": IDLE_BUCKET, "alert": ["bark", "shake head"]},
        # Recency: a used action is out of the pool, so a re-draw has to differ — that is what makes
        # "the action changed" a deterministic assertion rather than a 1-in-3 coincidence.
        "action_reuse_cooldown_s": 60.0,
    }
    settings.update(behavior_settings)
    ctx.set("settings", {"behavior": settings})
    fsm_mod = importlib.import_module("houndmind_ai.behavior.fsm")
    clock = {"now": T0}
    monkeypatch.setattr(fsm_mod.time, "time", lambda: clock["now"])
    return mod, ctx, board, clock


def _published(board: IntentBoard) -> str | None:
    command = board.find(Source.BEHAVIOUR)
    return None if command is None else command.action


def test_the_idle_action_holds_inside_the_variety_interval(monkeypatch):
    mod, ctx, board, clock = _module(
        monkeypatch, idle_variety_interval_s=30.0, random_idle_chance=1.0
    )
    mod.tick(ctx)
    first = _published(board)
    assert first in IDLE_BUCKET

    clock["now"] = T0 + 10.0
    mod.tick(ctx)
    assert _published(board) == first, "inside the window idle is held, not re-drawn"

    clock["now"] = T0 + 31.0
    mod.tick(ctx)
    assert _published(board) != first, "past the window a new action is drawn"


def test_a_chance_of_zero_never_re_draws(monkeypatch):
    mod, ctx, board, clock = _module(
        monkeypatch, idle_variety_interval_s=0.0, random_idle_chance=0.0
    )
    mod.tick(ctx)
    first = _published(board)

    for step in range(1, 50):
        clock["now"] = T0 + step
        mod.tick(ctx)
        assert _published(board) == first


def test_idle_shows_an_idle_action_after_another_state(monkeypatch):
    """Entering `idle` must not leave the previous state's action standing for a whole interval."""
    mod, ctx, board, clock = _module(
        monkeypatch, idle_variety_interval_s=30.0, random_idle_chance=1.0
    )
    ctx.set("perception", {"touch": "P"})
    mod.tick(ctx)
    assert _published(board) in {"bark", "shake_head"}

    clock["now"] = T0 + 1.0
    ctx.set("perception", {})
    mod.tick(ctx)
    assert _published(board) in IDLE_BUCKET
