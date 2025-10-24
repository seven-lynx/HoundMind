"""
LearningService: lightweight, JSON-backed counters for on-device learning.

- Tracks categories (e.g., "interactions", "commands", "obstacles") with string keys and integer counts.
- Safe to use on non-Pi and in simulation; creates a data folder locally if missing.
- Autosaves periodically and on explicit save/close.

Config flags used:
- ENABLE_LEARNING_SYSTEM (bool): controls whether the orchestrator wires this service.

Data location:
- <repo_root>/data/canine_core/learning.json

Author: 7Lynx
Doc Version: 2025.10.24
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple


def _repo_root() -> str:
    # canine_core/core/services/learning.py -> repo root is three levels up from canine_core
    here = os.path.abspath(os.path.dirname(__file__))
    # .../canine_core/core/services -> .../HoundMind
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    return root


class LearningService:
    """
    Minimal learning/counters service with JSON persistence.

    Thread-safe increments and periodic autosave.
    """

    def __init__(
        self,
    config: Optional[Any] = None,
        logger: Optional[Any] = None,
        path: Optional[str] = None,
        autosave_interval_s: float = 30.0,
    ) -> None:
        self._config = config or {}
        self._logger = logger
        self._lock = threading.RLock()
        self._last_save = 0.0
        self._autosave_interval_s = autosave_interval_s

        root = _repo_root()
        default_dir = os.path.join(root, "data", "canine_core")
        os.makedirs(default_dir, exist_ok=True)
        self._path = path or os.path.join(default_dir, "learning.json")

        self._data: Dict[str, Dict[str, int]] = {
            "interactions": {},
            "commands": {},
            "obstacles": {},
        }
        self._load()

    # -------------------- Persistence --------------------
    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        # shallow merge known categories; ignore unknowns for forwards-compat
                        for k in self._data.keys():
                            if k in raw and isinstance(raw[k], dict):
                                self._data[k].update({k2: int(v) for k2, v in raw[k].items()})
        except Exception as e:
            if self._logger:
                self._logger.warning(f"LearningService load failed: {e}")

    def save(self) -> None:
        with self._lock:
            try:
                tmp_path = self._path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, sort_keys=True)
                os.replace(tmp_path, self._path)
                self._last_save = time.time()
            except Exception as e:
                if self._logger:
                    self._logger.warning(f"LearningService save failed: {e}")

    def close(self) -> None:
        self.save()

    # -------------------- API --------------------
    def increment(self, category: str, key: str, amount: int = 1) -> int:
        if not key:
            return 0
        if amount == 0:
            return self.get_count(category, key)
        with self._lock:
            cat = self._data.setdefault(category, {})
            new_val = int(cat.get(key, 0)) + int(amount)
            cat[key] = new_val
        self._maybe_autosave()
        return new_val

    def record_interaction(self, key: str, amount: int = 1) -> int:
        return self.increment("interactions", key, amount)

    def record_command(self, key: str, amount: int = 1) -> int:
        return self.increment("commands", key, amount)

    def record_obstacle(self, key: str, amount: int = 1) -> int:
        return self.increment("obstacles", key, amount)

    def get_count(self, category: str, key: str) -> int:
        with self._lock:
            return int(self._data.get(category, {}).get(key, 0))

    def snapshot(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            # deep copy
            return {
                cat: {k: int(v) for k, v in d.items()} for cat, d in self._data.items()
            }

    def top_n(self, category: str, n: int = 5) -> Tuple[Tuple[str, int], ...]:
        with self._lock:
            items = list(self._data.get(category, {}).items())
        items.sort(key=lambda kv: kv[1], reverse=True)
        return tuple(items[: max(0, n)])

    # -------------------- Internal --------------------
    def _maybe_autosave(self) -> None:
        now = time.time()
        if now - self._last_save >= self._autosave_interval_s:
            self.save()
