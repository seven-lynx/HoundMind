"""Routing a walk across the map the dog built (#305).

The planner is a pure function, so these are synthetic grids: a clear room, a wall with one gap, a
walled-off goal. Two of them exist because the map's axes are not the obvious ones — cells are keyed
`"ix,iy"` with `ix` counting *left* and `iy` *forward* — and a transposed route is a plan that looks
valid and walks into the wrong room.
"""

from __future__ import annotations

from houndmind_ai.mapping.planner import plan_route

__all__ = [
    "test_a_clear_room_gives_a_straight_route",
    "test_a_wall_with_one_gap_is_walked_through_the_gap",
    "test_a_goal_inside_an_obstacle_is_refused",
    "test_a_goal_walled_off_from_the_start_has_no_path",
    "test_a_start_off_the_map_is_refused",
    "test_the_axes_are_not_transposed",
    "test_clearance_is_reported_and_shrinks_near_a_wall",
    "test_cell_size_is_honoured",
    "test_a_goal_in_the_starting_cell_is_one_waypoint",
]


def _wall(cells: dict, *, forward_cm: float, left_from: int, left_to: int, cell: float = 10.0) -> None:
    """Mark a run of occupied cells at one forward distance, in the mapper's index order."""
    iy = int(round(forward_cm / cell))
    for ix in range(left_from, left_to + 1):
        cells[f"{ix},{iy}"] = 3


def test_a_clear_room_gives_a_straight_route() -> None:
    plan = plan_route({}, (0.0, 0.0), (100.0, 0.0))

    assert plan.ok is True
    assert plan.waypoints[0].x_cm == 0.0
    assert plan.waypoints[-1].x_cm == 100.0
    assert all(waypoint.y_cm == 0.0 for waypoint in plan.waypoints)
    assert all(waypoint.clearance_cm is None for waypoint in plan.waypoints), "nothing is mapped"


def test_a_wall_with_one_gap_is_walked_through_the_gap() -> None:
    cells: dict = {}
    _wall(cells, forward_cm=100.0, left_from=-5, left_to=-1)
    _wall(cells, forward_cm=100.0, left_from=1, left_to=5)

    plan = plan_route(cells, (0.0, 0.0), (200.0, 0.0))

    assert plan.ok is True
    assert all(waypoint.y_cm == 0.0 for waypoint in plan.waypoints), "the route stays in the gap"


def test_a_goal_inside_an_obstacle_is_refused() -> None:
    cells = {"0,10": 3}

    plan = plan_route(cells, (0.0, 0.0), (100.0, 0.0))

    assert plan.ok is False
    assert plan.refusal == "goal_blocked"
    assert "obstacle" in (plan.detail or "")


def test_a_goal_walled_off_from_the_start_has_no_path() -> None:
    cells: dict = {}
    _wall(cells, forward_cm=100.0, left_from=-50, left_to=50)

    plan = plan_route(cells, (0.0, 0.0), (200.0, 0.0))

    assert plan.ok is False
    assert plan.refusal == "no_path"


def test_a_start_off_the_map_is_refused() -> None:
    """`grid_size` is the map's edge; a pose outside it cannot be planned from."""
    plan = plan_route({}, (10_000.0, 0.0), (100.0, 0.0), {"grid_size": [100, 100]})

    assert plan.ok is False
    assert plan.refusal == "start_unknown"


def test_the_axes_are_not_transposed() -> None:
    """One obstacle straight ahead makes the dog step *sideways*, not shorten the walk.

    Cells are keyed `ix = left`, `iy = forward`. If the two were swapped this route would detour in
    forward distance and the assertion on `x_cm` would fail.
    """
    cells = {"0,10": 3}

    plan = plan_route(cells, (0.0, 0.0), (200.0, 0.0))

    assert plan.ok is True
    assert any(waypoint.y_cm != 0.0 for waypoint in plan.waypoints), "it steps around the obstacle"
    assert all(0.0 <= waypoint.x_cm <= 200.0 for waypoint in plan.waypoints)


def test_clearance_is_reported_and_shrinks_near_a_wall() -> None:
    cells: dict = {}
    _wall(cells, forward_cm=100.0, left_from=-50, left_to=50)

    plan = plan_route(cells, (0.0, 0.0), (60.0, 0.0))

    clearances = [waypoint.clearance_cm for waypoint in plan.waypoints]
    assert clearances[0] is not None and clearances[-1] is not None
    assert clearances[-1] < clearances[0], "the goal is nearer the wall than the start"


def test_cell_size_is_honoured() -> None:
    plan = plan_route({}, (0.0, 0.0), (100.0, 0.0), {"cell_size_cm": 20.0})

    assert plan.ok is True
    assert all(waypoint.x_cm % 20.0 == 0.0 for waypoint in plan.waypoints)


def test_a_goal_in_the_starting_cell_is_one_waypoint() -> None:
    plan = plan_route({}, (0.0, 0.0), (2.0, 1.0))

    assert plan.ok is True
    assert len(plan.waypoints) == 1
    assert plan.to_dict()["valid"] is True
