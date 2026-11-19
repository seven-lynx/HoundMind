"""Route a walk across the map the dog built (#305).

A route is a list of waypoints in centimetres, each carrying the clearance the planner believed it
had. It is a pure function over `(cells, start_cm, goal_cm, settings)`: no context, no HAL, no
mapper instance, so a synthetic grid is enough to test it.

Two rules shape it.

1. **Occupancy is evidence, not terrain.** The mapper records *hits*, never free space
   (`mapping/mapper.py::_ingest_into_grid`), so a cell below the threshold is "not known to be
   blocked" rather than "known clear". A route over unknown ground is a plan the reactive navigator
   still has to survive, and `clearance_cm` says how much room the plan believes it has.
2. **The index is not the coordinate.** Cells are keyed `"ix,iy"` where `ix` counts the *left* axis
   and `iy` the *forward* one. A planner point is `(forward_cm, left_cm)` — the runtime's own order,
   the same one `mapping/mapper.py::cell_centre_cm` returns — so `forward_cm = iy * cell` and
   `left_cm = ix * cell`. Reading them the other way round yields a route that is transposed — a
   valid-looking walk into the wrong room — which is why the mapping is inverted in exactly one place
   here and pinned by a test.
3. **A region is a plan, not an interlock (H5).** `region` confines a route to the room a run is held
   in; `sealed_openings` refuse a doorway the user is not finished with, so the door is still open and
   the route simply does not use it. Both come back as named refusals, which keeps `act/gateway.py`
   and the interlock ignorant of geometry: a region is user data, and a drawing that is wrong must not
   become a safety device. The hold is directional too — a walk that *starts* outside the region is
   planned unconstrained, because a dog outside has to be able to plan its way back in.

A **document** point is the other order, on purpose: `mapping/home_map.py` stores `[x = left,
y = forward]`, because that is what a person tracing a floor plan reads. The two meet only where a
console draws both, and `mapping/home_map.py::document_point_to_runtime` is the one written swap
(#347) — never a second one here.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from houndmind_ai.mapping.rooms import point_in_polygon, polygon_points

__all__ = ["RoutePlan", "Waypoint", "plan_route"]

#: The mapper's default cell. Duplicated as a fallback only: `settings.mapping.cell_size_cm` wins.
CELL_CM = 10.0
#: Hits at or above this make a cell an obstacle. One echo is noise; two in the same cell is a thing.
OCCUPIED_HITS = 2.0
#: How many cells of room a waypoint would like. Fewer than this is penalised, not forbidden: a
#: doorway is narrow by definition, and refusing every narrow cell is a planner that cannot leave a
#: room.
CLEARANCE_CELLS = 2.0
#: Weight on the clearance penalty in the A* step cost. 0 is a shortest path with no regard for room.
CLEARANCE_WEIGHT = 2.0


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _grid_size(settings: dict) -> tuple[int, int]:
    """`grid_size` as two ints, or the mapper's own default: 100 cells at 10 cm is a 10 m square."""
    raw = settings.get("grid_size")
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return int(raw[0]), int(raw[1])
        except (TypeError, ValueError):
            pass
    return 100, 100


@dataclass(frozen=True)
class Waypoint:
    """One place to walk to, and the room the plan believed it had there."""

    x_cm: float
    y_cm: float
    clearance_cm: float | None

    def to_dict(self) -> dict[str, object]:
        return {
            "x_cm": round(self.x_cm, 1),
            "y_cm": round(self.y_cm, 1),
            "clearance_cm": None if self.clearance_cm is None else round(self.clearance_cm, 1),
        }


