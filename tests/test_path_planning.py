"""`mapping/path_planner.py::astar` on its own.

There is no hook test any more. `default_path_planning_hook` read `grid_map`, `current_cell` and
`settings.goal`, none of which production writes, so the old test built that shape by hand and
certified a contract the mapper never satisfied (#121). `astar` is a library helper with no caller
in the runtime; goal-directed walking is `place_navigator`.
"""

from houndmind_ai.mapping.path_planner import astar


def test_astar_simple():
    grid = [
        [0, 0, 0],
        [1, 1, 0],
        [0, 0, 0],
    ]
    start = (0, 0)
    goal = (2, 2)
    path = astar(grid, start, goal)
    assert path[0] == start
    assert path[-1] == goal


def test_astar_returns_no_path_when_the_goal_is_walled_off():
    grid = [
        [0, 1, 0],
        [0, 1, 0],
        [0, 1, 0],
    ]

    assert astar(grid, (0, 0), (2, 2)) == []

