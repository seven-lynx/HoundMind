"""Typed commands: the one vocabulary every motion producer speaks.

Replaces the legacy pattern where ``safety_action``, ``watchdog_action``,
``navigation_action`` and ``behavior_action`` were four context strings merged by a
hand-written precedence chain and deduplicated by string equality.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

__all__ = [
    "FORWARD_ACTIONS",
    "KNOWN_ACTIONS",
    "MOTION_ACTIONS",
    "Command",
    "Source",
    "Verdict",
]


class Source(IntEnum):
    """Who asked for the motion. Higher wins.

    Ordered explicitly so precedence is declared once, here, instead of being rediscovered
    by the order of keys in a lookup chain.
    """

    BEHAVIOUR = 10
    NAVIGATION = 20
    CLIENT = 30
    WATCHDOG = 40
    SYSTEM = 50


MOTION_ACTIONS = frozenset({"forward", "backward", "turn_left", "turn_right"})
FORWARD_ACTIONS = frozenset({"forward"})
KNOWN_ACTIONS = MOTION_ACTIONS | frozenset(
    {
        "stop",
        "stand",
        "sit",
        "lie",
        "stretch",
        "wag_tail",
        "bark",
        "head",
    }
)

DEFAULT_TTL_MS = 300


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass(frozen=True)
class Command:
    """A request to move. Immutable: renew it, do not mutate it."""

    action: str
    source: Source = Source.CLIENT
    params: dict[str, Any] = field(default_factory=dict)
    ttl_ms: int = DEFAULT_TTL_MS
    issued_at: float = 0.0
    id: str = field(default_factory=_new_id)

    def deadline(self) -> float:
        """Epoch/monotonic seconds after which this command must not run."""
        return self.issued_at + (max(0, self.ttl_ms) / 1000.0)

    def expired(self, now: float) -> bool:
        return now > self.deadline()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "action": self.action,
            "source": self.source.name.lower(),
            "params": dict(self.params),
            "ttl_ms": self.ttl_ms,
            "issued_at": self.issued_at,
        }


@dataclass(frozen=True)
class Verdict:
    """The interlock's answer. A refusal always carries a reason."""

    accepted: bool
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    veto: str | None = None
    detail: str | None = None
    retry_after_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "accepted": self.accepted,
            "action": self.action,
            "params": dict(self.params),
        }
        if not self.accepted:
            payload["veto"] = self.veto
            payload["detail"] = self.detail
            payload["retry_after_ms"] = self.retry_after_ms
        elif self.detail:
            payload["detail"] = self.detail
        return payload