@dataclass(frozen=True)
class RoutePlan:
    """A route, or a refusal that names itself.

    `refusal` is one of `no_path`, `goal_blocked`, `start_unknown`, `goal_outside_region`,
    `route_leaves_region` — never prose a consumer has to parse — and `detail` is the sentence a person
    reads in a log.
    """

    waypoints: tuple[Waypoint, ...] = ()
    refusal: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None and bool(self.waypoints)

    def to_dict(self) -> dict[str, object]:
        return {
            "valid": self.ok,
            "refusal": self.refusal,
            "detail": self.detail,
            "waypoints": [waypoint.to_dict() for waypoint in self.waypoints],
        }


def _cells_by_index(cells: Any) -> dict[tuple[int, int], float]:
    """`{"ix,iy": hits}` as `{(ix, iy): hits}`, skipping anything that is not a cell."""
    found: dict[tuple[int, int], float] = {}
    if not isinstance(cells, dict):
        return found
    for key, raw in cells.items():
        try:
            ix_text, iy_text = str(key).split(",", 1)
            found[(int(ix_text), int(iy_text))] = _safe_float(raw, 0.0)
        except (ValueError, TypeError):
            continue
    return found


def _index_of(point_cm: tuple[float, float], cell: float) -> tuple[int, int]:
    """The cell a `(forward_cm, left_cm)` point falls in, as the mapper's `(ix = left, iy = forward)`."""
    forward_cm, left_cm = point_cm
    return int(round(left_cm / cell)), int(round(forward_cm / cell))


def _centre_of(index: tuple[int, int], cell: float) -> tuple[float, float]:
    """The inverse of `_index_of`: the `(forward_cm, left_cm)` a cell sits at."""
    ix, iy = index
    return iy * cell, ix * cell


def _in_bounds(index: tuple[int, int], half_x: int, half_y: int) -> bool:
    ix, iy = index
    return abs(ix) <= half_x and abs(iy) <= half_y


def _clearance_cm(
    point_cm: tuple[float, float], occupied: set[tuple[int, int]], cell: float
) -> float | None:
    """Distance to the nearest occupied cell centre, less half a cell; `None` if nothing is mapped."""
    if not occupied:
        return None
    x_cm, y_cm = point_cm
    nearest = min(
        math.hypot(x_cm - _centre_of(index, cell)[0], y_cm - _centre_of(index, cell)[1])
        for index in occupied
    )
    return max(0.0, nearest - cell / 2.0)


def _step_cost(
    index: tuple[int, int],
    occupied: set[tuple[int, int]],
    cell: float,
    clearance_cells: float,
    weight: float,
) -> float:
    """One cell entered: a step, plus a penalty for having less room than the planner would like."""
    if weight <= 0.0 or clearance_cells <= 0.0:
        return 1.0
    clearance = _clearance_cm(_centre_of(index, cell), occupied, cell) or 0.0
    shortfall = max(0.0, (clearance_cells * cell - clearance) / (clearance_cells * cell))
    return 1.0 + weight * shortfall



def _segment(value: Any) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """A sealed opening's two ends as `(forward_cm, left_cm)` pairs, or `None`.

    A hand-edited document can put anything here, and one unreadable opening must not become a wall
    across the map: it is dropped, and a route through a door nobody can describe stays a route.
    """
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 2:
        return None
    ends: list[tuple[float, float]] = []
    for end in (value[0], value[1]):
        if not isinstance(end, Sequence) or isinstance(end, (str, bytes)) or len(end) < 2:
            return None
        ends.append((_safe_float(end[0], math.nan), _safe_float(end[1], math.nan)))
    for forward, left in ends:
        if not (math.isfinite(forward) and math.isfinite(left)):
            return None
    return ends[0], ends[1]


