"""Which room a point is in, whether it is off limits, and how far its walls are (#353, H1).

`rooms` has been drawn on the console since M4 and read by **nothing but the renderer**: a user could
mark a room keep-out, see it drawn with a dashed red edge, and the planner would route straight through
it (#353). This is the runtime's half of that defect: one ray-casting predicate, and the two questions a
route asks of it - is this point inside a keep-out room, and does this polyline pass through one.

Plan H adds the other two questions the same predicate answers, and they are not about refusal:
`room_at` names the room a point is in, keep-out or not, because "you are in the Kitchen" is a fact a
client can render; `edge_distances` measures a point against a room's walls, which is what the scale
work needs before it can compare a drawn wall with a ranged one.

It deliberately does **not** decide what a route may do. `mapping/planner.py` owns the route, and a
caller asks here whether a point or a path is off limits, then turns the answer into its own named
refusal. Nothing here knows which rooms the dog may *enter* either: a room the dog may enter changes no
answer this module gives. The keep-in **region** (H5) is the one question that is not about refusal and
not about a route: `step_inside_region` answers whether one stride would take the body out of the room a
run is held in, which is the layer that holds a patrol in, because a patrol never asks for a route.

Everything is in the **document** frame (`[x = left, y = forward]`), because that is the frame `rooms`
is stored and drawn in. A caller holding runtime points swaps once, through
`mapping/home_map.py::runtime_point_to_document`, rather than re-deriving the swap here (#347).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "KEEP_OUT_SAMPLE_CM",
    "REGION_MARGIN_CM",
    "edge_distances",
    "keep_out_room_at",
    "keep_out_rooms",
    "point_in_polygon",
    "polygon_points",
    "polyline_in_keep_out",
    "room_at",
    "room_label",
    "step_inside_region",
]

#: How far apart a polyline is sampled when it is tested against a room. A route is corners, and the
#: straight run between two of them can cross a room neither corner is in; sampling closes that hole.
#: Five centimetres is below one sonar cell and below one gait step, so no room the dog could walk
#: through fits between two samples.
KEEP_OUT_SAMPLE_CM = 5.0

#: How much room the body needs between a predicted pose and the drawn wall before the step counts as
#: inside the region (H5). A stride that ends nearer than this to the edge is a body against a wall, not a
#: walk inside a room; a step that moves *toward* the region is never refused on it.
REGION_MARGIN_CM = 15.0


def _safe_float(value: Any, default: float) -> float:
    """A finite float, or `default`. A heading, a step and a drawn coordinate all arrive as `Any`."""
    try:
        if value is None:
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default



def _point(value: Any) -> tuple[float, float] | None:
    """Two finite floats from `[x, y]`, or `None`. A hand-typed vertex can be anything."""
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return None
    if len(value) < 2:
        return None
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y)):
        return None
    return x, y


def _vertices(polygon: Any) -> list[tuple[float, float]]:
    """A polygon's usable vertices, in order. A shape with fewer than three is not a polygon."""
    if not isinstance(polygon, Sequence) or isinstance(polygon, (str, bytes)):
        return []
    points = [point for point in (_point(vertex) for vertex in polygon) if point is not None]
    return points if len(points) >= 3 else []


