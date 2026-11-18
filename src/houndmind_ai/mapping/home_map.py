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
    "USER_SECTIONS",
    "build_document",
    "load_home_map",
    "map_path",
    "validate_document",
    "write_document",
]

logger = logging.getLogger(__name__)

CURRENT_VERSION = 2
DEFAULT_CELL_SIZE_CM = 10.0
DEFAULT_MAX_CELLS = 20000

# The sections a human owns. The scan writes the cells, the sweep and the samples; these arrive from
# an editor and outlive every save, so a 30 s snapshot never erases a wall someone drew (M1).
USER_SECTIONS: tuple[str, ...] = ("walls", "openings", "rooms", "surfaces", "places", "dog")


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


def map_path(text: Any, default: str = "data/home_map.json") -> Path:
    """Resolve a configured map path against the repository root, not the working directory.

    A relative path is the shipped default (`data/home_map.json`) and the service does not run from
    the repo root, so resolving against the cwd would put the map where nobody looks for it. The
    rule lives here, beside the format, because the mapper, the loader and the control plane all
    have to agree on which file they mean.
    """
    raw = text if isinstance(text, str) and text.strip() else default
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    return path


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
    # The user's own sections (walls, rooms, ...), carried verbatim. None of them has a writer until
    # M3-M5, but a document that drops what it just read is not one a human can edit.
    sections: Mapping[str, Any] = field(default_factory=dict)

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    @property
    def rev(self) -> int:
        """The edit generation a `PUT /map` has to match. A scan save never bumps it."""
        return _safe_int(self.meta.get("rev"), 0)

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
        """The **client** shape: `cells` flat, the sample window as a count (M1).

        This is what `GET /map` publishes and what a `PUT /map` body carries back. The file nests
        the cells under `grid` and keeps the sample log; a client never receives that log, so it
        cannot send it either - which is why the two shapes are methods here rather than one dict.
        """
        document: dict[str, Any] = {
            "version": self.version,
            "meta": dict(self.meta),
            "cells": dict(self.cells),
            "sweep": dict(self.sweep),
            "samples": len(self.samples),
        }
        for name in USER_SECTIONS:
            if name in self.sections:
                document[name] = self.sections[name]
        return document

    def to_file_document(self) -> dict[str, Any]:
        """The **file** shape `write_document` writes: `grid.cells` nested, the sample log intact.

        The differences from `to_document()` are where the cells live and whether `samples` is the
        list or its count. Both spellings live in this class on purpose: a save that wrote the
        client shape would produce a file the next start reads as an empty map.
        """
        document: dict[str, Any] = {
            "version": self.version,
            "meta": dict(self.meta),
            "grid": {"cells": dict(self.cells)},
            "sweep": dict(self.sweep),
            "samples": [dict(entry) for entry in self.samples],
        }
        for name in USER_SECTIONS:
            if name in self.sections:
                document[name] = self.sections[name]
        return document


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
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The document to write: the grid, the last sweep, and a window of samples (L1.1).

    Pure apart from the clock, because building this inside the write is how the reader and the
    writer acquire two different ideas of what a map file is.

    `previous` is the document this runtime already knows. A scan save takes the edit generation
    (`meta.rev`) and the user's own sections from it, so a snapshot every 30 s never erases a wall
    a human drew and never invalidates a client's in-flight edit (M1). The scan owns the cells; the
    user owns everything else.
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

    previous_meta_raw = previous.get("meta") if isinstance(previous, Mapping) else None
    previous_meta = previous_meta_raw if isinstance(previous_meta_raw, Mapping) else {}

    document: dict[str, Any] = {
        "version": CURRENT_VERSION,
        "meta": {
            "rev": _safe_int(previous_meta.get("rev"), 0),
            "created_at": _safe_float(previous_meta.get("created_at"), stamp),
            "saved_at": stamp,
            "updated_at": stamp,
            "source": "scan",
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
    for name in USER_SECTIONS:
        if isinstance(previous, Mapping) and name in previous:
            document[name] = previous[name]
    return document


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
    It never takes the runtime down and is never mistaken for an empty room. The judgement itself
    is `validate_document`, so a `PUT /map` body and a file are held to the same rules.
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

    return validate_document(raw)


def validate_document(raw: Any) -> HomeMapLoad:
    """Judge one parsed document: the single validator, for a file and for a request body (M1).

    `cells` is read from `grid.cells` (the file shape) or from `cells` (the client shape that
    `GET /map` publishes and a `PUT /map` body carries) — the same map under two spellings, and
    accepting both is what keeps a round-trip from arriving with no cells.

    The user's sections are checked for shape only: a section of the wrong type is a problem, not a
    note, because silently dropping a room a human drew is exactly the failure the validity rules
    exist to prevent. Each segment that writes one (M3-M5) tightens its entries here.
    """
    if not isinstance(raw, Mapping):
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
    cells_raw = grid_raw.get("cells") if isinstance(grid_raw, Mapping) else raw.get("cells")
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

    sections: dict[str, Any] = {}
    problems: list[str] = []
    for name in USER_SECTIONS:
        if name not in raw:
            continue
        value = raw[name]
        if name == "dog":
            if isinstance(value, Mapping):
                sections[name] = dict(value)
            else:
                problems.append(f"{name} must be an object, not {type(value).__name__}")
            continue
        if isinstance(value, list) and all(isinstance(entry, Mapping) for entry in value):
            sections[name] = [dict(entry) for entry in value]
        else:
            problems.append(f"{name} must be a list of objects")
    if problems:
        return HomeMapLoad(None, problems=tuple(problems), reason="wrong section")

    return HomeMapLoad(
        HomeMap(
            version=version,
            meta=meta,
            cells=cells,
            sweep=sweep,
            samples=samples,
            sections=sections,
        ),
        notes=tuple(notes),
    )
