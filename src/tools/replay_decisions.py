"""Replay a recorded decision log against the real control plane, with no dog attached.

`logs/houndmind_decisions.jsonl` is what a runtime writes when
`logging.decision_log_file_enabled` is true (`logging/decision_log.py`). This tool reads it back,
rebuilds each `DecisionRecord`, and drives the *real* control plane over a synthetic context, so
`GET /api/v1/decisions`, `state.decision` and the `decision` socket event can be developed and
reviewed on a laptop (design §14.2). Without it, "replayable" in §15 is a claim.

Three rules, and all three are about not lying to the client on the other end:

1. **Only what the record contains is published.** The record carries the choice, its reasons and
   seven readings (`act/gateway.py::_decision_inputs`). The snapshot's sensors are projected from
   those seven; touch and sound are absent from the log, so they stay invalid rather than being
   invented. A replay is a decision feed, not a sensor feed.
2. **The recorded `ts` is history.** It comes from the *device's* monotonic clock, so it is passed
   through unchanged and used only for deltas when pacing — never compared with this machine's
   clock, and never rewritten to look local.
3. **Replay is read-only.** `POST /command` reaches a command bus nothing drains, so it answers 503
   after the ack timeout. A synthetic "accepted" would be exactly the lie the control plane exists
   to avoid, and nothing here constructs a HAL, so no servo can move.

Usage:
    python -m tools.replay_decisions logs/houndmind_decisions.jsonl
    python -m tools.replay_decisions logs/houndmind_decisions.jsonl --check
    python -m tools.replay_decisions logs/houndmind_decisions.jsonl --speed 0 --limit 300
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.commands import CommandBus
from houndmind_ai.kernel.decisions import (
    DEFAULT_MAX_ENTRIES,
    DecisionRecord,
    DecisionRing,
)
from houndmind_ai.services.module import ControlPlaneModule
from houndmind_ai.services.settings import DEFAULT_HOST, DEFAULT_PORT, ApiSettings

__all__ = [
    "MAX_DELTA_S",
    "ReplaySensors",
    "ReplaySession",
    "load_records",
    "main",
    "schedule",
    "sensors_from_record",
    "summarize",
]

# A gap longer than this is a pause on the device (a restart, a stalled loop), not a cadence.
# Replaying twenty minutes of silence in real time is never what the person at the keyboard meant.
MAX_DELTA_S = 60.0


@dataclass(frozen=True)
class ReplaySensors:
    """The `sensor_reading` shape `services/state.py::_sensors` reads.

    Only the fields a decision record can supply are populated. Touch and sound have no field
    here on purpose: the log does not carry them, and a default of `"N"` with `touch_valid=False`
    is the honest way to say "not recorded".
    """

    timestamp: float
    distance_cm: float | None
    distance_valid: bool
    touch: str = "N"
    touch_valid: bool = False
    sound_detected: bool = False
    sound_direction: int | None = None
    sound_valid: bool = False


def _number(value: object) -> float | None:
    """A float, or None. `bool` is not a reading and NaN is not a distance."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return None if number != number else number



def load_records(path: Path) -> tuple[list[DecisionRecord], int]:
    """Every record in `path`, oldest first, plus how many lines had to be skipped.

    A truncated **final** line is normal — a killed process or a power cut leaves exactly one —
    so it is dropped and counted. Any other bad line is fatal: half-replaying a file would show a
    client a history that never happened.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    last = -1
    for index, line in enumerate(lines):
        if line.strip():
            last = index
    if last < 0:
        return [], 0

    records: list[DecisionRecord] = []
    skipped = 0
    for index, line in enumerate(lines):
        payload_text = line.strip()
        if not payload_text:
            continue
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            if index == last:
                skipped += 1
                continue
            raise ValueError(f"{path}:{index + 1}: not JSON") from None
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{index + 1}: a decision record must be an object")
        kind = payload.get("type")
        if kind is not None and kind != "decision":
            # `logs/houndmind_events.jsonl` is `type: snapshot`. Pointing the tool at the wrong
            # file must say so on its first line instead of replaying zero decisions in silence.
            raise ValueError(
                f"{path}:{index + 1}: line type {kind!r} is not a decision record"
                " (the decision log is logs/houndmind_decisions.jsonl)"
            )
        try:
            records.append(DecisionRecord.from_dict(payload))
        except ValueError as exc:
            raise ValueError(f"{path}:{index + 1}: {exc}") from None
    return records, skipped


def schedule(records: list[DecisionRecord], speed: float) -> list[float]:
    """Seconds to wait before each record: the recorded deltas, divided by `speed`.

    `speed <= 0` means "do not wait", which is what makes the tool usable from a test and from
    `--check`. Zero, negative and NaN deltas become 0 (a coarse clock, or a clock that went
    backwards on the device); a gap over `MAX_DELTA_S` is clamped.
    """
    delays = [0.0]
    # `strict=False` on purpose: the second iterable is one record shorter.
    for previous, current in zip(records, records[1:], strict=False):
        gap = current.ts - previous.ts
        if gap != gap or gap <= 0:  # NaN, or time that ran backwards
            gap = 0.0
        delays.append(min(gap, MAX_DELTA_S) / speed if speed > 0 else 0.0)
    return delays


def sensors_from_record(record: DecisionRecord) -> ReplaySensors:
    """Project the record's `inputs` into a sensor reading, validity flags included."""
    inputs = record.inputs
    distance = _number(inputs.get("distance_cm"))
    return ReplaySensors(
        timestamp=record.ts,
        distance_cm=distance,
        # A value with a false flag is not a measurement; a flag with no value cannot be one.
        distance_valid=bool(inputs.get("distance_valid")) and distance is not None,
    )


