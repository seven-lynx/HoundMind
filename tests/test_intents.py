"""The intent board: latest value per source, expiring unless refreshed.

The property that matters is not "it stores a value". It is that a producer which stops
asking stops being heard, because that is what the four legacy context keys could not do.
"""

from __future__ import annotations

import threading

from houndmind_ai.kernel.commands import Source, canonical_action, mode_allows
from houndmind_ai.kernel.intents import INTERNAL_HOLD_MS, IntentBoard


class Clock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_publishing_stamps_the_command() -> None:
    board = IntentBoard(clock=Clock())
    command = board.publish("turn left", Source.NAVIGATION)
    assert command.action == "turn_left"
    assert command.source is Source.NAVIGATION
    assert command.issued_at == 100.0


def test_a_published_intent_is_visible() -> None:
    board = IntentBoard(clock=Clock())
    board.publish("forward", Source.NAVIGATION)
    assert [command.action for command in board.latest()] == ["forward"]
    assert board.find(Source.NAVIGATION).action == "forward"


def test_an_unrefreshed_intent_expires() -> None:
    clock = Clock()
    board = IntentBoard(clock=clock)
    board.publish("forward", Source.NAVIGATION)
    clock.advance(INTERNAL_HOLD_MS / 1000.0 + 0.01)
    assert board.latest() == []
    assert board.expired == 1


def test_refreshing_keeps_an_intent_alive() -> None:
    clock = Clock()
    board = IntentBoard(clock=clock)
    for _ in range(10):
        board.publish("forward", Source.NAVIGATION)
        clock.advance(0.2)
    assert board.find(Source.NAVIGATION) is not None
    assert board.expired == 0


def test_the_hold_belongs_to_the_board_not_the_producer() -> None:
    """A producer cannot make its intent permanent by asking for a long TTL."""
    clock = Clock()
    board = IntentBoard(hold_ms=500, clock=clock)
    command = board.publish("forward", Source.NAVIGATION)
    assert command.ttl_ms == 500
    clock.advance(0.51)
    assert board.find(Source.NAVIGATION) is None


def test_retracting_is_immediate() -> None:
    board = IntentBoard(clock=Clock())
    board.publish("forward", Source.NAVIGATION)
    board.retract(Source.NAVIGATION)
    assert board.latest() == []
    assert len(board) == 0


def test_one_source_does_not_overwrite_another() -> None:
    board = IntentBoard(clock=Clock())
    board.publish("forward", Source.NAVIGATION)
    board.publish("sit", Source.BEHAVIOUR)
    assert board.find(Source.NAVIGATION).action == "forward"
    assert board.find(Source.BEHAVIOUR).action == "sit"


def test_latest_is_ordered_by_precedence() -> None:
    board = IntentBoard(clock=Clock())
    for source in (Source.BEHAVIOUR, Source.SYSTEM, Source.NAVIGATION):
        board.publish("stand", source)
    assert [command.source for command in board.latest()] == [
        Source.SYSTEM,
        Source.NAVIGATION,
        Source.BEHAVIOUR,
    ]


def test_replacing_an_intent_keeps_one_entry_per_source() -> None:
    board = IntentBoard(clock=Clock())
    board.publish("forward", Source.NAVIGATION)
    board.publish("backward", Source.NAVIGATION)
    assert len(board) == 1
    assert board.find(Source.NAVIGATION).action == "backward"


def test_the_snapshot_names_every_live_source() -> None:
    board = IntentBoard(clock=Clock())
    board.publish("forward", Source.NAVIGATION)
    board.publish("sit", Source.BEHAVIOUR)
    assert board.snapshot() == {"navigation": "forward", "behaviour": "sit"}


def test_concurrent_publishing_and_reading_is_safe() -> None:
    """The loop publishes while the event logger reads. Neither may see a half-written slot."""
    board = IntentBoard(clock=Clock())
    stop = threading.Event()
    errors: list[BaseException] = []

    def producer() -> None:
        try:
            for _ in range(500):
                board.publish("forward", Source.NAVIGATION)
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            errors.append(exc)

    def reader() -> None:
        try:
            while not stop.is_set():
                board.latest()
                board.snapshot()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    publisher = threading.Thread(target=producer)
    publisher.start()
    publisher.join()
    stop.set()
    reader_thread.join(timeout=5.0)
    assert errors == []


# ------------------------------------------------------------------ the mode policy


def test_idle_and_patrol_allow_every_source() -> None:
    for mode in ("idle", "patrol"):
        for source in Source:
            assert mode_allows(mode, source), (mode, source)


def test_rest_allows_only_the_sources_that_can_end_a_motion() -> None:
    assert mode_allows("rest", Source.SYSTEM)
    assert mode_allows("rest", Source.WATCHDOG)
    assert not mode_allows("rest", Source.CLIENT)
    assert not mode_allows("rest", Source.NAVIGATION)
    assert not mode_allows("rest", Source.BEHAVIOUR)
    assert not mode_allows("rest", Source.ROUTINE)


def test_manual_keeps_autonomy_out_and_the_client_in() -> None:
    assert mode_allows("manual", Source.CLIENT)
    assert not mode_allows("manual", Source.NAVIGATION)
    assert not mode_allows("manual", Source.BEHAVIOUR)
    assert not mode_allows("manual", Source.ROUTINE)


def test_an_unknown_mode_falls_back_to_the_default() -> None:
    """A corrupt mode must not lock the dog out of its own recovery paths."""
    assert mode_allows("nonsense", Source.NAVIGATION)
    assert mode_allows("nonsense", Source.CLIENT)


def test_both_spellings_name_the_same_action() -> None:
    assert canonical_action("turn right") == canonical_action("turn_right")