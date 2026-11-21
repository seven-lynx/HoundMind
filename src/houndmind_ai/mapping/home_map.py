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
    "JOINT_DISAGREEMENT_TOLERANCE",
    "OBJECT_KINDS",
    "RoomFrame",
    "RoomFrames",
    "RoomTransform",
    "USER_SECTIONS",
    "build_document",
    "document_point_to_runtime",
    "load_home_map",
    "map_path",
    "resolve_room_frames",
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

#: How far two drawings of one shared wall may differ before a join reports it (H7). A join is a
#: proposal the user confirmed, not an edit: five percent is the difference a pencil and a length of
#: string make, and past it the two rooms disagree about a centimetre count somebody typed. It is a
#: `notes` entry at any size, because the drawings are the user's and a join never rewrites one.
JOINT_DISAGREEMENT_TOLERANCE = 0.05


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


@dataclass(frozen=True)
class RoomTransform:
    """One room's drawing placed in another frame: where its origin sits, and which way it is turned.

    `translate_cm` is a **document** point (`x` runs left, `y` runs forward) from the parent's origin to
    this room's origin, and `rotation_deg` turns the room about its own origin, positive from +x toward
    +y — a room drawn facing left comes to face forward. Both numbers are document terms, so nothing
    here swaps an axis: a caller holding a runtime pair converts once, through
    `runtime_point_to_document`, and `RoomFrames.to_runtime` is the only place that happens (#347).
    """

    translate_cm: tuple[float, float] = (0.0, 0.0)
    rotation_deg: float = 0.0

    def apply(self, point: Any) -> tuple[float, float]:
        """Where a point of this room's own drawing lands in the parent frame."""
        x, y = _point2(point)
        if self.rotation_deg:
            theta = math.radians(self.rotation_deg)
            cos, sin = math.cos(theta), math.sin(theta)
            x, y = x * cos - y * sin, x * sin + y * cos
        dx, dy = self.translate_cm
        return x + dx, y + dy

    def then(self, child: RoomTransform) -> RoomTransform:
        """`self` followed by `child`: what a chain of two joins composes to."""
        return RoomTransform(
            translate_cm=self.apply(child.translate_cm),
            rotation_deg=self.rotation_deg + child.rotation_deg,
        )


@dataclass(frozen=True)
class RoomFrame:
    """One room's placement in the home frame, and the joins that got it there.

    `chain` is the joint ids walked from the root, in order, so a caller can name the join that put a
    room where it is — `map_inspect` prints it, and H8's console draws it. A root room has no parent
    and an empty chain: its own drawing *is* the home frame.
    """

    room_id: str
    transform: RoomTransform
    parent: str | None = None
    chain: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoomFrames:
    """Every room the joins reach, all of them placed in one home frame (H7).

    The root is the room no join places. That is the only honest origin to pick, because the whole
    point of a join is that neither drawing knew about the other: whichever room was drawn first is the
    one whose centimetres the rest inherit. A room no join mentions is not here at all — there is
    nothing to place it against, and inventing a frame for a drawing the user already owns would be a
    second opinion about it.
    """

    frames: Mapping[str, RoomFrame] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def frame_for(self, room_id: Any) -> RoomFrame | None:
        return self.frames.get(room_id) if isinstance(room_id, str) else None

    def chain_for(self, room_id: Any) -> tuple[str, ...]:
        """The joint ids between the home frame and `room_id`, or nothing when it is not placed."""
        frame = self.frame_for(room_id)
        return frame.chain if frame is not None else ()

    def to_runtime(self, room_id: Any, point: Any) -> tuple[float, float] | None:
        """A point of `room_id`'s drawing, as `(forward_cm, left_cm)` in the home frame.

        The swap happens once, in `document_point_to_runtime` and `runtime_point_to_document`; the
        transform itself is document arithmetic. That is #347's fix kept whole — a second hand-written
        swap inside the join code is exactly how the mirrored dog came back.
        """
        frame = self.frame_for(room_id)
        if frame is None:
            return None
        return document_point_to_runtime(frame.transform.apply(runtime_point_to_document(point)))


