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
    SUPPORTED_SCHEMA_VERSIONS,
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
        driver="navigation",
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
        "driver",
        "autonomy_mode",
        "autonomy_weight",
        "status",
        "vetoes",
        "inputs",
        "confidence",
    }
    assert payload["driver"] == "navigation"
    assert payload["vetoes"] == [
        {"action": "sit", "source": "behaviour", "reason": "precedence", "detail": None}
    ]
    assert payload["confidence"] is None


def test_the_reader_still_reads_a_v1_line() -> None:
    """A replay tool that refuses its own older logs is a regression, so v1 stays readable."""
    v1_line = {
        "schema_version": 1,
        "ts": 900.0,
        "trace_id": "trace-old",
        "mode": "patrol",
        "state": "idle",
        "intent": "stand",
        "source": "behaviour",
        "vetoes": [],
        "inputs": {"distance_cm": None},
        "confidence": None,
    }

    read = DecisionRecord.from_dict(v1_line)

    assert read.driver is None
    # Reading upgrades on the way out: one shape is written, even when two are read.
    assert read.to_dict()["schema_version"] == SCHEMA_VERSION


def test_the_reader_still_reads_a_v2_line() -> None:
    """v2 added `driver`; a v3 build must not claim that line recorded a status."""
    v2_line = {
        "schema_version": 2,
        "ts": 901.0,
        "trace_id": "trace-v2",
        "mode": "patrol",
        "state": "alert",
        "intent": "forward",
        "source": "navigation",
        "driver": "navigation",
        "vetoes": [],
        "inputs": {},
        "confidence": 0.5,
    }

    read = DecisionRecord.from_dict(v2_line)

    assert read.driver == "navigation"
    assert read.status is None
    assert read.autonomy_mode is None
    assert read.autonomy_weight is None
    assert read.to_dict()["schema_version"] == SCHEMA_VERSION


def test_the_status_and_the_autonomy_pair_round_trip() -> None:
    payload = record(
        5.0,
        status="undecided",
        driver="behaviour",
        autonomy_mode="patrol",
        autonomy_weight=2.5,
    ).to_dict()

    read = DecisionRecord.from_dict(payload)

    assert read.status == "undecided"
    assert read.autonomy_mode == "patrol"
    assert read.autonomy_weight == 2.5


def test_a_status_this_build_does_not_know_is_refused_by_name() -> None:
    payload = record(6.0, status="accepted").to_dict()
    payload["status"] = "maybe"

    with pytest.raises(ValueError, match="unknown decision status"):
        DecisionRecord.from_dict(payload)


def test_an_absent_weight_stays_absent() -> None:
    """A weight the FSM never computed is `None`, never `0.0` and never a string."""
    for missing in (None, "", "heavy", True, float("nan")):
        line = record(7.0, status="accepted").to_dict()
        line["autonomy_weight"] = missing
        assert DecisionRecord.from_dict(line).autonomy_weight is None


def test_the_reader_refuses_a_shape_it_does_not_know() -> None:
    payload = record(1.0).to_dict()
    payload["schema_version"] = max(SUPPORTED_SCHEMA_VERSIONS) + 1

    with pytest.raises(ValueError, match="unsupported decision schema_version"):
        DecisionRecord.from_dict(payload)


def test_a_record_with_no_autonomy_input_names_no_driver() -> None:
    assert record(1.0).to_dict()["driver"] is None


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

