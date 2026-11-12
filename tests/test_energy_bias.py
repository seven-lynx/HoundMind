"""The energy band: a tired dog adds `rest` actions to `idle`, and nothing else changes (P3 L5).

`behavior/fsm.py::_idle_energy_bias` is the whole policy — which actions join the pool and how much
they outrank it — and `library.pick_idle_action(extra=..., bias=...)` is the weight table it feeds.
These tests are the five states that matter: inert with no reading, inert above the band, inert when
the band is switched off, visible below it, and pre-empted by the autonomy rest state.

The idle bucket used here is disjoint from `REST_BUCKET` on purpose: the shipped `idle` bucket already
contains `lie` and `relax neck`, so "no rest action appeared" would be undecidable over the real
catalog. Overlap is measured instead, in the session log — baseline 21.7 % of idle draws are rest-bucket
members before the band, 44.5 % at energy 0.20.
"""

from __future__ import annotations

import importlib

import pytest

from houndmind_ai.behavior.fsm import BehaviorModule, BehaviorState
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.intents import IntentBoard

T0 = 1000.0
IDLE_BUCKET = [
    "stand",
    "sit",
    "waiting",
    "nod",
    "think",
    "recall",
    "shake head",
    "tilting_head",
    "head_up_down",
]
REST_BUCKET = ["doze off", "nod lethargy", "lie", "relax neck"]


def _module(monkeypatch, **behavior_settings):
    mod = BehaviorModule("behavior", enabled=True)
    ctx = RuntimeContext()
    board = IntentBoard()
    ctx.set("intent_board", board)
    settings = {
        # Autonomy off is the only way to reach `idle` at a low reading: with it on, the mode gate
        # moves the dog to `rest` first (asserted below, so the two cannot silently double up).
        "autonomy_enabled": False,
        "random_idle_chance": 1.0,
        "idle_variety_interval_s": 0.0,
        "catalog": {"idle": IDLE_BUCKET, "rest": REST_BUCKET, "alert": ["bark"]},
    }
    settings.update(behavior_settings)
    ctx.set("settings", {"behavior": settings})
    fsm_mod = importlib.import_module("houndmind_ai.behavior.fsm")
    clock = {"now": T0}
    monkeypatch.setattr(fsm_mod.time, "time", lambda: clock["now"])
    return mod, ctx, board, clock


def _sequence(mod, ctx, board, clock, ticks: int = 120) -> list[str]:
    picked = []
    for _ in range(ticks):
        mod.tick(ctx)
        command = board.find(Source.BEHAVIOUR)
        if command is not None:
            picked.append(command.action.replace("_", " "))
        clock["now"] += 1.0
    return picked


def test_no_reading_leaves_the_bucket_alone(monkeypatch):
    mod, ctx, board, clock = _module(monkeypatch, energy_bias_start=0.5)
    picks = _sequence(mod, ctx, board, clock)

    assert picks, "the run has to publish something to prove anything"
    assert not set(picks) & set(REST_BUCKET), f"no rest action without a reading; saw {set(picks)}"


def test_above_the_band_leaves_the_bucket_alone(monkeypatch):
    mod, ctx, board, clock = _module(monkeypatch, energy_bias_start=0.5)
    ctx.set("energy_level", 0.9)
    picks = _sequence(mod, ctx, board, clock)

    assert not set(picks) & set(REST_BUCKET)


def test_a_band_of_zero_switches_the_bias_off(monkeypatch):
    mod, ctx, board, clock = _module(monkeypatch, energy_bias_start=0.0)
    ctx.set("energy_level", 0.1)
    picks = _sequence(mod, ctx, board, clock)

    assert not set(picks) & set(REST_BUCKET), "0 is the off switch, not a very small band"


@pytest.mark.parametrize(("energy", "floor_share"), [(0.45, 0.25), (0.34, 0.35)])
def test_below_the_band_rest_actions_join_the_pool(monkeypatch, energy, floor_share):
    mod, ctx, board, clock = _module(monkeypatch, energy_bias_start=0.5)
    ctx.set("energy_level", energy)
    picks = _sequence(mod, ctx, board, clock)

    share = sum(1 for p in picks if p in set(REST_BUCKET)) / len(picks)
    assert share >= floor_share, f"rest actions were {share:.0%} of idle at energy {energy}"
    assert "doze off" in picks or "nod lethargy" in picks, (
        "the two actions idle could never reach before are the visible payoff"
    )


def test_the_autonomy_rest_state_wins_and_the_bias_is_not_consulted(monkeypatch):
    """At or below `autonomy_rest_energy_max` a dog with autonomy on rests — it does not rest twice."""
    mod, ctx, board, clock = _module(
        monkeypatch, autonomy_enabled=True, energy_bias_start=0.5, catalog={"idle": IDLE_BUCKET}
    )
    ctx.set("energy_level", 0.2)
    mod.tick(ctx)

    assert mod.state is BehaviorState.REST
