"""Rooms as a runtime question: is this point inside one, and is that one keep-out (#353).

The point of these is the case a happy-path test misses: a route is *corners*, and the straight run
between two corners can cross a room neither corner is in. A keep-out check that only looked at the
waypoints would call that walk clear.
"""

from __future__ import annotations

import pytest

from houndmind_ai.mapping.rooms import (
    edge_distances,
    keep_out_room_at,
    keep_out_rooms,
    point_in_polygon,
    polyline_in_keep_out,
    room_at,
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


def test_room_at_names_a_room_that_is_not_keep_out() -> None:
    """H1: the room the dog is in is a fact, not a refusal, so keep-out must not filter it."""
    document = _document({"id": "kitchen", "name": "Kitchen", "polygon": SQUARE})
    assert room_at((50, 50), document)["name"] == "Kitchen"
    assert room_at((500, 500), document) is None


def test_room_at_skips_a_lasso_that_is_not_a_room() -> None:
    document = _document({"id": "half", "polygon": [[0, 0], [100, 100]]})
    assert room_at((50, 50), document) is None


def test_room_at_answers_the_first_room_drawn_when_two_overlap() -> None:
    """The map is not a partition, so the rule is first-match-wins, exactly as keep-out's is."""
    document = _document(
        {"id": "hall", "name": "Hall", "polygon": SQUARE},
        {"id": "kitchen", "name": "Kitchen", "polygon": SQUARE},
    )
    assert room_at((50, 50), document)["id"] == "hall"


def test_room_at_on_an_unusable_point_is_none_not_a_guess() -> None:
    document = _document({"id": "kitchen", "name": "Kitchen", "polygon": SQUARE})
    assert room_at("nope", document) is None
    assert room_at((50, "x"), document) is None


def test_edge_distances_measure_the_walls_not_the_corners() -> None:
    """An off-centre point: 25 cm from the left wall and 75 from the right one, not the corner."""
    nearest, farthest = edge_distances((25, 50), {"polygon": SQUARE})
    assert nearest == pytest.approx(25.0)
    assert farthest == pytest.approx(75.0)


def test_the_centre_of_a_square_is_equally_far_from_every_wall() -> None:
    """A corner is not an edge point, so the projection clamps to the wall and both read 50."""
    assert edge_distances((50, 50), {"polygon": SQUARE}) == pytest.approx((50.0, 50.0))


def test_edge_distances_from_outside_a_room() -> None:
    """Outside, right of the square: 50 to that wall and 150 across to the far one."""
    nearest, farthest = edge_distances((150, 50), {"polygon": SQUARE})
    assert nearest == pytest.approx(50.0)
    assert farthest == pytest.approx(150.0)


def test_a_point_on_the_wall_is_zero_away() -> None:
    """A real measurement, which is why an unusable room is `None` rather than this."""
    nearest, _ = edge_distances((0, 50), {"polygon": SQUARE})
    assert nearest == pytest.approx(0.0)


def test_edge_distances_on_an_unusable_room_is_none() -> None:
    """Zero must not read as a wall distance for a caller deciding whether a room can take a stride."""
    assert edge_distances((50, 50), {"polygon": [[0, 0], [100, 100]]}) is None
    assert edge_distances((50, 50), {"polygon": "nope"}) is None
    assert edge_distances((50, 50), {}) is None
    assert edge_distances("nope", {"polygon": SQUARE}) is None
