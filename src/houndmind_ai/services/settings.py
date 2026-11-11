"""Typed view of `settings.api`.

The schema in `kernel/config_schema.py` already rejected a bad value at load, so the coercion
here is belt-and-braces for the case that matters: a module constructed by a test with a plain
dict. Nothing in this file reads the filesystem, opens a socket, or generates a token.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "ApiSettings"]

# The shipped posture (D7/D8): reachable on the LAN, authenticated on everything except
# `/meta` and `/health`. A loopback default would mean the documented laptop-to-dog workflow
# silently fails on a fresh install.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8420


def _table(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_str(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(value, maximum))


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    if number != number:  # NaN is "missing", never a delay.
        return default
    return max(minimum, min(number, maximum))


@dataclass(frozen=True)
class ApiSettings:
    """Everything the control plane needs to open one port."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    # Path to the install-issued token. `~` is expanded by the token store, not here, so this
    # value stays readable in an error message.
    token_path: str = "~/.houndmind/api_token"
    # Directory holding the pre-built web app. None means "the bundled `web/` directory".
    static_root: str | None = None
    # Telemetry push rate on the WebSocket. 10 Hz is the contract; faster floods a phone.
    state_hz: float = 10.0
    pairing_enabled: bool = True
    pairing_attempts_per_minute: int = 5
    # Bounded hand-off to the gateway: a client that spams commands gets 429, not a backlog.
    command_queue: int = 64
    # How long a POST /command waits for the gateway's verdict before answering 503.
    command_ack_timeout_s: float = 0.5
    # A connected client that stops pinging for this long has its command dropped.
    link_loss_s: float = 6.0
    max_clients: int = 8
    # `GET /logs?tail=` default and ceiling.
    log_tail: int = 200

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any] | None) -> ApiSettings:
        raw = _table(_table(settings).get("api"))
        token_path = raw.get("token_path")
        static_root = raw.get("static_root")
        return cls(
            host=_as_str(raw.get("host"), DEFAULT_HOST),
            port=_as_int(raw.get("port"), DEFAULT_PORT, 1, 65535),
            token_path=_as_str(token_path, cls.token_path),
            static_root=static_root if isinstance(static_root, str) and static_root else None,
            state_hz=_as_float(raw.get("state_hz"), cls.state_hz, 1.0, 50.0),
            pairing_enabled=_as_bool(raw.get("pairing_enabled"), cls.pairing_enabled),
            pairing_attempts_per_minute=_as_int(
                raw.get("pairing_attempts_per_minute"),
                cls.pairing_attempts_per_minute,
                1,
                60,
            ),
            command_queue=_as_int(raw.get("command_queue"), cls.command_queue, 1, 1024),
            command_ack_timeout_s=_as_float(
                raw.get("command_ack_timeout_s"), cls.command_ack_timeout_s, 0.05, 5.0
            ),
            link_loss_s=_as_float(raw.get("link_loss_s"), cls.link_loss_s, 1.0, 60.0),
            max_clients=_as_int(raw.get("max_clients"), cls.max_clients, 1, 64),
            log_tail=_as_int(raw.get("log_tail"), cls.log_tail, 1, 5000),
        )