def command_from_record(record: DecisionRecord) -> dict[str, object] | None:
    """The winner, as the `motion_command` the snapshot reads (`services/state.py:60-74`).

    A record with no intent decided nothing to execute, so there is no command — not a command
    with an empty action, which a client would render as a dog doing something nameless.
    """
    if not record.intent:
        return None
    return {
        "canonical_action": record.intent,
        "source": record.source,
        "issued_at": record.ts,
    }


class ReplaySession:
    """One context, one ring, one record at a time.

    Leaves on the context exactly what `act/gateway.py` and `logging/decision_log.py` leave during
    a real run — `decision_record`, `decision_ring`, `runtime_mode`, `sensor_reading` and
    `motion_command` — so the control plane reads a replay the way it reads a dog. Nothing else is
    set, and nothing that is set is invented.
    """

    def __init__(self, ring_size: int = DEFAULT_MAX_ENTRIES) -> None:
        self.context = RuntimeContext()
        self.ring = DecisionRing(ring_size)
        self.context.set("settings", {"api": {}, "logging": {}})
        self.context.set("module_names", ["replay"])
        self.context.set("module_statuses", {})

    def step(self, record: DecisionRecord) -> None:
        """Publish one tick, in the order the runtime would have published it."""
        self.context.set("decision_record", record)
        self.context.set("runtime_mode", record.mode)
        self.context.set("sensor_reading", sensors_from_record(record))
        # `{}` rather than leaving the previous tick's command in place: a record with no intent
        # is the dog doing nothing, and a stale command would claim it was still moving.
        self.context.set("motion_command", command_from_record(record) or {})
        self.ring.append(record)
        self.context.set("decision_ring", self.ring)
        if record.trace_id and self.context.get("trace_id") is None:
            # The run's own trace id, read from the log. Never generated: the client is looking at
            # a run that already happened, and a fresh id would join it to nothing.
            self.context.set("trace_id", record.trace_id)


def _top(counts: dict[str, int], limit: int = 5) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def summarize(records: list[DecisionRecord]) -> list[str]:
    """What `--check` prints: the shape of a session, in counts rather than opinion."""
    intents: dict[str, int] = {}
    reasons: dict[str, int] = {}
    silent = 0
    for record in records:
        if record.intent is None:
            silent += 1
        else:
            label = f"{record.intent} ({record.source or 'unknown'})"
            intents[label] = intents.get(label, 0) + 1
        for refusal in record.vetoes:
            reasons[refusal.reason] = reasons.get(refusal.reason, 0) + 1

    span = records[-1].ts - records[0].ts if len(records) > 1 else 0.0
    return [
        f"records: {len(records)}  span: {span:.1f} s of device clock",
        f"silent ticks (no intent): {silent}",
        "intents:",
        *[f"  {count:6d}  {label}" for label, count in _top(intents)],
        "refusal reasons:",
        *[f"  {count:6d}  {reason}" for reason, count in _top(reasons)],
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay a recorded decision log through the control plane (no dog, no motion)"
    )
    parser.add_argument("path", type=Path, help="path to houndmind_decisions.jsonl")
    parser.add_argument("--speed", type=float, default=1.0, help="playback speed; 0 = no waiting")
    parser.add_argument("--limit", type=int, default=0, help="replay only the last N records")
    parser.add_argument("--check", action="store_true", help="validate and summarise, serve nothing")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"bind address (default {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"port (default {DEFAULT_PORT})")
    parser.add_argument("--token-path", default=None, help="token file the client must present")
    parser.add_argument(
        "--linger", type=float, default=0.0, help="keep serving N seconds after the last record"
    )
    args = parser.parse_args(argv)

    try:
        records, skipped = load_records(args.path)
    except (OSError, ValueError) as exc:
        print(f"[replay] {exc}")
        return 2
    if args.limit > 0:
        records = records[-args.limit:]
    if not records:
        print(f"[replay] {args.path} holds no decision records")
        return 2
    if skipped:
        print(f"[replay] ignored {skipped} truncated line(s) at the end of the file")
    for line in summarize(records):
        print(f"[replay] {line}")
    if args.check:
        return 0

    print("[replay] read-only: POST /command has no gateway behind it and will time out")
    session = ReplaySession()
    raw_settings = session.context.get("settings")
    settings: dict[str, object] = dict(raw_settings) if isinstance(raw_settings, dict) else {}
    api: dict[str, object] = {"host": args.host, "port": args.port}
    if args.token_path:
        api["token_path"] = args.token_path
    settings["api"] = api
    session.context.set("settings", settings)

    bus = CommandBus()
    session.context.set("command_bus", bus)
    plane = ControlPlaneModule("api", enabled=True, bus=bus)
    plane.start(session.context)
    if plane.status.last_error or not plane.status.enabled:
        print(f"[replay] control plane did not start: {plane.status.last_error or 'unknown reason'}")
        return 2
    # The token *path* is printed, never the token: it is a secret, and the client developer reads
    # the same 0600 file the app does.
    token_path = ApiSettings.from_settings(settings).token_path
    print(f"[replay] serving http://{args.host}:{args.port} (token file: {token_path})")
    print("[replay] Ctrl+C to stop; nothing here can move a servo")
    try:
        # `strict=True`: one delay per record is an invariant, so a short schedule is a bug here.
        for record, delay in zip(records, schedule(records, args.speed), strict=True):
            if delay > 0:
                time.sleep(delay)
            session.step(record)
        if args.linger > 0:
            time.sleep(args.linger)
    except KeyboardInterrupt:
        print("\n[replay] interrupted")
        return 130
    finally:
        plane.stop(session.context)
    print(f"[replay] replayed {len(records)} records; {len(session.ring)} kept in the ring")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
