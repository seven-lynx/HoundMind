"""The decision record: one row per tick, with a reason on every losing intent.

The interesting cases are the ones that make a record trustworthy: a missing confidence stays
missing, a refusal keeps the reason that produced it, and a tick where nothing happened is still
a record. Each test names the rule it pins.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from houndmind_ai.kernel.decisions import (
    DEFAULT_MAX_ENTRIES,
    SCHEMA_VERSION,
    DecisionRecord,
    DecisionRing,
    Refusal,
    confidence_or_none,
)


def record(ts: float, **kwargs) -> DecisionRecord:
    return DecisionRecord(ts=ts, mode="patrol", **kwargs)


# ------------------------------------------------------------------ confidence


def test_a_missing_confidence_stays_missing() -> None:
    """`None`, never `0.0`: an unmeasured confidence is not a confident zero."""
    for missing in (None, "", "high", True, False, float("nan")):
        assert confidence_or_none(missing) is None


def test_a_measured_confidence_survives() -> None:
    assert confidence_or_none(0.82) == pytest.approx(0.82)
    # A measured zero is a fact, so it is kept — unlike a missing reading.
    assert confidence_or_none(0) == 0.0
    assert confidence_or_none(0.0) == 0.0


def test_an_out_of_range_confidence_is_not_quietly_rescaled() -> None:
    """Clamping would hide a producer bug while inventing certainty."""
    assert confidence_or_none(1.7) == pytest.approx(1.7)


# -------------------------------------------------------------------- refusals


def test_a_refusal_keeps_its_reason() -> None:
    refusal = Refusal(
        action="forward",
        source="navigation",
        reason="obstacle",
        detail="8.0 cm at sensor (limit 12.0 cm)",
    )
    assert refusal.to_dict() == {
        "action": "forward",
        "source": "navigation",
        "reason": "obstacle",
        "detail": "8.0 cm at sensor (limit 12.0 cm)",
    }


def test_a_precedence_refusal_needs_no_detail() -> None:
    """The gateway's own two words (`mode`, `precedence`) carry no interlock detail."""
    refusal = Refusal(action="sit", source="behaviour", reason="precedence")
    assert refusal.to_dict()["detail"] is None


# ---------------------------------------------------------------------- wire


def test_the_wire_shape_is_the_documented_one() -> None:
    payload = record(
        12.5,
        state="patrolling",
        intent="forward",
        source="navigation",
        vetoes=(Refusal("sit", "behaviour", "precedence"),),
        inputs={"distance_cm": 42.0, "distance_valid": True, "battery_v": 7.6},
        confidence=None,
        trace_id="trace-1",
    ).to_dict()

    assert payload["schema_version"] == SCHEMA_VERSION
    assert set(payload) == {
        "schema_version",
        "ts",
        "trace_id",
        "mode",
        "state",
        "intent",
        "source",
        "vetoes",
        "inputs",
        "confidence",
    }
    assert payload["vetoes"] == [
        {"action": "sit", "source": "behaviour", "reason": "precedence", "detail": None}
    ]
    assert payload["confidence"] is None


def test_a_tick_where_nothing_happened_is_still_a_record() -> None:
    """An unexplained pet is indistinguishable from a broken one, so silence is recorded."""
    payload = record(3.0).to_dict()
    assert payload["intent"] is None
    assert payload["source"] is None
    assert payload["vetoes"] == []
    assert payload["mode"] == "patrol"


def test_the_record_copies_its_inputs() -> None:
    """A producer that reuses its readings dict must not rewrite history."""
    readings: dict[str, object] = {"distance_cm": 42.0}
    rec = record(1.0, inputs=readings)
    readings["distance_cm"] = 8.0
    assert rec.to_dict()["inputs"] == {"distance_cm": 42.0}


def test_a_record_is_history_and_cannot_be_edited() -> None:
    with pytest.raises(FrozenInstanceError):
        record(1.0).intent = "forward"  # type: ignore[misc]


# ----------------------------------------------------------------------- ring


def test_the_ring_keeps_the_last_n_records_oldest_first() -> None:
    ring = DecisionRing(max_entries=3)
    for ts in range(5):
        ring.append(record(float(ts)))

    assert len(ring) == 3
    assert [rec.ts for rec in ring.recent()] == [2.0, 3.0, 4.0]


def test_an_empty_ring_has_no_latest_record() -> None:
    """`None` is the honest answer before the first tick; a zero record would be a lie."""
    ring = DecisionRing()
    assert ring.latest() is None
    assert ring.recent() == []
    assert len(ring) == 0


def test_latest_is_the_newest_record() -> None:
    ring = DecisionRing(max_entries=10)
    ring.append(record(1.0))
    ring.append(record(2.0))
    assert ring.latest() is not None
    assert ring.latest().ts == 2.0  # type: ignore[union-attr]


def test_recent_clamps_the_limit_instead_of_raising() -> None:
    """`?limit=` is client input, so every value has to have an answer."""
    ring = DecisionRing(max_entries=10)
    for ts in range(5):
        ring.append(record(float(ts)))

    assert [rec.ts for rec in ring.recent(2)] == [3.0, 4.0]
    assert ring.recent(99) == ring.recent()
    assert ring.recent(0) == []
    assert ring.recent(-5) == []
    assert ring.recent("junk") == []  # type: ignore[arg-type]


def test_the_ring_size_cannot_collapse_to_zero() -> None:
    """A zero-length ring would discard every record and never say so."""
    for value in (0, -5):
        ring = DecisionRing(max_entries=value)
        ring.append(record(1.0))
        assert ring.max_entries == 1
        assert len(ring) == 1


def test_a_junk_ring_size_falls_back_to_the_default() -> None:
    """Missing and unreadable are the same thing here, and neither means "keep nothing"."""
    for value in ("junk", None):
        ring = DecisionRing(max_entries=value)  # type: ignore[arg-type]
        assert ring.max_entries == DEFAULT_MAX_ENTRIES


def test_the_default_ring_holds_the_documented_window() -> None:
    """§4.2: about twenty seconds at the 10 Hz loop."""
    assert DEFAULT_MAX_ENTRIES == 200
    assert DecisionRing().max_entries == DEFAULT_MAX_ENTRIES