@dataclass(frozen=True)
class _Joint:
    """One joint as the chain can walk it: two named rooms, two named openings, one placement."""

    name: str
    a_room: str
    b_room: str
    a_opening: str
    b_opening: str
    transform: RoomTransform


def _section_entries(section: Any) -> list[Mapping[str, Any]]:
    """The object entries of a user section, or nothing. A section nobody wrote is not an error."""
    if isinstance(section, (str, bytes)) or not isinstance(section, Sequence):
        return []
    return [entry for entry in section if isinstance(entry, Mapping)]


def _joint_entries(joints: Any) -> list[_Joint]:
    """The joints that can be walked, labelled the way `_joint_problems` labels them.

    An entry that is not an object, does not name two rooms, names a room as itself, or carries no
    readable transform is `_joint_problems`' business: it is refused by name when the document is
    judged, and simply not walked here, so a chain is never built out of a join the document cannot
    mean.
    """
    if isinstance(joints, (str, bytes)) or not isinstance(joints, Sequence):
        return []
    parsed: list[_Joint] = []
    for index, entry in enumerate(joints):
        if not isinstance(entry, Mapping):
            continue
        a_room = entry.get("a_room")
        b_room = entry.get("b_room")
        transform = _transform_from(entry.get("transform"))
        if not isinstance(a_room, str) or not a_room or not isinstance(b_room, str) or not b_room:
            continue
        if a_room == b_room or transform is None:
            continue
        joint_id = entry.get("id")
        a_opening = entry.get("a_opening")
        b_opening = entry.get("b_opening")
        parsed.append(
            _Joint(
                name=joint_id if isinstance(joint_id, str) and joint_id else f"joints[{index}]",
                a_room=a_room,
                b_room=b_room,
                a_opening=a_opening if isinstance(a_opening, str) else "",
                b_opening=b_opening if isinstance(b_opening, str) else "",
                transform=transform,
            )
        )
    return parsed


def resolve_room_frames(joints: Any, *, walls: Any = None, openings: Any = None) -> RoomFrames:
    """Place every room a set of joints reaches into one home frame (H7).

    A joint is `{id, a_room, a_opening, b_room, b_opening, transform}`, and its `transform` places
    `b_room`'s drawing in `a_room`'s frame — so `a_room` is the parent. The root of a chain is the room
    that appears as `a_room` and never as `b_room`; walking outward from it composes the transforms,
    which is how a room drawn on its own ends up in the same centimetres as the one next door.

    Two joins that place the same room, and a set of joins that closes a loop with no room to start
    from, are **reported**: the first join stands and no drawing is moved. `notes` also carries a join
    whose two drawings disagree about the length of the wall the doorway is cut into by more than
    `JOINT_DISAGREEMENT_TOLERANCE` — a report, never a rewrite, for the same reason the scale audit
    refuses: the map is the user's.

    `walls` and `openings` are the document sections, read only to measure that wall; leaving them out
    simply means no join is measured. Nothing here raises on a document nobody validated.
    """
    parsed = _joint_entries(joints)
    notes: list[str] = []
    placements: dict[str, tuple[str, str, RoomTransform]] = {}
    rooms: list[str] = []
    for joint in parsed:
        for room in (joint.a_room, joint.b_room):
            if room not in rooms:
                rooms.append(room)
        if joint.b_room in placements:
            notes.append(
                f"{joint.name} also places {joint.b_room}; {placements[joint.b_room][1]} was walked "
                "instead, and both joins are kept as drawn"
            )
            continue
        placements[joint.b_room] = (joint.a_room, joint.name, joint.transform)

    frames: dict[str, RoomFrame] = {
        room: RoomFrame(room, RoomTransform()) for room in rooms if room not in placements
    }
    pending = list(frames)
    while pending:
        room = pending.pop(0)
        base = frames[room]
        for child, (parent, name, transform) in placements.items():
            if parent != room or child in frames:
                continue
            frames[child] = RoomFrame(
                child, base.transform.then(transform), room, base.chain + (name,)
            )
            pending.append(child)

    stranded = [room for room in rooms if room not in frames]
    if stranded:
        notes.append(
            "the joins for "
            + ", ".join(stranded)
            + " close a loop with no room to start from; every room in it keeps its own drawing"
        )
        for room in stranded:
            frames[room] = RoomFrame(room, RoomTransform())

    notes.extend(_joint_notes(parsed, walls, openings))
    return RoomFrames(frames=frames, notes=tuple(notes))


