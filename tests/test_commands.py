"""Typed commands: precedence, identity, and the deadman."""

from __future__ import annotations

import dataclasses

import pytest

from houndmind_ai.kernel.commands import (
    DEFAULT_TTL_MS,
    FORWARD_ACTIONS,
    KNOWN_ACTIONS,
    MOTION_ACTIONS,
    Command,
    Source,
    Verdict,
)


def test_source_precedence_is_declared_not_discovered() -> None:
    assert (
        Source.SYSTEM
        > Source.WATCHDOG
        > Source.CLIENT
        > Source.NAVIGATION
        > Source.BEHAVIOUR
    )


def test_ids_are_unique_per_command() -> None:
    ids = {Command("forward").id for _ in range(50)}
    assert len(ids) == 50


def test_two_identical_actions_are_distinguishable() -> None:
    """The legacy bug: 'forward' from two sources compared equal, so the second was dropped."""
    a = Command("forward", source=Source.NAVIGATION)
    b = Command("forward", source=Source.CLIENT)
    assert a.action == b.action
    assert a.id != b.id
    assert a.source != b.source


def test_deadman_uses_ttl() -> None:
    command = Command("forward", issued_at=100.0, ttl_ms=300)
    assert command.deadline() == pytest.approx(100.3)
    assert command.expired(100.29) is False
    assert command.expired(100.31) is True


def test_zero_ttl_expires_immediately() -> None:
    command = Command("forward", issued_at=5.0, ttl_ms=0)
    assert command.expired(5.0001) is True


def test_default_ttl_is_the_short_deadman() -> None:
    assert Command("forward").ttl_ms == DEFAULT_TTL_MS == 300


def test_command_is_immutable() -> None:
    command = Command("forward")
    with pytest.raises(dataclasses.FrozenInstanceError):
        command.action = "backward"  # type: ignore[misc]


def test_commands_do_not_share_a_params_dict() -> None:
    a = Command("forward")
    b = Command("forward")
    assert a.params is not b.params


def test_catalog_sets_are_consistent() -> None:
    assert MOTION_ACTIONS <= KNOWN_ACTIONS
    assert FORWARD_ACTIONS <= MOTION_ACTIONS
    # `trot` carries the dog forward, so the sonar gate covers it like `forward`.
    assert "trot" in FORWARD_ACTIONS
    assert "trot" in MOTION_ACTIONS
    assert "stop" in KNOWN_ACTIONS
    # stop is deliberately not a motion action: it must never be vetoed.
    assert "stop" not in MOTION_ACTIONS


def test_to_dict_is_json_shaped() -> None:
    payload = Command("forward", params={"speed": 100}, issued_at=1.0).to_dict()
    assert payload["action"] == "forward"
    assert payload["source"] == "client"
    assert payload["params"] == {"speed": 100}


def test_verdict_serialises_refusal_with_reason() -> None:
    refused = Verdict(accepted=False, action="forward", veto="obstacle", detail="5.0 cm")
    payload = refused.to_dict()
    assert payload["accepted"] is False
    assert payload["veto"] == "obstacle"
    assert payload["detail"] == "5.0 cm"


def test_verdict_acceptance_hides_veto_fields() -> None:
    payload = Verdict(accepted=True, action="forward").to_dict()
    assert "veto" not in payload
    assert "retry_after_ms" not in payload