"""Where internal producers leave their intent, and where the gateway finds it.

The four legacy context keys (`safety_action`, `watchdog_action`, `navigation_action`,
`behavior_action`) had two defects that no amount of care in the producers could fix:

- **They never expired.** `act/gateway.py` re-stamped whatever it found in them with the
  current tick's timestamp, so a navigation module that wedged mid-sentence kept the dog
  walking forever. The deadman protected clients and only clients.
- **Clearing was a second write.** A producer that crashed before writing ``None`` left its
  last intent in place, and "I forgot to clear" was indistinguishable from "I still mean it".

:class:`IntentBoard` gives every :class:`~houndmind_ai.kernel.commands.Source` one slot. A
producer publishes, the entry remembers when it was published, and it stops being visible once
the board's hold window passes. Publishing the same intent again refreshes it — that is the
whole protocol. A producer that stops, crashes or blocks simply stops refreshing, and the dog
stops. Nothing has to be un-set.

The hold window belongs to the board, not to the producer: a producer cannot accidentally make
its intent permanent by asking for a long TTL. One window is enough because every producer
publishes at least once per tick, and the shipped loop runs far faster than the default.

This is deliberately **not** the :class:`~houndmind_ai.kernel.commands.CommandBus`. A bus is an
inbox: it queues, it demands one acknowledgement per item, and it is the right shape for a
client that asked a question and is waiting for an answer. An intent is a *state*: it is
replaced, it is read every tick, and nobody is waiting for a per-tick acknowledgement.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from houndmind_ai.kernel.commands import Command, Source, canonical_action

__all__ = ["INTERNAL_HOLD_MS", "IntentBoard"]

# How long an intent survives without being published again. One second is five ticks at the
# shipped 5 Hz and five at the Pi 4 profile's 10 Hz, so an ordinary hiccup never stops the dog,
# while a producer that has actually stopped is caught long before a human would notice. It is
# also short enough that no intent can outlive a `stop`.
INTERNAL_HOLD_MS = 1000


@dataclass(frozen=True)
class _Slot:
    """One source's standing intent, and the moment it must be refreshed by."""

    command: Command
    expires_at: float


class IntentBoard:
    """Latest-value intent per :class:`Source`, expiring unless refreshed.

    Thread-safe: producers tick on the loop thread while the event logger and the control plane
    read from their own, which is exactly the unsynchronised-shared-dict bug (H-02) this
    replaces rather than repeats.
    """

    def __init__(
        self,
        hold_ms: int = INTERNAL_HOLD_MS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._hold_s = max(0, int(hold_ms)) / 1000.0
        self._lock = threading.Lock()
        self._slots: dict[Source, _Slot] = {}
        # Diagnostics: an intent that expired unrefreshed is a producer that stopped, and that
        # number is the cheapest evidence that something wedged.
        self.expired = 0
        self.published = 0

    # ---- producer side -----------------------------------------------------

    def publish(
        self,
        action: str,
        source: Source,
        params: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> Command:
        """Publish `source`'s intent for this tick and return the stamped command.

        The action is canonicalised here (not at the call site) so a producer can keep spelling
        motion however its own module reads best.
        """
        stamp = self._clock() if now is None else now
        command = Command(
            action=canonical_action(action),
            source=source,
            params=dict(params or {}),
            ttl_ms=int(self._hold_s * 1000),
            issued_at=stamp,
        )
        with self._lock:
            self._slots[source] = _Slot(command, stamp + self._hold_s)
            self.published += 1
        return command

    def retract(self, source: Source) -> None:
        """Withdraw `source`'s intent now, without waiting for it to expire."""
        with self._lock:
            self._slots.pop(source, None)

    # ---- consumer side -----------------------------------------------------

    def latest(self, now: float | None = None) -> list[Command]:
        """Every live intent, highest-priority source first."""
        stamp = self._clock() if now is None else now
        live: list[Command] = []
        with self._lock:
            for source in sorted(self._slots, reverse=True):
                slot = self._slots[source]
                if stamp > slot.expires_at:
                    del self._slots[source]
                    self.expired += 1
                    continue
                live.append(slot.command)
        return live

    def find(self, source: Source, now: float | None = None) -> Command | None:
        """`source`'s live intent, or None when it has not published or has gone stale."""
        stamp = self._clock() if now is None else now
        with self._lock:
            slot = self._slots.get(source)
            if slot is None:
                return None
            if stamp > slot.expires_at:
                del self._slots[source]
                self.expired += 1
                return None
            return slot.command

    def snapshot(self, now: float | None = None) -> dict[str, str]:
        """`{source: action}` for diagnostics, e.g. the event log."""
        return {
            command.source.name.lower(): command.action for command in self.latest(now)
        }

    def __len__(self) -> int:
        with self._lock:
            return len(self._slots)

    def __repr__(self) -> str:
        live = sorted(source.name.lower() for source in self._slots)
        return f"IntentBoard(live={live}, expired={self.expired})"