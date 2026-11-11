"""A thread-safe, snapshot-based store for the shared runtime context.

`RuntimeContext` used to be a bare `dict`, and two consequences of that were live bugs:

- The sensor service publishes readings from a daemon thread while the main loop reads and
  writes the same mapping. CPython makes a single `dict.__setitem__` atomic, but iteration is
  not, so anything that walks the context can raise "dictionary changed size during
  iteration" — and the logging filter walked it on every single record.
- Nothing described which keys exist. A typo in one module read as `None` in another, and a
  key could hold a string one tick and a `Config` the next.

`StateStore` fixes the mechanics rather than the symptoms: one re-entrant lock, whole-value
writes, and snapshot reads for anything that needs to iterate. It deliberately does not
enforce a key schema — modules own their own keys, and the registry of keys is the context
documentation in `docs/api_reference.md`, not a runtime gate.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from typing import Any

__all__ = ["StateStore"]


class StateStore:
    """A lock-protected mapping shared between the loop and background workers."""

    __slots__ = ("_data", "_lock")

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, Any] = dict(initial or {})

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def pop(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.pop(key, default)

    def update(self, values: Mapping[str, Any]) -> None:
        """Write several keys under one lock, so readers never see a half-applied set."""
        with self._lock:
            self._data.update(values)

    def snapshot(self) -> dict[str, Any]:
        """A shallow copy. Iterate this, not the store, when order or size matters."""
        with self._lock:
            return dict(self._data)

    def keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._data)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __repr__(self) -> str:
        return f"StateStore({len(self)} keys)"