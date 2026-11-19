"""A mode change must not leave an autonomy intent standing, and must not clear the tilt latch (#270).

Both are safety properties the code claimed and did not have. `MODE_ALLOWED_SOURCES` gates a *new*
intent; it says nothing about one already published, so a manual switch left a behaviour or navigation
slot live until it expired - and the interlock's latch is a property of the dog, not of a mode, so
nothing about switching may clear it.
"""

from __future__ import annotations

from houndmind_ai.act.gateway import MotionGatewayModule
from houndmind_ai.act.interlock import Interlock, InterlockLimits
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.kernel.commands import Command, CommandBus, Source
from houndmind_ai.kernel.intents import IntentBoard
from houndmind_ai.services.api import ControlPlane
from houndmind_ai.services.settings import ApiSettings


class Clock:
    """A clock that does not move: nothing here may depend on wall time passing."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t


class DummyContext:
    """The smallest context a plane needs: settings, a clock and the intent board."""

    def __init__(self, board: IntentBoard | None = None) -> None:
        self.data: dict = {"settings": {}, "intent_board": board}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value


def make_plane(board: IntentBoard | None) -> tuple[ControlPlane, DummyContext]:
    context = DummyContext(board)
    plane = ControlPlane(context, ApiSettings(host="127.0.0.1", port=0), CommandBus())
    return plane, context


def make_gateway(clock: Clock) -> tuple[MotionGatewayModule, RuntimeContext]:
    """A gateway wired the way `tests/test_gateway.py` builds one: one clock for the interlock and
    for the board, and `start` publishing the board a producer finds."""
    gateway = MotionGatewayModule(
        "motion_gateway",
        interlock=Interlock(InterlockLimits(), now=clock),
        clock=clock,
        board=IntentBoard(clock=clock),
    )
    context = RuntimeContext()
    gateway.start(context)
    return gateway, context


def test_a_mode_change_retracts_every_autonomy_slot() -> None:
    """The bug: a manual switch keeps driving on intent the old mode published."""
    board = IntentBoard()
    plane, _context = make_plane(board)
    board.publish("forward", Source.BEHAVIOUR)
    board.publish("turn_left", Source.NAVIGATION)
    board.publish("trot", Source.CLIENT)

    plane.set_mode("manual")

    live = {command.source for command in board.latest()}
    assert Source.BEHAVIOUR not in live
    assert Source.NAVIGATION not in live
    # A human's own request is not autonomy: switching the mode moves the wheel, it does not let go.
    assert live == {Source.CLIENT}


def test_the_same_mode_twice_retracts_nothing() -> None:
    """A redundant `set_mode` is not a change, and must not cancel a goal the dog is walking."""
    board = IntentBoard()
    plane, _context = make_plane(board)
    plane.set_mode("patrol")
    board.publish("forward", Source.NAVIGATION)

    plane.set_mode("patrol")

    assert {command.source for command in board.latest()} == {Source.NAVIGATION}


def test_a_plane_without_an_intent_board_still_switches_modes() -> None:
    """The retraction is additive: the control plane worked before there was a board to retract."""
    plane, context = make_plane(None)

    plane.set_mode("rest")

    assert context.get("runtime_mode") == "rest"


def test_the_tilt_latch_survives_a_mode_change() -> None:
    """The latch is a property of the dog. Nothing about a mode switch may clear it."""
    board = IntentBoard()
    plane, _context = make_plane(board)
    clock = Clock()
    dog = FakeDogHAL(now=clock)
    dog.set_distance(100.0)
    dog.set_imu(60.0, 0.0)
    interlock = Interlock(InterlockLimits(), now=clock)

    latched = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert latched.accepted is False
    assert interlock.tilt_latched is True

    plane.set_mode("manual")
    plane.set_mode("patrol")
    plane.set_mode("rest")

    assert interlock.tilt_latched is True
    still_refused = interlock.evaluate(Command("forward", issued_at=clock()), dog.read())
    assert still_refused.accepted is False
    assert still_refused.veto == "tilt"


# --------------------------------------------------------------- the gateway's half of the rule


def test_the_gateway_retracts_autonomy_when_the_mode_changes() -> None:
    """The half `set_mode` cannot cover: a mode written straight onto the context (#270)."""
    clock = Clock()
    gateway, context = make_gateway(clock)
    board = context.get("intent_board")
    gateway.tick(context)  # the first tick seeds the mode
    board.publish("forward", Source.NAVIGATION)

    context.set("runtime_mode", "manual")
    gateway.tick(context)

    assert board.find(Source.NAVIGATION) is None
    assert context.get("motion_command") is None


def test_a_stale_intent_cannot_revive_when_the_mode_returns() -> None:
    """The bug in the flesh: refused under `manual`, executed after the switch to `patrol`."""
    clock = Clock()
    gateway, context = make_gateway(clock)
    board = context.get("intent_board")
    context.set("runtime_mode", "manual")
    gateway.tick(context)
    board.publish("forward", Source.NAVIGATION)
    gateway.tick(context)
    assert board.find(Source.NAVIGATION) is not None  # refused by the gate, not withdrawn

    context.set("runtime_mode", "patrol")
    gateway.tick(context)

    assert board.find(Source.NAVIGATION) is None
    assert context.get("motion_command") is None


def test_the_first_tick_does_not_retract_a_producers_intent() -> None:
    """Seeding is not a change: an intent published before the gateway ran is legitimate."""
    clock = Clock()
    gateway, context = make_gateway(clock)
    board = context.get("intent_board")
    board.publish("forward", Source.NAVIGATION)

    gateway.tick(context)

    assert board.find(Source.NAVIGATION) is not None
    assert context.get("motion_command")["action"] == "forward"


def test_the_record_names_the_withdrawal_rather_than_looking_idle() -> None:
    """A retracted intent must not read as "nobody asked" in the record (#270, B3).

    This is the row C3 of the device run reads back: after `manual` -> `idle` with a live autonomy
    intent, the record has to say that autonomy was withdrawn, and by which mode change.
    """
    clock = Clock()
    gateway, context = make_gateway(clock)
    board = context.get("intent_board")
    context.set("runtime_mode", "manual")
    gateway.tick(context)
    board.publish("forward", Source.NAVIGATION)
    board.publish("wag_tail", Source.BEHAVIOUR)

    context.set("runtime_mode", "idle")
    gateway.tick(context)

    record = context.get("decision_record").to_dict()
    assert record["intent"] is None
    # The highest-ranked autonomy source that lost the tick, so a reader sees what was withdrawn.
    assert record["driver"] == "navigation"
    assert [(refusal["source"], refusal["reason"]) for refusal in record["vetoes"]] == [
        ("navigation", "mode_change"),
        ("behaviour", "mode_change"),
    ]
    assert "manual" in record["vetoes"][0]["detail"]
    assert "idle" in record["vetoes"][0]["detail"]


def test_a_tick_that_withdraws_nothing_names_no_driver() -> None:
    """No autonomy on the board is not the same as autonomy withdrawn."""
    clock = Clock()
    gateway, context = make_gateway(clock)
    gateway.tick(context)

    context.set("runtime_mode", "manual")
    gateway.tick(context)

    record = context.get("decision_record").to_dict()
    assert record["driver"] is None
    assert record["vetoes"] == []
