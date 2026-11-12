"""The decision record: why the dog did that, one row per tick.

The state snapshot can say *what* the dog is doing — one action and, when the navigator has an
opinion, a confidence (`services/state.py::_nav`). It cannot say why. The behaviour module keeps
its state private, and the gateway keeps every refused verdict local while it ranks the tick
(`act/gateway.py::_resolve`), so a client that sees `veto: "obstacle"` has no way to compare it
with the intents that lost the same tick.

This module is the missing half: a fixed-shape record of one tick's decision, plus the bounded
ring that keeps the last few seconds of them. Four rules ride on it.

1. **One record per tick, whatever happened.** "The dog did nothing" is a decision — an
   unexplained pet is indistinguishable from a broken one.
2. **`confidence` is `None`, never `0.0`, when nothing measured it.** The same rule the rest of
   the runtime follows for a sensor that did not answer.
3. **A refusal keeps its reason.** `Refusal.reason` is the interlock's own `veto` string
   (``obstacle``, ``tilt``, ``low_voltage``, ``expired``, ``unknown_action``) or one of two
   precedence words this module adds: ``mode`` for an intent the mode policy dropped before
   ranking, ``precedence`` for one the interlock accepted and a higher rank then displaced.
4. **Nothing is invented.** `inputs` carries the readings the decision used, with their validity
   flags, and a missing reading is absent rather than zero.
5. **The wire shape is read back by the module that writes it.** `to_dict` is what the route, the
   socket and the JSONL emit; `from_dict` is the reader `SCHEMA_VERSION` exists for. A log from a
   build that writes a different shape is refused by name, never half-understood, because a replay
   tool that guesses is a replay of a dog that never existed.

The record's per-tick identity is `ts`, from the producer's monotonic clock. `trace_id` identifies
the *run* — it is generated once per process (`core/runtime.py`) — so it joins a record to the log
but cannot tell two ticks apart. A consumer that wants to notice a new record compares `ts`.

No I/O, no clock, no config at import time: the gateway builds the record from values it already
holds, and the ring is a deque.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from houndmind_ai.hal.iface import as_int

__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "SCHEMA_VERSION",
    "DecisionRecord",
    "DecisionRing",
    "Refusal",
    "confidence_or_none",
]

# The JSONL and the wire both carry this, so a replay tool can refuse a shape it does not know.
# Matches `logging/event_logger.py::SCHEMA_VERSION`.
SCHEMA_VERSION = 1

# About twenty seconds at the 10 Hz loop the Pi 4 profile runs. Long enough to explain the last
# few decisions to a user, short enough that a client cannot mistake it for history.
DEFAULT_MAX_ENTRIES = 200


def confidence_or_none(value: Any) -> float | None:
    """A confidence the producer actually measured, or `None`.

    `bool` is not a measurement and NaN is not a confidence, so both become `None` rather than a
    plausible-looking number. Values are **not** clamped to 0..1: an out-of-range confidence is a
    producer bug, and scaling it into range would hide that while inventing certainty. `0.0` is
    kept — a measured zero is a fact, unlike a missing reading.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return None if number != number else number


