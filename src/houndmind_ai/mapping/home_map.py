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
loses the one map they have. Version 3 adds no field to the scan's own sections: it adds the `objects`
and `joints` sections a person draws (H3), and a document written before either key existed reads both
as an empty list.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "CURRENT_VERSION",
    "DEFAULT_CELL_SIZE_CM",
    "DEFAULT_MAX_CELLS",
    "HomeMap",
    "HomeMapLoad",
    "OBJECT_KINDS",
    "USER_SECTIONS",
    "build_document",
    "document_point_to_runtime",
    "load_home_map",
    "map_path",
    "runtime_point_to_document",
    "scale_source_for",
    "validate_document",
    "write_document",
]

logger = logging.getLogger(__name__)

CURRENT_VERSION = 3
DEFAULT_CELL_SIZE_CM = 10.0
DEFAULT_MAX_CELLS = 20000

# The sections a human owns. The scan writes the cells, the sweep and the samples; these arrive from
# an editor and outlive every save, so a 30 s snapshot never erases a wall someone drew (M1).
USER_SECTIONS: tuple[str, ...] = (
    "walls",
    "openings",
    "rooms",
    "surfaces",
    "places",
    "objects",
    "joints",
    "dog",
)

# A furniture kind is a closed vocabulary (H3): `kind` is what a planner will branch on, so a spelling
# nothing has agreed on is a refused document rather than a word nobody reads.
OBJECT_KINDS: tuple[str, ...] = ("cabinet", "counter", "sofa", "table", "shelf", "other")

# The sections whose absence means "empty" rather than "not written". A document from before v3 has no
# `objects` key at all, and the console reads the same absence as an empty list (H3).
EMPTY_WHEN_ABSENT: tuple[str, ...] = ("objects", "joints")


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


def document_point_to_runtime(point: Any) -> tuple[float, float]:
    """A document point `[x = left, y = forward]` as the runtime's `(forward_cm, left_cm)`.

    The two frames are both correct and both called `x`/`y`, which is the defect (#347). A **document**
    point is written for a person reading a plan: `x` runs left and `y` runs forward
    (`CONTROL_API.md`, the console's canvas). The **runtime** speaks `(forward_cm, left_cm)`: the pose
    (`navigation/odometry.py`), the planner (`mapping/planner.py::_index_of`) and the grid
    (`mapping/mapper.py::cell_centre_cm`) all use it.

    Nothing was wrong while the two never met. They meet in the console, which draws the document and
    will plot the live pose, and this pair of functions is the only place the swap is written — so a
    reader who gets it wrong gets it wrong once, here, where `tests/test_map_frames.py` can see it.
    """
    left, forward = _point2(point)
    return forward, left


def runtime_point_to_document(point: Any) -> tuple[float, float]:
    """The inverse of `document_point_to_runtime`: `(forward_cm, left_cm)` as `[x = left, y = forward]`."""
    forward, left = _point2(point)
    return left, forward


def _point2(point: Any) -> tuple[float, float]:
    """Two finite floats from a `[x, y]` pair, zero-filled rather than raised on.

    A polygon vertex typed by hand can be short, a string or `null`; a map that raised on one would
    make the whole document unreadable, and a vertex at the origin is a shape someone can see and fix.
    """
    if isinstance(point, (str, bytes)) or not isinstance(point, Sequence):
        return 0.0, 0.0
    values = list(point)[:2]
    while len(values) < 2:
        values.append(0.0)
    return _safe_float(values[0], 0.0), _safe_float(values[1], 0.0)


def scale_source_for(rooms: Any) -> str:
    """Whether the document carries a real dimension: `"user"` or `"unmeasured"` (H2).

    A room's size lives beside its polygon as `size_cm: {width_cm, depth_cm}` — the two numbers a
    person typed when they drew it, not something the dog inferred. Both have to be **positive**,
    because half a rectangle and a zero are how an unmeasured room would otherwise claim a scale,
    and H4's discovery run is the only thing allowed to turn a guess into a measurement.

    `validate_document` keeps section entries verbatim, so this is the only place the shape is read.
    It is a claim about the *document*, though, and a document can hold one measured room beside an
    unmeasured one: a caller that needs the per-room truth reads `size_cm` itself, which is what the
    console's label does.
    """
    rooms_raw = rooms if isinstance(rooms, Sequence) else ()
    for room in rooms_raw:
        if not isinstance(room, Mapping):
            continue
        size = room.get("size_cm")
        if not isinstance(size, Mapping):
            continue
        width = _safe_float(size.get("width_cm"), 0.0)
        depth = _safe_float(size.get("depth_cm"), 0.0)
        if width > 0 and depth > 0:
            return "user"
    return "unmeasured"


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
    # The user's own sections (walls, rooms, ...), carried verbatim: walls and openings gained their
    # writer in M3 and rooms and surfaces in M4, and a document that drops what it just read is not one
    # a human can edit.
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
    # `meta` above is rebuilt from the settings, so the user's own dimension claim is the one key
    # that has to be carried forward by hand — without it the next 30 s snapshot erases what a
    # `PUT /map` stamped (H2). An absent claim stays absent: defaulting it here would let the scan
    # write a measurement nobody took.
    scale_source = previous_meta.get("scale_source")
    if isinstance(scale_source, str) and scale_source:
        document["meta"]["scale_source"] = scale_source
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
        # `utf-8-sig` is a superset of `utf-8`: a file written by a Windows editor that adds a
        # byte-order mark loads instead of failing `json.loads` with "Unexpected UTF-8 BOM".
        # A backup that a desktop tool has touched is the normal case for user data (#361).
        text = target.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return HomeMapLoad(None, reason=f"no home map at {target}")
    except OSError as exc:
        return HomeMapLoad(None, problems=(f"cannot read {target}: {exc}",), reason="unreadable")

    try:
        raw = json.loads(text)
    except ValueError as exc:
        return HomeMapLoad(None, problems=(f"not JSON: {exc}",), reason="not JSON")

    return validate_document(raw)