def _sealed_cells(openings: Any, cell: float) -> set[tuple[int, int]]:
    """The cells a sealed doorway spans, sampled every half cell so none of them is skipped.

    Each opening is an `(a, b)` pair of planner points. A caller holding the document's
    `{"a": [x, y], "b": [x, y]}` converts through `home_map.document_point_to_runtime` first: the frame
    swap lives in one place (#347), and a door sealed along a transposed line is a route the dog takes.
    """
    blocked: set[tuple[int, int]] = set()
    if not isinstance(openings, Sequence) or isinstance(openings, (str, bytes)):
        return blocked
    for value in openings:
        segment = _segment(value)
        if segment is None:
            continue
        (forward_a, left_a), (forward_b, left_b) = segment
        span = math.hypot(forward_b - forward_a, left_b - left_a)
        steps = max(1, int(math.ceil(span / max(cell / 2.0, 1.0))))
        for step in range(steps + 1):
            fraction = step / steps
            blocked.add(
                _index_of(
                    (
                        forward_a + (forward_b - forward_a) * fraction,
                        left_a + (left_b - left_a) * fraction,
                    ),
                    cell,
                )
            )
    return blocked


def _astar(
    start: tuple[int, int],
    goal: tuple[int, int],
    occupied: set[tuple[int, int]],
    half_x: int,
    half_y: int,
    cell: float,
    clearance_cells: float,
    weight: float,
    inside: Callable[[tuple[int, int]], bool] | None = None,
) -> list[tuple[int, int]] | None:
    """A* over the four neighbours of each free cell, with the clearance penalty in the step cost.

    Four-way rather than eight: a diagonal step cuts a corner, and a corner is where a wall is.

    `inside` is the optional region test (H5): a cell it refuses is never entered, so the route that
    comes back cannot leave the polygon. The start cell is never tested - that is where the dog is, and
    refusing to plan from its own feet is not a constraint, it is a lock.
    """

    def heuristic(node: tuple[int, int]) -> float:
        return float(abs(node[0] - goal[0]) + abs(node[1] - goal[1]))

    frontier: list[tuple[float, tuple[int, int]]] = [(heuristic(start), start)]
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    cost_so_far: dict[tuple[int, int], float] = {start: 0.0}

    while frontier:
        _estimate, current = heapq.heappop(frontier)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return list(reversed(path))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            neighbour = (current[0] + dx, current[1] + dy)
            if neighbour in occupied or not _in_bounds(neighbour, half_x, half_y):
                continue
            if inside is not None and not inside(neighbour):
                continue
            step = cost_so_far[current] + _step_cost(
                neighbour, occupied, cell, clearance_cells, weight
            )
            if step < cost_so_far.get(neighbour, float("inf")):
                cost_so_far[neighbour] = step
                came_from[neighbour] = current
                heapq.heappush(frontier, (step + heuristic(neighbour), neighbour))
    return None


