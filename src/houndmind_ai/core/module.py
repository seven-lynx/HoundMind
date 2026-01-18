from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from houndmind_ai.core.runtime import RuntimeContext


logger = logging.getLogger(__name__)


class ModuleError(RuntimeError):
    pass


@dataclass
class ModuleStatus:
    enabled: bool
    required: bool
    started: bool = False
    disabled_reason: str | None = None
    # Timestamp of the last successful tick (epoch seconds).
    last_tick_ts: float | None = None
    # Timestamp of the last heartbeat recorded by the runtime (epoch seconds).
    last_heartbeat_ts: float | None = None
    # Last error message encountered while starting or ticking.
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        # Provide a stable snapshot for runtime reporting and logging.
        return {
            "enabled": self.enabled,
            "required": self.required,
            "started": self.started,
            "disabled_reason": self.disabled_reason,
            "last_tick_ts": self.last_tick_ts,
            "last_heartbeat_ts": self.last_heartbeat_ts,
            "last_error": self.last_error,
        }


class Module:
    name: str

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        self.name = name
        self.status = ModuleStatus(enabled=enabled, required=required)

    def start(self, context: "RuntimeContext") -> None:
        self.status.started = True

    def stop(self, context: "RuntimeContext") -> None:
        self.status.started = False

    def tick(self, context: "RuntimeContext") -> None:
        return None

    def disable(self, reason: str) -> None:
        self.status.enabled = False
        self.status.started = False
        self.status.disabled_reason = reason
        # Track the last error for health/status reporting.
        self.status.last_error = reason
        logger.warning("Module %s disabled: %s", self.name, reason)
