from __future__ import annotations
from typing import Callable, Dict, List, Any
import threading


class EventBus:
    """Tiny in-process pub/sub bus.

    - Thread-safe subscriptions
    - Non-throwing publish (logs are caller's responsibility)
    """

    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable[[dict], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: Callable[[dict], None]) -> None:
        with self._lock:
            self._subs.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Callable[[dict], None]) -> None:
        with self._lock:
            handlers = self._subs.get(event_type)
            if not handlers:
                return
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    def publish(self, event_type: str, data: Dict[str, Any] | None = None) -> None:
        payload = data or {}
        # snapshot without holding lock while invoking
        with self._lock:
            handlers = list(self._subs.get(event_type, []))
        for h in handlers:
            try:
                h(payload)
            except Exception:
                # swallow handler errors to keep bus resilient
                pass
