"""Which room a point is in, and whether that room is one the dog must stay out of (#353).

`rooms` has been drawn on the console since M4 and read by **nothing but the renderer**: a user could
mark a room keep-out, see it drawn with a dashed red edge, and the planner would route straight through
it (#353). This is the runtime's half of that defect: one ray-casting predicate, and the two questions a
route asks of it - is this point inside a keep-out room, and does this polyline pass through one.

It deliberately does **not** decide what a route may do. `mapping/planner.py` owns the route, and a
caller asks here whether a point or a path is off limits, then turns the answer into its own named
refusal. Plan H (H1, H5) grows region and sealed-opening semantics on top of this predicate; nothing
here knows about rooms the dog *is* allowed in, because a room the dog may enter changes no answer.

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
    "keep_out_room_at",
    "keep_out_rooms",
    "point_in_polygon",
    "polyline_in_keep_out",
    "room_label",
]

#: How far apart a polyline is sampled when it is tested against a room. A route is corners, and the
#: straight run between two of them can cross a room neither corner is in; sampling closes that hole.
#: Five centimetres is below one sonar cell and below one gait step, so no room the dog could walk
#: through fits between two samples.
KEEP_OUT_SAMPLE_CM = 5.0


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


def _on_segment(point: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Is `point` on the segment `a`-`b`, within a tolerance a float can actually distinguish?

    Distance from the point to the segment, compared against a millimetre: a polygon vertex typed at
    one decimal place cannot be placed more precisely than that, and a boundary that reads as inside
    only half the time is a keep-out room the dog walks through every other time.
    """
    (px, py), (ax, ay), (bx, by) = point, a, b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 0.0:
        return math.hypot(px - ax, py - ay) <= 0.1
    # Project onto the segment, clamped to its ends.
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)) <= 0.1


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


def room_label(room: Any) -> str:
    """A room as a person names it: its `name`, its `id`, or a phrase that admits it has neither.

    One spelling, used by every refusal that names a room, so an error a user reads in the console and
    the same refusal in the event log cannot disagree about what the room is called.
    """
    if not isinstance(room, Mapping):
        return "unnamed room"
    return str(room.get("name") or room.get("id") or "unnamed room")


def keep_out_rooms(document: Any) -> list[dict[str, Any]]:
    """The rooms a user marked keep-out, as dicts with at least three usable vertices.

    A `keep_out` room with two corners is not a room yet - the lasso that writes one refuses to close
    below three - so it is skipped rather than treated as a wall across the map.
    """
    if not isinstance(document, Mapping):
        return []
    rooms = document.get("rooms")
    if not isinstance(rooms, Sequence) or isinstance(rooms, (str, bytes)):
        return []
    found: list[dict[str, Any]] = []
    for room in rooms:
        if not isinstance(room, Mapping) or not room.get("keep_out"):
            continue
        if _vertices(room.get("polygon")):
            found.append(dict(room))
    return found


def keep_out_room_at(point: Any, document: Any) -> dict[str, Any] | None:
    """The keep-out room `point` falls in, or `None`. First match wins; rooms may overlap."""
    for room in keep_out_rooms(document):
        if point_in_polygon(point, room.get("polygon")):
            return room
    return None


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