def _joint_notes(joints: Sequence[_Joint], walls: Any, openings: Any) -> list[str]:
    """Where two drawings of one doorway disagree about the wall it was cut into (H7).

    Both lengths are the user's, so this reports the pair and moves neither: a join that quietly
    rescaled a room would make the map disagree with the room the dog is standing in. A doorway whose
    wall cannot be found in one of the drawings is not measured at all rather than measured wrongly.
    """
    segments = _wall_segments(walls)
    by_id = {
        entry["id"]: entry
        for entry in _section_entries(openings)
        if isinstance(entry.get("id"), str) and entry.get("id")
    }
    notes: list[str] = []
    for joint in joints:
        here = _opening_wall(by_id.get(joint.a_opening), segments)
        there = _opening_wall(by_id.get(joint.b_opening), segments)
        if here is None or there is None:
            continue
        a_wall, a_length = here
        b_wall, b_length = there
        if a_length <= 0 or b_length <= 0:
            continue
        apart = abs(a_length - b_length) / max(a_length, b_length)
        if apart <= JOINT_DISAGREEMENT_TOLERANCE:
            continue
        notes.append(
            f"{joint.name} joins two drawings that disagree about the shared wall: {a_length:g} cm "
            f"in {joint.a_room} ({a_wall}) against {b_length:g} cm in {joint.b_room} ({b_wall}), "
            f"{apart:.0%} apart — both were kept as drawn"
        )
    return notes


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


def _wall_segments(walls: Any) -> dict[str, tuple[tuple[float, float], tuple[float, float]] | None]:
    """Every drawn wall's endpoints, keyed by id; None when its endpoints cannot be read.

    One parser for the walls section: the length an object has to fit inside and the wall a join is
    measured against are the same two points, and two parsers would eventually disagree about which
    entries are walls.
    """
    segments: dict[str, tuple[tuple[float, float], tuple[float, float]] | None] = {}
    for wall in _section_entries(walls):
        wall_id = wall.get("id")
        if not isinstance(wall_id, str) or not wall_id:
            continue
        a = _point(wall.get("a"))
        b = _point(wall.get("b"))
        segments[wall_id] = (a, b) if a is not None and b is not None else None
    return segments


def _wall_lengths(walls: Any) -> dict[str, float | None]:
    """Every drawn wall's length in cm, keyed by id; None when its endpoints cannot be read."""
    return {
        wall_id: math.dist(segment[0], segment[1]) if segment is not None else None
        for wall_id, segment in _wall_segments(walls).items()
    }