@dataclass(frozen=True)
class Refusal:
    """One intent that did not win the tick, and why."""

    action: str
    source: str
    reason: str
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "source": self.source,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DecisionRecord:
    """One tick's decision. Frozen: a record is history, and history does not change."""

    ts: float
    mode: str
    state: str | None = None
    intent: str | None = None
    source: str | None = None
    vetoes: tuple[Refusal, ...] = ()
    inputs: Mapping[str, object] = field(default_factory=dict)
    confidence: float | None = None
    trace_id: str | None = None

    def __post_init__(self) -> None:
        # `frozen=True` stops the field being *rebound*, not the dict behind it being mutated. A
        # gateway that reuses one readings dict every tick would otherwise rewrite the records
        # already sitting in the ring, and the log would agree with a tick that never happened.
        object.__setattr__(self, "inputs", MappingProxyType(dict(self.inputs)))

    def to_dict(self) -> dict[str, object]:
        """The wire shape, shared by `/decisions`, the WS event and the JSONL line."""
        return {
            "schema_version": SCHEMA_VERSION,
            "ts": self.ts,
            "trace_id": self.trace_id,
            "mode": self.mode,
            "state": self.state,
            "intent": self.intent,
            "source": self.source,
            "vetoes": [refusal.to_dict() for refusal in self.vetoes],
            "inputs": dict(self.inputs),
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> DecisionRecord:
        """Read `to_dict` output back — the reader `SCHEMA_VERSION` exists for.

        Every refusal is by name and specific, because the callers are a replay tool and anything
        else that stored a line: "unsupported schema_version 2" is actionable, while a record that
        silently loses its `vetoes` would show a client a dog that refused nothing for no reason.
        A missing optional field stays `None`; a missing `ts` or `mode` is an error, since neither
        can be defaulted without claiming something that was never recorded.
        """
        if not isinstance(data, Mapping):
            raise ValueError(f"a decision record must be a mapping, not {type(data).__name__}")

        raw_version = data.get("schema_version")
        version = as_int(raw_version, -1)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported decision schema_version {raw_version!r}"
                f" (this build reads {SCHEMA_VERSION})"
            )

        ts = _opt_float(data.get("ts"))
        if ts is None:
            raise ValueError("decision record has no numeric ts")

        mode = data.get("mode")
        if not isinstance(mode, str) or not mode:
            # Defaulting here would make the snapshot claim a mode the dog was never in.
            raise ValueError("decision record has no mode")

        raw_vetoes = data.get("vetoes")
        if raw_vetoes is None:
            raw_vetoes = ()
        if not isinstance(raw_vetoes, (list, tuple)):
            raise ValueError("decision record vetoes must be a list")

        raw_inputs = data.get("inputs")
        if raw_inputs is None:
            raw_inputs = {}
        if not isinstance(raw_inputs, Mapping):
            raise ValueError("decision record inputs must be a mapping")

        return cls(
            ts=ts,
            mode=mode,
            state=_opt_str(data.get("state")),
            intent=_opt_str(data.get("intent")),
            source=_opt_str(data.get("source")),
            vetoes=tuple(_refusal_from_dict(item) for item in raw_vetoes),
            inputs=raw_inputs,
            confidence=confidence_or_none(data.get("confidence")),
            trace_id=_opt_str(data.get("trace_id")),
        )


def _opt_float(value: Any) -> float | None:
    """`confidence_or_none` under the name the reader uses: absent stays absent, never `0.0`."""
    return confidence_or_none(value)


def _opt_str(value: Any) -> str | None:
    """A non-empty string, or None. `""` is a missing value, not an empty name."""
    return value if isinstance(value, str) and value else None


def _refusal_from_dict(data: Any) -> Refusal:
    """One veto off the wire. A veto without a reason is refused, not repaired."""
    if not isinstance(data, Mapping):
        raise ValueError(f"a veto must be a mapping, not {type(data).__name__}")
    fields: dict[str, str] = {}
    for name in ("action", "source", "reason"):
        value = data.get(name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"a veto needs a non-empty {name}")
        fields[name] = value
    return Refusal(
        action=fields["action"],
        source=fields["source"],
        reason=fields["reason"],
        detail=_opt_str(data.get("detail")),
    )


class DecisionRing:
    """The last `max_entries` decision records, oldest first.

    Appended once per tick by the producer and read by the control plane, so the app, the socket
    and the JSONL cannot disagree about what the dog decided: one record, three surfaces.

    Deliberately not a `Module`: it has no cadence of its own. Whoever produces the record owns
    it, and a ring that ticked separately could fall out of step with the gateway that fills it.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        # `as_int` treats junk as missing, so a hand-built context cannot make this a zero-length
        # ring that silently discards every record.
        self._max = max(1, as_int(max_entries, DEFAULT_MAX_ENTRIES))
        self._items: deque[DecisionRecord] = deque(maxlen=self._max)

    @property
    def max_entries(self) -> int:
        return self._max

    def append(self, record: DecisionRecord) -> None:
        self._items.append(record)

    def latest(self) -> DecisionRecord | None:
        """The newest record, or None before the first tick produced one."""
        return self._items[-1] if self._items else None

    def recent(self, limit: int | None = None) -> list[DecisionRecord]:
        """Up to `limit` records, oldest first. A non-positive limit is an empty answer."""
        if limit is None:
            return list(self._items)
        wanted = max(0, as_int(limit, 0))
        if wanted == 0:
            return []
        if wanted >= len(self._items):
            return list(self._items)
        return list(self._items)[-wanted:]

    def __len__(self) -> int:
        return len(self._items)
