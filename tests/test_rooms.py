"""Rooms as a runtime question: is this point inside one, and is that one keep-out (#353).

The point of these is the case a happy-path test misses: a route is *corners*, and the straight run
between two corners can cross a room neither corner is in. A keep-out check that only looked at the
waypoints would call that walk clear.
"""

from __future__ import annotations

from houndmind_ai.mapping.rooms import (
    keep_out_room_at,
    keep_out_rooms,
    point_in_polygon,
    polyline_in_keep_out,
)

SQUARE = [[0, 0], [100, 0], [100, 100], [0, 100]]
# An L: the notch at x > 40 and y > 40 is *outside* the room, and a wall there is what makes it one.
ELL = [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]


def _document(*rooms: dict) -> dict:
    return {"rooms": list(rooms)}


def test_a_point_inside_and_outside_a_square() -> None:
    assert point_in_polygon((50, 50), SQUARE) is True
    assert point_in_polygon((150, 50), SQUARE) is False
    assert point_in_polygon((-1, -1), SQUARE) is False


def test_a_point_on_the_edge_counts_as_inside() -> None:
    """An edge is the boundary of the room, and a dog on it is in the room."""
    assert point_in_polygon((0, 50), SQUARE) is True
    assert point_in_polygon((100, 100), SQUARE) is True


def test_a_concave_room_does_not_swallow_its_notch() -> None:
    """Ray casting that ignored the shape would call the notch inside and refuse a legal walk."""
    assert point_in_polygon((20, 70), ELL) is True
    assert point_in_polygon((70, 70), ELL) is False


def test_a_polygon_that_is_not_one_is_not_a_room() -> None:
    assert point_in_polygon((0, 0), [[0, 0], [10, 10]]) is False
    assert point_in_polygon((0, 0), "nope") is False
    assert point_in_polygon((0, 0), [[0, 0], [10, "x"], [10, 10]]) is False


def test_a_vertex_that_cannot_be_read_is_dropped_not_zeroed() -> None:
    """One bad corner would otherwise move the room to the origin, which is worse than ignoring it."""
    polygon = [[0, 0], [100, 0], [100, 100], [0, 100], ["oops", None]]
    assert point_in_polygon((50, 50), polygon) is True
    assert point_in_polygon((-50, -50), polygon) is False


def test_only_keep_out_rooms_are_returned() -> None:
    document = _document(
        {"id": "kitchen", "name": "kitchen", "polygon": SQUARE},
        {"id": "stairs", "name": "stairs", "polygon": SQUARE, "keep_out": True},
        {"id": "den", "name": "den", "polygon": SQUARE, "keep_out": False},
        {"id": "half", "name": "half", "polygon": [[0, 0], [10, 10]], "keep_out": True},
    )
    rooms = keep_out_rooms(document)
    assert [room["id"] for room in rooms] == ["stairs"], "an unfinished lasso is not a room"


def test_the_room_a_point_falls_in_is_named() -> None:
    document = _document({"id": "stairs", "name": "stairs", "polygon": SQUARE, "keep_out": True})
    assert keep_out_room_at((50, 50), document)["id"] == "stairs"
    assert keep_out_room_at((500, 500), document) is None


def test_a_walk_across_a_room_is_caught_when_neither_end_is_in_it() -> None:
    """The whole reason the segment is sampled: the corners are outside, the walk is not."""
    document = _document(
        {"id": "stairs", "name": "stairs", "polygon": [[40, 0], [60, 0], [60, 100], [40, 100]],
         "keep_out": True}
    )
    assert polyline_in_keep_out([(20, 50), (80, 50)], document)["id"] == "stairs"


def test_a_walk_that_stays_outside_is_clear() -> None:
    document = _document(
        {"id": "stairs", "name": "stairs", "polygon": [[0, 40], [100, 40], [100, 60], [0, 60]],
         "keep_out": True}
    )
    assert polyline_in_keep_out([(0, 10), (100, 10), (100, 20)], document) is None


def test_a_document_with_no_keep_out_room_answers_none() -> None:
    document = _document({"id": "kitchen", "name": "kitchen", "polygon": SQUARE})
    assert polyline_in_keep_out([(0, 0), (1000, 1000)], document) is None
    assert polyline_in_keep_out([(0, 0), (1, 1)], {}) is None