def _distance_to_segment_cm(
    point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """How far a point lies from the segment `a`-`b`, projected and clamped to its ends.

    `mapping/rooms.py::_distance_to_segment` does the same projection for the keep-out predicate, but
    it is private there and a join is not a keep-out question, so this is a short copy rather than a
    second meaning given to that module's geometry.
    """
    (px, py), (ax, ay), (bx, by) = point, a, b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _opening_wall(
    opening: Any, segments: Mapping[str, tuple[tuple[float, float], tuple[float, float]] | None]
) -> tuple[str, float] | None:
    """The drawn wall a doorway was cut into, and its length, or None when no wall answers.

    The console cuts an opening *inside* one wall (`map.js::cutOpening`), so both of its ends sit on a
    single drawn segment: that segment is the shared wall a join is measured against. A doorway whose
    wall cannot be found is not measured, because a join that picked the nearest wall would report a
    disagreement between two rooms that share no wall at all.
    """
    if not isinstance(opening, Mapping):
        return None
    a = _point(opening.get("a"))
    b = _point(opening.get("b"))
    if a is None or b is None:
        return None
    for wall_id, segment in segments.items():
        if segment is None:
            continue
        start, end = segment
        if (
            _distance_to_segment_cm(a, start, end) <= _WALL_FIT_TOLERANCE_CM
            and _distance_to_segment_cm(b, start, end) <= _WALL_FIT_TOLERANCE_CM
        ):
            return wall_id, math.dist(start, end)
    return None


def _transform_from(raw: Any) -> RoomTransform | None:
    """A joint's `transform`, or None when it does not say where the second room sits.

    `translate_cm` is required: a join with no offset is a join nobody drew. A missing `rotation_deg`
    is a translation-only join and reads as zero, which is what two rooms drawn side by side mean — but
    a turn that is present and unreadable is None rather than zero, because guessing it would move a
    room nobody asked to move.
    """
    if not isinstance(raw, Mapping):
        return None
    translate = raw.get("translate_cm")
    if not isinstance(translate, Sequence) or isinstance(translate, (str, bytes)) or len(translate) != 2:
        return None
    dx = _safe_float(translate[0], math.nan)
    dy = _safe_float(translate[1], math.nan)
    degrees = _safe_float(raw.get("rotation_deg", 0.0), math.nan)
    if math.isnan(dx) or math.isnan(dy) or math.isnan(degrees):
        return None
    return RoomTransform((dx, dy), degrees)



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


def _reference_problem(label: str, field_name: str, value: Any, known: Any, what: str) -> str | None:
    """The problem with one reference a joint makes, or None when it resolves."""
    if not isinstance(value, str) or not value:
        return f"{label} has no {field_name}"
    if value not in known:
        return f"{label} names {field_name} {value!r}, which no {what} answers"
    return None


def _joint_problems(joints: Sequence[Any], openings: Any, rooms: Any) -> list[str]:
    """A join is two drawn doorways and the placement of one room in the other (H7).

    Every refusal names the field and the id that did not work: a doorway no drawing answers, a room no
    polygon answers, a room joined to itself, a transform that does not say where the second room sits.
    Nothing here compares lengths. Two rooms that disagree about the shared wall are a `notes` entry in
    `resolve_room_frames`, because the drawings are the user's, and a join that refused them would
    refuse the only map they have — the same reason the scale audit reports rather than rescales.
    """
    opening_ids = {
        entry.get("id") for entry in _section_entries(openings) if isinstance(entry.get("id"), str)
    }
    room_ids = {
        entry.get("id") for entry in _section_entries(rooms) if isinstance(entry.get("id"), str)
    }
    problems: list[str] = []
    for index, entry in enumerate(joints):
        label = f"joints[{index}]"
        if not isinstance(entry, Mapping):
            problems.append(f"{label} is not an object")
            continue
        for field_name in ("a_room", "b_room"):
            problem = _reference_problem(
                label, field_name, entry.get(field_name), room_ids, "drawn room"
            )
            if problem is not None:
                problems.append(problem)
        for field_name in ("a_opening", "b_opening"):
            problem = _reference_problem(
                label, field_name, entry.get(field_name), opening_ids, "drawn opening"
            )
            if problem is not None:
                problems.append(problem)
        a_room = entry.get("a_room")
        b_room = entry.get("b_room")
        if isinstance(a_room, str) and a_room and a_room == b_room:
            problems.append(f"{label} joins {a_room} to itself")
        if _transform_from(entry.get("transform")) is None:
            problems.append(
                f"{label} has no readable transform; a join needs translate_cm as two numbers "
                "and, if the room is turned, a numeric rotation_deg"
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
    answers, is a problem naming the wall's length rather than a clamp. `joints` follows (H7): a join
    whose room or doorway no drawing answers is a problem naming it, while two drawings that disagree
    about the shared wall are a note — the pair of lengths is reported and neither is moved.
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
    if "joints" in sections:
        problems.extend(
            _joint_problems(sections["joints"], sections.get("openings"), sections.get("rooms"))
        )
    if problems:
        return HomeMapLoad(None, problems=tuple(problems), reason="wrong section")

    # The joins are measured only on a document that loads — a refusal above already says why it did
    # not, and a disagreement between two drawings is a note, never a second reason to refuse one (H7).
    notes.extend(
        resolve_room_frames(
            sections.get("joints") or [],
            walls=sections.get("walls"),
            openings=sections.get("openings"),
        ).notes
    )

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