def _distance_to_segment(
    point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Distance from `point` to the segment `a`-`b`, projected and clamped to its ends."""
    (px, py), (ax, ay), (bx, by) = point, a, b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.hypot(px - ax, py - ay)
    # Project onto the segment, clamped to its ends.
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _on_segment(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Is `point` on the segment `a`-`b`, within a tolerance a float can actually distinguish?

    Distance from the point to the segment, compared against a millimetre: a polygon vertex typed at
    one decimal place cannot be placed more precisely than that, and a boundary that reads as inside
    only half the time is a keep-out room the dog walks through every other time.
    """
    return _distance_to_segment(point, a, b) <= 0.1


def point_in_polygon(point: Any, polygon: Any) -> bool:
    """Is `point` inside `polygon`? Inside **or on the edge** - a dog on the boundary is in the room.

    Every vertex the implementation cannot read is dropped rather than treated as zero: one bad corner
    would otherwise turn a room into a triangle somewhere else, and a keep-out room that moved is worse
    than one that is ignored.

    The ray cast uses the standard half-open rule, which counts a ray that grazes a vertex once. That
    rule alone puts the right and top edges *outside*, which is why the boundary is tested separately:
    "the dog is on the line" must not depend on which side of the room the line is on.
    """
    target = _point(point)
    vertices = _vertices(polygon)
    if target is None or not vertices:
        return False
    x, y = target
    count = len(vertices)
    for index in range(count):
        if _on_segment(target, vertices[index], vertices[(index + 1) % count]):
            return True
    inside = False
    for index in range(count):
        ax, ay = vertices[index]
        bx, by = vertices[(index + 1) % count]
        # A horizontal ray to -x; count an edge when it straddles it and the point is left of it.
        if (ay > y) != (by > y):
            x_at_y = ax + (y - ay) * (bx - ax) / (by - ay)
            if x_at_y > x:
                inside = not inside
    return inside


def polygon_points(polygon: Any) -> list[tuple[float, float]]:
    """A polygon's usable vertices, in order; fewer than three means the shape is not a polygon.

    The one place that decides what counts as a room's shape, so a module that has to know whether it was
    handed a region **at all** asks this instead of re-deriving the rule: a two-corner lasso is not a
    room, and a caller that treated it as one would hold a walk against a line.
    """
    return _vertices(polygon)


def room_label(room: Any) -> str:
    """A room as a person names it: its `name`, its `id`, or a phrase that admits it has neither.

    One spelling, used by every refusal that names a room, so an error a user reads in the console and
    the same refusal in the event log cannot disagree about what the room is called.
    """
    if not isinstance(room, Mapping):
        return "unnamed room"
    return str(room.get("name") or room.get("id") or "unnamed room")


def _rooms(document: Any) -> list[dict[str, Any]]:
    """Every room with at least three usable vertices, keep-out or not, in document order.

    A room with two corners is not a room yet - the lasso that writes one refuses to close below
    three - so it is skipped rather than treated as a wall across the map.
    """
    if not isinstance(document, Mapping):
        return []
    rooms = document.get("rooms")
    if not isinstance(rooms, Sequence) or isinstance(rooms, (str, bytes)):
        return []
    return [
        dict(room)
        for room in rooms
        if isinstance(room, Mapping) and _vertices(room.get("polygon"))
    ]


def keep_out_rooms(document: Any) -> list[dict[str, Any]]:
    """The rooms a user marked keep-out, as dicts with at least three usable vertices."""
    return [room for room in _rooms(document) if room.get("keep_out")]


def keep_out_room_at(point: Any, document: Any) -> dict[str, Any] | None:
    """The keep-out room `point` falls in, or `None`. First match wins; rooms may overlap."""
    for room in keep_out_rooms(document):
        if point_in_polygon(point, room.get("polygon")):
            return room
    return None


def room_at(point: Any, document: Any) -> dict[str, Any] | None:
    """The room `point` falls in, keep-out or not, or `None`. First match wins.

    The sibling of `keep_out_room_at` and deliberately the same walk in the same order: the map is
    **not a partition**, so a point inside two overlapping rooms belongs to the one drawn first, and a
    caller that needs every candidate reads `document["rooms"]` itself rather than expecting a list.

    The frame is the document's (`[x = left, y = forward]`); a caller holding a runtime point swaps
    once through `home_map.runtime_point_to_document` first (#347).
    """
    for room in _rooms(document):
        if point_in_polygon(point, room.get("polygon")):
            return room
    return None


def edge_distances(point: Any, room: Any) -> tuple[float, float] | None:
    """Nearest and farthest distance in cm from `point` to `room`'s edges, or `None`.

    `None` rather than zeros when the room or the point is unusable: a distance of zero means "on the
    wall", which is a measurement, and a caller deciding whether a room is wide enough to take a stride
    must not read a failed read as one.

    Both numbers are measured to the polygon's **edges**, not its vertices, so a point inside a room
    never reads zero while a point on a wall does.
    """
    target = _point(point)
    if target is None or not isinstance(room, Mapping):
        return None
    vertices = _vertices(room.get("polygon"))
    if not vertices:
        return None
    count = len(vertices)
    distances = [
        _distance_to_segment(target, vertices[index], vertices[(index + 1) % count])
        for index in range(count)
    ]
    return min(distances), max(distances)


def polyline_in_keep_out(points: Any, document: Any) -> dict[str, Any] | None:
    """The keep-out room a polyline passes through, or `None`.

    The vertices are tested first and then each straight run is sampled, because a route is corners:
    `[(0, 0), (400, 0)]` can cross a room that neither end is in, and a check that only looked at the
    waypoints would report that walk as clear.
    """
    if not keep_out_rooms(document):
        return None
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        return None
    path = [point for point in (_point(vertex) for vertex in points) if point is not None]
    if not path:
        return None
    for x, y in path:
        room = keep_out_room_at((x, y), document)
        if room is not None:
            return room
    for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
        span = math.hypot(bx - ax, by - ay)
        steps = max(1, int(math.ceil(span / KEEP_OUT_SAMPLE_CM)))
        for step in range(1, steps):
            fraction = step / steps
            room = keep_out_room_at(
                (ax + (bx - ax) * fraction, ay + (by - ay) * fraction), document
            )
            if room is not None:
                return room
    return None


def _nearest_edge_cm(point: tuple[float, float], vertices: list[tuple[float, float]]) -> float:
    """Distance from `point` to the nearest edge of a polygon already known to be usable."""
    count = len(vertices)
    return min(
        _distance_to_segment(point, vertices[index], vertices[(index + 1) % count])
        for index in range(count)
    )


def step_inside_region(
    pose: Any,
    heading_deg: Any,
    step_cm: Any,
    region: Any,
    margin_cm: float = REGION_MARGIN_CM,
) -> bool:
    """Would one stride from `pose` at `heading_deg` stay inside `region`? H5's keep-in gate.

    `True` means the step is legal. Three things make it `False`: the pose lands outside the polygon, it
    lands inside but nearer than `margin_cm` to the drawn wall (a body against a wall is not a body in a
    room), or the dog is already outside and the step does not bring it closer.

    **The hold is directional**, and that is the whole safety argument for it: a dog outside the polygon
    has to be able to walk back in, or the escape hatch becomes the trap. So a step that *moves toward*
    the region is never refused, even when it ends within the margin or still outside.

    Everything is in the **document** frame (`[x = left, y = forward]`), because a drawn room is stored
    and drawn in it; a runtime pose swaps once through `home_map.runtime_point_to_document` (#347).
    `heading_deg` is the odometry convention - 0 is forward, positive is left - so a stride of `step_cm`
    moves `+step * cos` along `y` and `+step * sin` along `x`.

    A region that is not a polygon and a pose that cannot be read both answer `True`: this is a routing
    constraint, not an interlock, and the run refuses to start without a usable region (H6). A gate that
    failed closed here would hold every step of a dog whose drawing was wrong, with no sensor at fault.
    """
    vertices = _vertices(region)
    current = _point(pose)
    if not vertices or current is None:
        return True
    heading = math.radians(_safe_float(heading_deg, 0.0))
    step = _safe_float(step_cm, 0.0)
    margin = _safe_float(margin_cm, REGION_MARGIN_CM)
    predicted = (
        current[0] + step * math.sin(heading),
        current[1] + step * math.cos(heading),
    )
    if point_in_polygon(predicted, vertices):
        if margin <= 0.0 or _nearest_edge_cm(predicted, vertices) >= margin:
            return True
    if point_in_polygon(current, vertices):
        return False
    # Outside before: only a step that closes the distance to the room is legal.
    return _nearest_edge_cm(predicted, vertices) < _nearest_edge_cm(current, vertices)