def _simplify(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drop the cells in the middle of a straight run: a route is corners, not a cell list."""
    if len(path) <= 2:
        return path
    kept = [path[0]]
    for index in range(1, len(path) - 1):
        previous, current, following = path[index - 1], path[index], path[index + 1]
        if (current[0] - previous[0], current[1] - previous[1]) != (
            following[0] - current[0],
            following[1] - current[1],
        ):
            kept.append(current)
    kept.append(path[-1])
    return kept


def plan_route(
    cells: Any,
    start_cm: tuple[float, float],
    goal_cm: tuple[float, float],
    settings: dict | None = None,
    *,
    region: Any = None,
    sealed_openings: Any = None,
) -> RoutePlan:
    """A route from `start_cm` to `goal_cm` over the mapped cells, or a named refusal.

    `cells` is the mapper's grid (`{"ix,iy": hits}`). The start and the goal are centimetres in the
    planner's own frame, `(forward_cm, left_cm)` — **not** the document's `[x = left, y = forward]`.
    Everything a caller can get wrong about the request comes back as a refusal: a start that is not on
    the map or is inside an obstacle is `start_unknown`, a goal in an obstacle is `goal_blocked`, and a
    goal walled off from the start is `no_path`.

    `region` is an optional room polygon in the same frame, and `sealed_openings` are `(a, b)` point
    pairs in it (H5). A goal outside the region is `goal_outside_region`; a goal inside it that can only
    be reached by walking out of it is `route_leaves_region`; a doorway listed as sealed is a wall for
    this plan, though the door itself is still open. A caller holding drawn geometry converts through
    `home_map.document_point_to_runtime` first — the swap lives in one place (#347), and a region or a
    doorway read in the wrong order is a route into the wrong room.

    A walk that **starts** outside `region` is planned unconstrained, on purpose: a dog outside has to
    be able to plan its way back in, and a hold that refused the return would be the trap it exists to
    prevent. The goal is still held, so the exemption cannot be used to wander further out.
    """
    settings = settings or {}
    cell = _safe_float(settings.get("cell_size_cm"), CELL_CM)
    if cell <= 0.0:
        cell = CELL_CM
    half_x, half_y = _grid_size(settings)
    half_x, half_y = half_x // 2, half_y // 2
    threshold = _safe_float(settings.get("occupied_hits"), OCCUPIED_HITS)
    clearance_cells = _safe_float(settings.get("clearance_cells"), CLEARANCE_CELLS)
    weight = _safe_float(settings.get("clearance_weight"), CLEARANCE_WEIGHT)

    grid = _cells_by_index(cells)
    occupied = {index for index, hits in grid.items() if hits >= threshold}

    start = _index_of(start_cm, cell)
    goal = _index_of(goal_cm, cell)
    if not _in_bounds(start, half_x, half_y) or start in occupied:
        return RoutePlan(
            refusal="start_unknown",
            detail=(
                f"the start {start_cm} is not a free cell on this map "
                f"(cell {start}, bounds +/-{half_x},{half_y})"
            ),
        )
    # A sealed doorway is a wall for this plan. The cell the dog already stands in is not: it may be
    # standing in that doorway, and refusing to plan from its own feet would hold it there.
    occupied |= _sealed_cells(sealed_openings, cell) - {start}
    if not _in_bounds(goal, half_x, half_y) or goal in occupied:
        return RoutePlan(
            refusal="goal_blocked",
            detail=f"the goal {goal_cm} is inside an obstacle or off the map (cell {goal})",
        )
    region_points = polygon_points(region)
    if region_points and not point_in_polygon(goal_cm, region_points):
        return RoutePlan(
            refusal="goal_outside_region",
            detail=f"the goal {goal_cm} is outside the region this walk is held in",
        )
    if start == goal:
        point = _centre_of(start, cell)
        return RoutePlan(
            waypoints=(
                Waypoint(
                    x_cm=point[0],
                    y_cm=point[1],
                    clearance_cm=_clearance_cm(point, occupied, cell),
                ),
            )
        )

    confine = bool(region_points) and point_in_polygon(start_cm, region_points)

    def inside(index: tuple[int, int]) -> bool:
        """Is this cell's centre inside the region? The route may not enter a cell that is not."""
        return point_in_polygon(_centre_of(index, cell), region_points)

    path = _astar(
        start,
        goal,
        occupied,
        half_x,
        half_y,
        cell,
        clearance_cells,
        weight,
        inside if confine else None,
    )
    if path is None:
        if confine:
            loose = _astar(start, goal, occupied, half_x, half_y, cell, clearance_cells, weight)
            if loose is not None:
                return RoutePlan(
                    refusal="route_leaves_region",
                    detail=(
                        f"every route from {start_cm} to {goal_cm} leaves the region "
                        f"(a free route exists, and it does not stay inside)"
                    ),
                )
        return RoutePlan(
            refusal="no_path", detail=f"no free route from cell {start} to cell {goal}"
        )
    return RoutePlan(
        waypoints=tuple(
            Waypoint(
                x_cm=_centre_of(index, cell)[0],
                y_cm=_centre_of(index, cell)[1],
                clearance_cm=_clearance_cm(_centre_of(index, cell), occupied, cell),
            )
            for index in _simplify(path)
        )
    )

