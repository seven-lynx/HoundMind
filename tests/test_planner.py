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
    "test_a_goal_outside_the_region_is_refused",
    "test_the_region_is_read_in_the_planners_order_not_the_documents",
    "test_a_route_is_held_inside_the_region",
    "test_a_walk_that_can_only_leave_the_region_is_refused",
    "test_a_walk_that_starts_outside_the_region_is_still_planned",
    "test_a_sealed_opening_is_the_difference_between_a_route_and_a_refusal",
    "test_a_sealed_opening_in_a_wall_with_no_way_round_is_no_path",
    "test_an_unreadable_sealed_opening_is_dropped_not_walled",
    "test_an_unusable_region_constrains_nothing",
]

#: A room 200 cm deep and 80 cm wide, in the planner's own `(forward_cm, left_cm)` order. Tall on
#: purpose: a region read in the document's `[x = left, y = forward]` order is a different room, and
#: every assertion about it would answer differently.
ROOM = [(0.0, -40.0), (200.0, -40.0), (200.0, 40.0), (0.0, 40.0)]



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


def test_a_goal_outside_the_region_is_refused() -> None:
    plan = plan_route({}, (50.0, 0.0), (300.0, 0.0), region=ROOM)

    assert plan.ok is False
    assert plan.refusal == "goal_outside_region"
    assert "region" in (plan.detail or "")


def test_the_region_is_read_in_the_planners_order_not_the_documents() -> None:
    """The same two points, asked against both orders: one is a room, the other is not.

    `deep` is 200 cm forward and 40 cm to either side. Swapping every pair - which is what reading a
    drawn room without `document_point_to_runtime` does - makes a 40 cm deep, 200 cm wide one, and the
    goal 150 cm ahead falls out of it.
    """
    deep = [(0.0, -20.0), (200.0, -20.0), (200.0, 20.0), (0.0, 20.0)]
    swapped = [(left, forward) for forward, left in deep]

    assert plan_route({}, (10.0, 0.0), (150.0, 0.0), region=deep).ok is True
    assert plan_route({}, (10.0, 0.0), (150.0, 0.0), region=swapped).refusal == "goal_outside_region"


def test_a_route_is_held_inside_the_region() -> None:
    """A wall across the room with one gap: the route takes the gap and never leaves the polygon."""
    cells: dict = {}
    _wall(cells, forward_cm=100.0, left_from=-4, left_to=-1)
    _wall(cells, forward_cm=100.0, left_from=1, left_to=4)

    plan = plan_route(cells, (0.0, 0.0), (200.0, 0.0), region=ROOM)

    assert plan.ok is True
    assert all(-40.0 <= waypoint.y_cm <= 40.0 for waypoint in plan.waypoints)


def test_a_walk_that_can_only_leave_the_region_is_refused() -> None:
    """A wall from one drawn wall to the other: the only way round it is outside the room."""
    cells: dict = {}
    _wall(cells, forward_cm=100.0, left_from=-40, left_to=40)

    plan = plan_route(cells, (0.0, 0.0), (200.0, 0.0), region=ROOM)

    assert plan.ok is False
    assert plan.refusal == "route_leaves_region"


def test_a_walk_that_starts_outside_the_region_is_still_planned() -> None:
    """The hold is directional. An escapee that could not plan its way home would be caged by it."""
    plan = plan_route({}, (100.0, 400.0), (100.0, 0.0), region=ROOM)

    assert plan.ok is True
    assert plan.waypoints[-1].y_cm == 0.0


def test_a_sealed_opening_is_the_difference_between_a_route_and_a_refusal() -> None:
    """The doorway stays drawn and stays open; the plan simply does not use it (H5)."""
    cells: dict = {}
    _wall(cells, forward_cm=100.0, left_from=-4, left_to=-1)
    _wall(cells, forward_cm=100.0, left_from=1, left_to=4)

    open_door = plan_route(cells, (0.0, 0.0), (200.0, 0.0), region=ROOM)
    sealed = plan_route(
        cells,
        (0.0, 0.0),
        (200.0, 0.0),
        region=ROOM,
        sealed_openings=[((100.0, -6.0), (100.0, 6.0))],
    )

    assert open_door.ok is True
    assert sealed.refusal == "route_leaves_region", "the only way past that wall is outside the room"


def test_a_sealed_opening_in_a_wall_with_no_way_round_is_no_path() -> None:
    """Sealing is independent of the region: with no region, a sealed gap is simply a wall."""
    cells: dict = {}
    _wall(cells, forward_cm=100.0, left_from=-50, left_to=-1)
    _wall(cells, forward_cm=100.0, left_from=1, left_to=50)

    open_door = plan_route(cells, (0.0, 0.0), (200.0, 0.0))
    sealed = plan_route(
        cells, (0.0, 0.0), (200.0, 0.0), sealed_openings=[((100.0, -6.0), (100.0, 6.0))]
    )

    assert open_door.ok is True
    assert sealed.ok is False
    assert sealed.refusal == "no_path"


def test_an_unreadable_sealed_opening_is_dropped_not_walled() -> None:
    """One garbage doorway in a hand-edited document must not become a wall across the map."""
    plan = plan_route(
        {},
        (0.0, 0.0),
        (100.0, 0.0),
        sealed_openings=[("nope", None), ((0.0, 0.0), ("x", 1.0))],
    )

    assert plan.ok is True


def test_an_unusable_region_constrains_nothing() -> None:
    """A two-corner lasso is not a room, so it holds nothing; H6 refuses the run instead."""
    assert plan_route({}, (0.0, 0.0), (100.0, 0.0), region=None).ok is True
    assert plan_route({}, (0.0, 0.0), (100.0, 0.0), region="nope").ok is True
    assert plan_route({}, (0.0, 0.0), (100.0, 0.0), region=[[0.0, 0.0], [10.0, 10.0]]).ok is True