# A rectangle ending half a centimetre past its wall is a float artefact rather than a drawing error:
# the console snaps to 5 cm, so the boundary only has to absorb the arithmetic.
_WALL_FIT_TOLERANCE_CM = 0.5


def _point(value: Any) -> tuple[float, float] | None:
    """One document point, `[x, y]` in cm, or None when the pair is not two numbers."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    x = _safe_float(value[0], math.nan)
    y = _safe_float(value[1], math.nan)
    if math.isnan(x) or math.isnan(y):
        return None
    return (x, y)


def _wall_lengths(walls: Any) -> dict[str, float | None]:
    """Every drawn wall's length in cm, keyed by id; None when its endpoints cannot be read."""
    lengths: dict[str, float | None] = {}
    if not isinstance(walls, list):
        return lengths
    for wall in walls:
        if not isinstance(wall, Mapping):
            continue
        wall_id = wall.get("id")
        if not isinstance(wall_id, str) or not wall_id:
            continue
        a = _point(wall.get("a"))
        b = _point(wall.get("b"))
        lengths[wall_id] = math.dist(a, b) if a is not None and b is not None else None
    return lengths


def _object_problems(objects: Sequence[Any], walls: Any) -> list[str]:
    """An object is a rectangle standing against a wall, so it has to name that wall and fit on it (H3).

    A clamp would draw furniture through the next room and hide the mistake in the drawing, so every
    refusal here is a `problems[]` entry that names the number that did not work.
    """
    lengths = _wall_lengths(walls)
    problems: list[str] = []
    for index, entry in enumerate(objects):
        label = f"objects[{index}]"
        if not isinstance(entry, Mapping):
            problems.append(f"{label} is not an object")
            continue
        kind = entry.get("kind")
        if kind not in OBJECT_KINDS:
            problems.append(f"{label} has kind {kind!r}; use one of {', '.join(OBJECT_KINDS)}")
        wall_id = entry.get("wall_id")
        if not isinstance(wall_id, str) or not wall_id:
            problems.append(f"{label} has no wall_id")
            continue
        if wall_id not in lengths:
            problems.append(f"{label} stands against {wall_id}, which no drawn wall answers")
            continue
        length = lengths[wall_id]
        if length is None:
            problems.append(f"{label} stands against {wall_id}, whose endpoints are not two points")
            continue
        start = _safe_float(entry.get("start_cm"), -1.0)
        width = _safe_float(entry.get("width_cm"), -1.0)
        depth = _safe_float(entry.get("depth_cm"), -1.0)
        if start < 0 or width <= 0 or depth <= 0:
            problems.append(f"{label} needs start_cm at or above 0 and a positive width_cm and depth_cm")
            continue
        if start + width > length + _WALL_FIT_TOLERANCE_CM:
            problems.append(
                f"{label} runs {start + width:g} cm along {wall_id}, which is {length:g} cm long"
            )
    return problems


def validate_document(raw: Any) -> HomeMapLoad:
    """Judge one parsed document: the single validator, for a file and for a request body (M1).

    `cells` is read from `grid.cells` (the file shape) or from `cells` (the client shape that
    `GET /map` publishes and a `PUT /map` body carries) — the same map under two spellings, and
    accepting both is what keeps a round-trip from arriving with no cells.

    The user's sections are checked for shape only: a section of the wrong type is a problem, not a
    note, because silently dropping a room a human drew is exactly the failure the validity rules
    exist to prevent. Each segment that writes one (M3-M5) tightens its entries here. `objects` is the
    first held to geometry (H3): a rectangle that runs past its wall, or names a wall no drawing
    answers, is a problem naming the wall's length rather than a clamp.
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
            # `objects` and `joints` arrived in v3: a document written before them has no key at all,
            # and that absence means empty rather than "not written" (H3).
            if name in EMPTY_WHEN_ABSENT:
                sections[name] = []
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
    if "objects" in sections:
        problems.extend(_object_problems(sections["objects"], sections.get("walls")))
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
