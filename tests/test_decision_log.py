"""The decision feed has to survive the event log and outlive a frozen clock.

Two ways this module could look correct and still be wrong, both covered below: inheriting
`event_log_enabled` (then `/decisions` dies on a device that turned the event log off), and
deduplicating on `ts` (then two ticks that share a timestamp collapse into one row).
"""

from __future__ import annotations

import json
from pathlib import Path

from houndmind_ai.act.gateway import MotionGatewayModule
from houndmind_ai.act.interlock import Interlock
from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.kernel.decisions import DecisionRecord
from houndmind_ai.kernel.intents import IntentBoard
from houndmind_ai.logging.decision_log import DecisionLogModule


def _record(ts: float = 1.0, intent: str | None = "walk") -> DecisionRecord:
    return DecisionRecord(ts=ts, mode="idle", state="idle", intent=intent, source="navigation")


def _module(**logging_settings):
    module = DecisionLogModule("decision_log")
    context = RuntimeContext()
    context.set("settings", {"logging": logging_settings})
    return module, context


def test_each_new_record_is_appended():
    module, context = _module()
    module.tick(context)
    context.set("decision_record", _record(1.0))
    module.tick(context)
    context.set("decision_record", _record(2.0))
    module.tick(context)
    assert [r.ts for r in context.get("decision_ring").recent()] == [1.0, 2.0]


def test_the_same_record_ticked_twice_is_appended_once():
    module, context = _module()
    context.set("decision_record", _record(1.0))
    module.tick(context)
    module.tick(context)
    assert len(context.get("decision_ring")) == 1


def test_two_records_with_the_same_timestamp_are_both_kept():
    """Identity, not `ts`: a frozen or coarse clock gives two decisions one timestamp."""
    module, context = _module()
    context.set("decision_record", _record(5.0))
    module.tick(context)
    context.set("decision_record", _record(5.0))  # a new record, same clock reading
    module.tick(context)
    assert len(context.get("decision_ring")) == 2


def test_a_tick_before_the_first_record_publishes_an_empty_ring():
    module, context = _module()
    module.tick(context)
    ring = context.get("decision_ring")
    assert ring is not None
    assert len(ring) == 0
    assert ring.latest() is None


def test_the_ring_does_not_inherit_the_event_log_flag():
    module, context = _module(event_log_enabled=False)
    context.set("decision_record", _record())
    module.tick(context)
    assert len(context.get("decision_ring")) == 1


def test_the_master_flag_stops_the_feed(tmp_path: Path):
    path = tmp_path / "decisions.jsonl"
    module, context = _module(
        decision_log_enabled=False,
        decision_log_file_enabled=True,
        decision_log_path=str(path),
    )
    context.set("decision_record", _record())
    module.tick(context)
    # The ring is still published: "no feed" and "no decisions yet" are different answers.
    assert context.get("decision_ring") is not None
    assert len(context.get("decision_ring")) == 0
    assert not path.exists()


def test_the_ring_keeps_only_the_configured_number_of_records():
    module, context = _module(decision_log_max_entries=2)
    for index in range(3):
        context.set("decision_record", _record(float(index)))
        module.tick(context)
    ring = context.get("decision_ring")
    assert ring.max_entries == 2
    assert [r.ts for r in ring.recent()] == [1.0, 2.0]


def test_something_that_is_not_a_decision_is_ignored():
    module, context = _module()
    context.set("decision_record", {"ts": 1.0})
    module.tick(context)
    assert len(context.get("decision_ring")) == 0


def test_the_file_carries_one_line_per_record(tmp_path: Path):
    path = tmp_path / "decisions.jsonl"
    module, context = _module(
        decision_log_file_enabled=True, decision_log_path=str(path)
    )
    context.set("decision_record", _record(1.0))
    module.tick(context)
    context.set("decision_record", _record(2.0))
    module.tick(context)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "decision"
    assert first["schema_version"] == 1
    assert first["ts"] == 1.0
    assert first["intent"] == "walk"


def test_the_file_is_off_unless_asked_for(tmp_path: Path):
    path = tmp_path / "decisions.jsonl"
    module, context = _module(decision_log_path=str(path))
    context.set("decision_record", _record())
    module.tick(context)
    assert len(context.get("decision_ring")) == 1
    assert not path.exists()


def test_the_file_rotates_once_at_the_cap(tmp_path: Path):
    path = tmp_path / "decisions.jsonl"
    path.write_text("x" * 2048, encoding="utf-8")
    DecisionLogModule._rotate_if_needed(path, {"decision_log_max_mb": 0.001})
    rotated = path.with_suffix(path.suffix + ".1")
    assert rotated.exists()
    assert rotated.read_text(encoding="utf-8") == "x" * 2048
    assert not path.exists()


def test_zero_cap_disables_rotation(tmp_path: Path):
    path = tmp_path / "decisions.jsonl"
    path.write_text("x" * 2048, encoding="utf-8")
    DecisionLogModule._rotate_if_needed(path, {"decision_log_max_mb": 0})
    assert not path.with_suffix(path.suffix + ".1").exists()
    assert path.exists()


def test_the_ring_accepts_what_the_gateway_actually_publishes():
    """Every other test here builds its own record; this one uses the real producer."""
    context = RuntimeContext()
    context.set("settings", {"logging": {}})
    gateway = MotionGatewayModule(
        "motion_gateway", interlock=Interlock(), bus=CommandBus(), board=IntentBoard()
    )
    gateway.start(context)
    gateway.tick(context)

    module = DecisionLogModule("decision_log")
    module.start(context)
    module.tick(context)

    ring = context.get("decision_ring")
    assert len(ring) == 1
    # The gateway's own object, not a copy that happens to match.
    assert ring.latest() is context.get("decision_record")
    assert isinstance(ring.latest(), DecisionRecord)
