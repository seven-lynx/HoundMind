"""The replay tool: a reader that refuses what it cannot trust, and a session that publishes only
what the record contains.

`--check` and `main()` are exercised through a file, never through a socket: a test must not bind a
port on a CI runner, and the server path is the control plane's own, already covered by
`tests/test_api_stream.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from houndmind_ai.kernel.decisions import DecisionRecord, Refusal
from houndmind_ai.services.state import build_state
from tools.replay_decisions import (
    MAX_DELTA_S,
    ReplaySession,
    load_records,
    main,
    schedule,
    sensors_from_record,
)


def record(ts: float, **overrides: object) -> DecisionRecord:
    fields: dict[str, object] = {
        "ts": ts,
        "mode": "patrol",
        "state": "alert",
        "intent": "forward",
        "source": "navigation",
    }
    fields.update(overrides)
    return DecisionRecord(**fields)  # type: ignore[arg-type]


def line(item: DecisionRecord) -> str:
    """One JSONL line, exactly as `logging/decision_log.py` writes it."""
    return json.dumps({"type": "decision", **item.to_dict()})


def write_log(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_record_survives_the_round_trip() -> None:
    """`to_dict` and `from_dict` are two directions of one shape, so a round trip is identity."""
    original = record(
        1.5,
        vetoes=(Refusal(action="sit", source="behaviour", reason="precedence", detail="ranked"),),
        inputs={"distance_cm": 42.5, "distance_valid": True},
        trace_id="trace123",
    )

    copy = DecisionRecord.from_dict(original.to_dict())

    assert copy == original
    assert copy.vetoes[0].reason == "precedence"
    assert copy.inputs["distance_cm"] == 42.5
    assert copy.confidence is None, "unmeasured stays None through the wire"


def test_an_unknown_schema_version_is_refused_by_name() -> None:
    payload = record(1.0).to_dict()
    payload["schema_version"] = 99

    with pytest.raises(ValueError, match="99"):
        DecisionRecord.from_dict(payload)


def test_a_veto_without_a_reason_is_refused() -> None:
    """Dropping the entry would show a client a refusal with no reason, which is the point of P1."""
    payload = record(1.0).to_dict()
    payload["vetoes"] = [{"action": "sit", "source": "behaviour"}]

    with pytest.raises(ValueError, match="reason"):
        DecisionRecord.from_dict(payload)


@pytest.mark.parametrize("field", ["ts", "mode"])
def test_a_record_without_its_required_fields_is_refused(field: str) -> None:
    payload = record(1.0).to_dict()
    payload.pop(field)

    with pytest.raises(ValueError, match=field):
        DecisionRecord.from_dict(payload)


def test_a_truncated_last_line_is_counted_not_fatal(tmp_path) -> None:
    """A power cut leaves exactly one partial line, and losing the rest over it would be worse."""
    path = write_log(
        tmp_path / "decisions.jsonl",
        [line(record(0.0)), line(record(0.5)), '{"type": "decision", "ts": 0.9'],
    )

    records, skipped = load_records(path)

    assert [item.ts for item in records] == [0.0, 0.5]
    assert skipped == 1


def test_a_bad_line_in_the_middle_is_fatal(tmp_path) -> None:
    path = write_log(
        tmp_path / "decisions.jsonl", [line(record(0.0)), "not json", line(record(1.0))]
    )

    with pytest.raises(ValueError, match=":2:"):
        load_records(path)


def test_an_event_log_is_not_a_decision_log(tmp_path) -> None:
    """`logs/houndmind_events.jsonl` is `type: snapshot`; pointing the tool at it must say so."""
    path = write_log(tmp_path / "events.jsonl", [json.dumps({"type": "snapshot", "timestamp": 1.0})])

    with pytest.raises(ValueError, match="houndmind_decisions.jsonl"):
        load_records(path)


def test_sensors_come_from_the_record_and_nothing_else() -> None:
    reading = sensors_from_record(
        record(2.0, inputs={"distance_cm": 42.5, "distance_valid": True})
    )

    assert reading.distance_cm == 42.5
    assert reading.distance_valid is True
    assert reading.timestamp == 2.0
    # Not recorded is not valid: the log carries no touch or sound reading.
    assert reading.touch_valid is False
    assert reading.sound_valid is False


def test_an_invalid_distance_keeps_its_flag() -> None:
    reading = sensors_from_record(
        record(2.0, inputs={"distance_cm": 100.0, "distance_valid": False})
    )

    assert reading.distance_cm == 100.0
    assert reading.distance_valid is False, "100 cm with a false flag is not 'clear'"


def test_the_schedule_uses_deltas_and_clamps_a_stall() -> None:
    records = [record(0.0), record(0.1), record(0.1), record(500.0)]

    assert schedule(records, 1.0) == pytest.approx([0.0, 0.1, 0.0, MAX_DELTA_S])
    assert schedule(records, 2.0) == pytest.approx([0.0, 0.05, 0.0, MAX_DELTA_S / 2])
    assert schedule(records, 0.0) == [0.0, 0.0, 0.0, 0.0], "speed 0 means 'as fast as possible'"


def test_a_stepped_session_is_what_the_control_plane_would_serve() -> None:
    """The seam the S4 integration test taught us to check: record in, snapshot out."""
    session = ReplaySession()
    session.step(record(1.0, inputs={"distance_cm": 42.5, "distance_valid": True}))
    session.step(
        record(
            1.1,
            intent="sit",
            source="behaviour",
            inputs={"distance_cm": 40.0, "distance_valid": True},
        )
    )

    state = build_state(session.context, now=0.0)

    assert state["decision"]["ts"] == 1.1
    assert state["decision"]["intent"] == "sit"
    assert state["mode"] == "patrol"
    assert state["sensors"]["distance_cm"] == 40.0
    assert state["sensors"]["touch_valid"] is False
    assert state["actuators"]["last_command"] == "sit"
    assert state["actuators"]["source"] == "behaviour"
    assert len(session.ring) == 2


def test_a_silent_tick_does_not_leave_the_previous_command_standing() -> None:
    session = ReplaySession()
    session.step(record(1.0, intent="forward", source="navigation"))
    session.step(record(1.1, intent=None, source=None))

    assert build_state(session.context, now=0.0)["actuators"]["last_command"] is None


def test_check_validates_a_file_and_serves_nothing(tmp_path, capsys) -> None:
    path = write_log(
        tmp_path / "decisions.jsonl",
        [
            line(record(0.0)),
            line(
                record(
                    0.5,
                    intent=None,
                    source=None,
                    vetoes=(Refusal(action="sit", source="behaviour", reason="mode"),),
                )
            ),
        ],
    )

    assert main([str(path), "--check"]) == 0

    out = capsys.readouterr().out
    assert "records: 2" in out
    assert "silent ticks (no intent): 1" in out
    assert "forward (navigation)" in out
    assert "mode" in out


def test_a_missing_file_is_exit_code_two(tmp_path, capsys) -> None:
    assert main([str(tmp_path / "missing.jsonl"), "--check"]) == 2
    assert "missing.jsonl" in capsys.readouterr().out


def test_a_log_with_no_records_is_exit_code_two(tmp_path, capsys) -> None:
    path = write_log(tmp_path / "decisions.jsonl", [])

    assert main([str(path), "--check"]) == 2
    assert "no decision records" in capsys.readouterr().out

