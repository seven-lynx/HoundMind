"""The bus between the control plane and the gateway.

Two threads, one contract: the control plane submits and waits, the gateway drains and
acknowledges. These tests cover the parts that are easy to get wrong and expensive to debug on
a dog — a full queue that blocks, an ack that arrives before the waiter does, a waiter that
never gets an answer.
"""

from __future__ import annotations

import threading

from houndmind_ai.kernel.commands import Command, CommandBus, Source, Verdict


def _command(action: str = "forward", issued_at: float = 0.0) -> Command:
    return Command(action=action, source=Source.CLIENT, issued_at=issued_at)


def test_a_submitted_command_is_drained_exactly_once() -> None:
    bus = CommandBus()
    command = _command()

    assert bus.submit(command) is True
    assert bus.drain() == [command]
    assert bus.drain() == [], "a command must not be handed out twice"


def test_a_full_queue_refuses_instead_of_blocking() -> None:
    """A refusal the client can read beats a latency spike on the servo bus."""
    bus = CommandBus(maxsize=2)
    assert bus.submit(_command()) is True
    assert bus.submit(_command()) is True

    assert bus.submit(_command()) is False
    assert bus.dropped == 1
    assert bus.pending == 2


def test_an_ack_reaches_a_waiter() -> None:
    bus = CommandBus()
    command = _command()
    verdict = Verdict(accepted=True, action="forward")
    bus.submit(command)

    def ack_later() -> None:
        for pending in bus.drain():
            bus.acknowledge(pending, verdict)

    threading.Thread(target=ack_later).start()

    assert bus.wait(command.id, timeout=1.0) == verdict


def test_an_ack_that_arrives_before_the_wait_is_not_lost() -> None:
    """The gateway can judge a command before the HTTP thread starts waiting for it."""
    bus = CommandBus()
    command = _command()
    verdict = Verdict(accepted=False, action="forward", veto="obstacle", detail="12 cm")
    bus.submit(command)
    for pending in bus.drain():
        bus.acknowledge(pending, verdict)

    assert bus.wait(command.id, timeout=0.01) == verdict


def test_wait_times_out_without_an_ack() -> None:
    """A timeout is not a veto: the route reports it as 503, not as an accepted command."""
    bus = CommandBus()
    bus.submit(_command())

    assert bus.wait("never-acked", timeout=0.01) is None


def test_an_ack_with_no_waiter_does_not_grow_without_bound() -> None:
    bus = CommandBus()
    for _ in range(300):
        command = _command()
        bus.submit(command)
        for pending in bus.drain():
            bus.acknowledge(pending, Verdict(accepted=True, action=command.action))

    assert len(bus._acks) <= CommandBus._ACK_CAP  # noqa: SLF001 - the bound is the contract