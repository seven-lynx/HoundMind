"""The shared context is written by daemon threads and read by the loop.

The old bare dict made that a race: CPython keeps a single `setitem` atomic, but iteration is
not, so anything walking the mapping could raise "dictionary changed size during iteration".
These tests pin the mechanics that make the bus safe.
"""

from __future__ import annotations

import threading

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.state import StateStore


def test_set_and_get() -> None:
    store = StateStore()
    store.set("speed", 40)
    assert store.get("speed") == 40


def test_missing_key_returns_the_default() -> None:
    assert StateStore().get("nope", "fallback") == "fallback"


def test_none_is_a_value_not_an_absence() -> None:
    store = StateStore()
    store.set("last_error", None)
    assert "last_error" in store
    assert store.get("last_error", "default") is None


def test_snapshot_is_a_copy() -> None:
    store = StateStore({"a": 1})
    snapshot = store.snapshot()
    snapshot["a"] = 2
    assert store.get("a") == 1


def test_update_is_visible_as_one_set() -> None:
    store = StateStore()
    store.update({"a": 1, "b": 2})
    assert store.snapshot() == {"a": 1, "b": 2}


def test_pop_removes() -> None:
    store = StateStore({"a": 1})
    assert store.pop("a") == 1
    assert "a" not in store


def test_iteration_is_over_a_copy() -> None:
    store = StateStore({"a": 1, "b": 2})
    assert set(store) == {"a", "b"}
    assert len(store) == 2


def test_concurrent_writers_do_not_break_snapshot() -> None:
    """The failure this prevents: RuntimeError while iterating during a write."""
    store = StateStore()
    stop = threading.Event()
    failures: list[BaseException] = []

    def writer(prefix: str) -> None:
        index = 0
        while not stop.is_set():
            store.set(f"{prefix}{index % 50}", index)
            index += 1

    def reader() -> None:
        try:
            while not stop.is_set():
                # Iterating the raw mapping used to raise here.
                for _key, _value in store.snapshot().items():
                    pass
                for _key in store:
                    pass
        except BaseException as exc:  # noqa: BLE001 - the point of the test
            failures.append(exc)

    threads = [
        threading.Thread(target=writer, args=("a",)),
        threading.Thread(target=writer, args=("b",)),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for thread in threads:
        thread.start()
    try:
        threading.Event().wait(0.3)
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=2)

    assert not failures, failures


def test_runtime_context_keeps_the_familiar_api() -> None:
    context = RuntimeContext()
    context.set("settings", {"logging": {}})
    assert context.get("settings") == {"logging": {}}
    assert "settings" in context
    assert context.snapshot() == {"settings": {"logging": {}}}


def test_runtime_context_accepts_a_shared_store() -> None:
    store = StateStore()
    first = RuntimeContext(store)
    second = RuntimeContext(store)
    first.set("shared", True)
    assert second.get("shared") is True