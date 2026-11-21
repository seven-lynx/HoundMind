"""Print what a home map file actually contains.

Why this exists: `data/home_map.json` was written every 30 s and read by nobody, so its contents were
an assumption. It held no grid (#286), and a map that holds no grid cannot answer a single navigation
question. This tool reads the file with the same validator the runtime uses (`mapping/home_map.py`) and
shows the answer: the cells, the sweep behind them, the nearest wall the map knows about, and a coarse
picture of it.

Read-only. No HAL, no runtime, no motion — it works on any machine, on any file.

    python -m tools.map_inspect                       # the shipped path, if it exists
    python -m tools.map_inspect data/home_map.json --json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from houndmind_ai.mapping.home_map import (
    HomeMap,
    RoomFrame,
    load_home_map,
    resolve_room_frames,
)
from houndmind_ai.mapping.mapper import nearest_wall

# `src/tools/<name>.py` -> the repository root, so a relative path means what the runtime means.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = "data/home_map.json"


def _resolve(text: str) -> Path:
    path = Path(text)
    return path if path.is_absolute() else REPO_ROOT / path


def _stamp(value: object) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unknown"
    try:
        return datetime.fromtimestamp(float(value), tz=UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    except (OSError, OverflowError, ValueError):
        return "unknown"


def _parse_key(key: str) -> tuple[int, int] | None:
    try:
        ix_text, iy_text = key.split(",", 1)
        return int(ix_text), int(iy_text)
    except (AttributeError, TypeError, ValueError):
        return None


def render(home_map: HomeMap, width: int = 72) -> str:
    """A coarse picture: `#` for a strong cell, `+` for a weak one, `@` for the dog at the origin.

    `ix` is centimetres to the dog's left and `iy` is forward, so the picture is drawn with the nose
    up and the dog's left on the left - the same convention as the web app's map panel.
    """
    points = [pair for pair in (_parse_key(key) for key in home_map.cells) if pair is not None]
    if not points:
        return "(no cells)"

    min_ix = min(pair[0] for pair in points)
    max_ix = max(pair[0] for pair in points)
    min_iy = min(pair[1] for pair in points)
    max_iy = max(pair[1] for pair in points)
    span = max(max_ix - min_ix, max_iy - min_iy, 1)
    step = max(1, -(-span // max(8, width)))  # ceil, so the picture fits the requested width

    strongest = max(home_map.cells.values())
    lines: list[str] = []
    for iy in range(max_iy, min_iy - 1, -step):
        row: list[str] = []
        for ix in range(max_ix - (max_ix - min_ix) % step, min_ix - 1, -step):
            hits = max(
                (home_map.cells.get(f"{x},{y}", 0) for x in range(ix, ix + step) for y in range(iy - step + 1, iy + 1)),
                default=0,
            )
            if ix == 0 and iy == 0:
                row.append("@")
            elif hits <= 0:
                row.append(".")
            elif hits >= strongest * 0.6:
                row.append("#")
            else:
                row.append("+")
        lines.append("".join(row))
    return "\n".join(lines)


def _frame_text(room_id: str, frame: RoomFrame) -> str:
    """One room's place in the home frame, and the joins that put it there (H7).

    The root room is the frame itself; every other room names the room it hangs off and the whole chain
    of joint ids from the root, so a disagreement between a join and the drawing it was made from can
    be traced one join at a time instead of guessed at from two coordinates.
    """
    origin = frame.transform.translate_cm
    where = f"({origin[0]:g}, {origin[1]:g}) cm, {frame.transform.rotation_deg:g} deg"
    if frame.parent is None:
        return f"{room_id} = the home frame, {where}"
    return f"{room_id} = {frame.parent} through {' then '.join(frame.chain)} at {where}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", default=DEFAULT_PATH, help=f"map file (default {DEFAULT_PATH})")
    parser.add_argument("--json", action="store_true", help="print the document as JSON instead of a report")
    parser.add_argument("--width", type=int, default=72, help="picture width in characters (default 72)")
    parser.add_argument("--wall-cm", type=float, default=300.0, help="cap for the nearest-wall query")
    args = parser.parse_args(argv)

    path = _resolve(args.path)
    result = load_home_map(path)

    if result.map is None:
        print(f"file:    {path}")
        print(f"verdict: NOT LOADED - {result.reason or 'unknown reason'}")
        for problem in result.problems:
            print(f"problem: {problem}")
        return 1

    home_map = result.map
    if args.json:
        print(json.dumps(home_map.to_document(), indent=2))
        return 0

    grid = home_map.as_grid()
    wall = nearest_wall(grid, (0.0, 0.0), args.wall_cm, cell_size_cm=home_map.cell_size_cm)
    print(f"file:     {path}")
    print(f"version:  {home_map.version}")
    print(f"saved:    {_stamp(home_map.meta.get('saved_at'))}")
    print(f"cell:     {home_map.cell_size_cm:g} cm   grid {home_map.grid_size[0]}x{home_map.grid_size[1]}")
    print(f"cells:    {home_map.cell_count}")
    print(f"samples:  {len(home_map.samples)}")
    print(f"sweep:    {len(home_map.sweep)} angle(s)")
    objects = [entry for entry in (home_map.sections.get("objects") or []) if isinstance(entry, dict)]
    walls = {entry["wall_id"] for entry in objects if isinstance(entry.get("wall_id"), str)}
    print(f"objects:  {len(objects)}" + (f" on {len(walls)} wall(s)" if walls else ""))
    joints = [entry for entry in (home_map.sections.get("joints") or []) if isinstance(entry, dict)]
    frames = resolve_room_frames(
        joints,
        walls=home_map.sections.get("walls"),
        openings=home_map.sections.get("openings"),
    )
    print(f"joints:   {len(joints)} joint(s); {len(frames.frames)} room(s) placed")
    for room_id, frame in frames.frames.items():
        print(f"frame:    {_frame_text(room_id, frame)}")
    print(
        "wall:     "
        + (f"{wall:.0f} cm (capped at {args.wall_cm:g})" if wall is not None else "none known in range")
    )
    if home_map.meta.get("cells_truncated"):
        print("note:     the grid was capped when it was written; the weakest cells are not here")
    for note in result.notes:
        print(f"note:     {note}")
    print()
    print(render(home_map, width=max(8, args.width)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
