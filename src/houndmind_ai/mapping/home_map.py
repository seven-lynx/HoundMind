"""The home map: one JSON document the dog can write *and* read back.

`MappingModule.save_home_map` has persisted a file since P3 and nothing ever loaded it. Two defects
under one name:

- **The file held no map.** A sample is a per-tick sensor snapshot (`mapper.py:43-53`): `distance_cm`
  is the single forward reading, and the sweep angles that fill the occupancy grid were used for
  openings and dropped. `mapping_state["grid"]` — the actual map — was never written.
- **No reader existed.** `data/home_map.json` was a log for humans to `grep`, so a restart began from
  nothing and every place anchor died with the process.

This module owns the format in both directions, so the writer and the reader cannot drift: the mapper
builds a document here and loads it here, and `tools.map_inspect` reads the same file with the same
validator.

The document is versioned and additive. A file written before this module (no `version`, no `grid`)
still loads — as *samples only*, with a note saying so — because refusing an old file is how a user
loses the one map they have.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "CURRENT_VERSION",
    "DEFAULT_CELL_SIZE_CM",
    "DEFAULT_MAX_CELLS",
    "HomeMap",
    "HomeMapLoad",
    "build_document",
    "load_home_map",
    "write_document",
]

logger = logging.getLogger(__name__)

CURRENT_VERSION = 2
DEFAULT_CELL_SIZE_CM = 10.0
DEFAULT_MAX_CELLS = 20000


def _safe_float(value: Any, default: float) -> float:
    """A finite float, or the default. `True` is not a measurement and NaN is not a distance."""
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_int(value: Any, default: int) -> int:
    """An int, or the default. A string such as `"three"` is not a count."""
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_cells(cells: Mapping[str, Any], max_cells: int) -> tuple[dict[str, int], bool]:
    """Valid `{"ix,iy": hits}` entries, highest hits first, capped at `max_cells`.

    A map that grew without bound is a map that eventually fails to serialise at 3 a.m.; the cap
    keeps the strongest evidence (a cell hit twenty times is a wall, one hit is a maybe) and the
    boolean says the rest was left out, so a consumer never reads a truncated map as a small one.
    """
    parsed: list[tuple[int, str, int]] = []
    for key, raw in cells.items():
        try:
            ix_text, iy_text = str(key).split(",", 1)
            int(ix_text)
            int(iy_text)
            hits = _safe_int(raw, 0)
        except (TypeError, ValueError):
            continue
        if hits <= 0:
            continue
        parsed.append((hits, str(key), hits))

    parsed.sort(key=lambda entry: entry[0], reverse=True)
    truncated = max_cells > 0 and len(parsed) > max_cells
    if truncated:
        parsed = parsed[:max_cells]
    return {key: hits for _hits, key, hits in parsed}, truncated


@dataclass(frozen=True)
class HomeMap:
    """A loaded map. Read-only by convention: `as_grid` hands out copies, never its own cells."""

    version: int
    meta: Mapping[str, Any]
    cells: Mapping[str, int]
    sweep: Mapping[str, float]
    samples: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    @property
    def cell_size_cm(self) -> float:
        size = _safe_float(self.meta.get("cell_size_cm"), DEFAULT_CELL_SIZE_CM)
        return size if size > 0 else DEFAULT_CELL_SIZE_CM

    @property
    def grid_size(self) -> tuple[int, int]:
        raw = self.meta.get("grid_size")
        if isinstance(raw, (list, tuple)) and len(raw) == 2:
            return (_safe_int(raw[0], 100), _safe_int(raw[1], 100))
        return (100, 100)

    def as_grid(self) -> dict[str, Any]:
        """The shape `mapping_state["grid"]` uses, so a loaded map seeds the live one."""
        return {"cells": dict(self.cells)}

    def to_document(self) -> dict[str, Any]:
        """The shape a client receives: JSON-ready, with the sweep angle count rather than the sweep."""
        return {
            "version": self.version,
            "meta": dict(self.meta),
            "cells": dict(self.cells),
            "sweep": dict(self.sweep),
            "samples": len(self.samples),
        }


@dataclass(frozen=True)
class HomeMapLoad:
    """What happened when a file was read. `problems` are fatal; `notes` are things worth saying."""

    map: HomeMap | None
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.map is not None


def _windowed_samples(samples: Any, settings: Mapping[str, Any], now: float) -> list[dict[str, Any]]:
    """The sample window the settings ask for, newest kept, oldest dropped first."""
    if not isinstance(samples, list):
        return []
    kept = [dict(entry) for entry in samples if isinstance(entry, Mapping)]
    max_age_s = _safe_float(settings.get("home_map_max_age_s"), 0.0)
    if max_age_s > 0:
        cutoff = now - max_age_s
        kept = [entry for entry in kept if _safe_float(entry.get("timestamp"), 0.0) >= cutoff]
    max_samples = _safe_int(settings.get("home_map_max_samples"), 0)
    if max_samples > 0 and len(kept) > max_samples:
        kept = kept[-max_samples:]
    return kept


def build_document(
    mapping_state: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """The document to write: the grid, the last sweep, and a window of samples (L1.1).

    Pure apart from the clock, because building this inside the write is how the reader and the
    writer acquire two different ideas of what a map file is.
    """
    stamp = time.time() if now is None else float(now)
    cell_size_cm = _safe_float(settings.get("cell_size_cm"), DEFAULT_CELL_SIZE_CM)
    if cell_size_cm <= 0:
        cell_size_cm = DEFAULT_CELL_SIZE_CM

    grid_size = settings.get("grid_size")
    if not (isinstance(grid_size, (list, tuple)) and len(grid_size) == 2):
        grid_size = (100, 100)
    max_cells = _safe_int(settings.get("home_map_max_cells"), DEFAULT_MAX_CELLS)

    grid = mapping_state.get("grid")
    raw_cells = grid.get("cells") if isinstance(grid, Mapping) else None
    cells, truncated = _bounded_cells(
        raw_cells if isinstance(raw_cells, Mapping) else {}, max_cells
    )

    # The sweep is what a map is made of; the samples below are only the log around it.
    sweep: dict[str, float] = {}
    last_sweep = mapping_state.get("last_sweep")
    if isinstance(last_sweep, Mapping):
        angles = last_sweep.get("angles")
        if isinstance(angles, Mapping):
            for key, value in angles.items():
                distance = _safe_float(value, 0.0)
                if distance > 0:
                    sweep[str(key)] = distance

    return {
        "version": CURRENT_VERSION,
        "meta": {
            "saved_at": stamp,
            "cell_size_cm": cell_size_cm,
            "grid_size": [_safe_int(grid_size[0], 100), _safe_int(grid_size[1], 100)],
            "home_map_max_cells": max_cells,
            "cells_truncated": truncated,
            "opening_min_width_cm": settings.get("opening_min_width_cm", 60),
            "safe_path_min_width_cm": settings.get("safe_path_min_width_cm", 40),
        },
        "grid": {"cells": cells},
        "sweep": sweep,
        "samples": _windowed_samples(mapping_state.get("samples"), settings, stamp),
    }


def write_document(path: Path, document: Mapping[str, Any]) -> Path:
    """Write the document atomically: a brownout mid-write must not leave half a map behind.

    The temp file sits in the same directory on purpose - `Path.replace` is atomic within one
    filesystem only, and `/tmp` is a different one from `/home/pi` on a Raspberry Pi OS image.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def load_home_map(path: Path) -> HomeMapLoad:
    """Read a map file, reporting problems by name instead of raising (L1.2).

    Every failure path returns a `HomeMapLoad`: a corrupt file degrades to "no map, here is why".
    It never takes the runtime down and is never mistaken for an empty room.
    """
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return HomeMapLoad(None, reason=f"no home map at {target}")
    except OSError as exc:
        return HomeMapLoad(None, problems=(f"cannot read {target}: {exc}",), reason="unreadable")

    try:
        raw = json.loads(text)
    except ValueError as exc:
        return HomeMapLoad(None, problems=(f"not JSON: {exc}",), reason="not JSON")
    if not isinstance(raw, dict):
        return HomeMapLoad(None, problems=("the file is not a JSON object",), reason="wrong shape")

    notes: list[str] = []
    version = _safe_int(raw.get("version"), 0)
    if version > CURRENT_VERSION:
        return HomeMapLoad(
            None,
            problems=(f"written by version {version}; this runtime reads up to {CURRENT_VERSION}",),
            reason="newer format",
        )
    if version <= 0:
        version = 1
        notes.append("no version field: read as the pre-grid format, samples only")

    meta_raw = raw.get("meta")
    if isinstance(meta_raw, Mapping):
        meta = dict(meta_raw)
    else:
        meta = {}
        if meta_raw is not None:
            notes.append("meta is not an object; defaults used")

    grid_raw = raw.get("grid")
    cells_raw = grid_raw.get("cells") if isinstance(grid_raw, Mapping) else None
    if isinstance(cells_raw, Mapping):
        cells, truncated = _bounded_cells(
            cells_raw, _safe_int(meta.get("home_map_max_cells"), DEFAULT_MAX_CELLS)
        )
        if truncated:
            notes.append("the grid was longer than the cap; only the strongest cells were kept")
        elif len(cells_raw) - len(cells) > 0:
            dropped = len(cells_raw) - len(cells)
            notes.append(f"{dropped} grid entries were not cells and were dropped")
    else:
        cells = {}
        if version >= CURRENT_VERSION:
            notes.append("no grid section: this map carries no cells")

    sweep: dict[str, float] = {}
    sweep_raw = raw.get("sweep")
    if isinstance(sweep_raw, Mapping):
        for key, value in sweep_raw.items():
            distance = _safe_float(value, 0.0)
            if distance > 0:
                sweep[str(key)] = distance

    samples_raw = raw.get("samples")
    if isinstance(samples_raw, list):
        samples = tuple(dict(entry) for entry in samples_raw if isinstance(entry, Mapping))
    else:
        samples = ()
        if samples_raw is not None:
            notes.append("samples is not a list; ignored")

    return HomeMapLoad(
        HomeMap(version=version, meta=meta, cells=cells, sweep=sweep, samples=samples),
        notes=tuple(notes),
    )
