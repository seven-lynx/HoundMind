from houndmind_ai.mapping.path_planner import astar, default_path_planning_hook
from houndmind_ai.mapping.mapper import MappingModule
from houndmind_ai.core.runtime import RuntimeContext


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


def test_mapping_module_uses_hook():
    ctx = RuntimeContext()
    # minimal settings with mapping enabled and a goal
    settings = {"mapping": {"enabled": True, "path_planning_enabled": True, "goal": (2, 2)}}
    ctx.set("settings", settings)

    # create a small 3x3 grid with an obstacle
    grid = [
        [0, 0, 0],
        [1, 1, 0],
        [0, 0, 0],
    ]
    mapping_state = {"grid_map": grid, "current_cell": (0, 0), "samples": []}
    ctx.set("mapping_state", mapping_state)

    # register the default hook (as runtime would do)
    ctx.set("path_planning_hook", default_path_planning_hook)

    module = MappingModule("mapping", enabled=True)
    # also add a minimal scan_latest so the mapper doesn't bail early
    ctx.set("scan_latest", {"angles": {}})
    module.tick(ctx)

    plan = ctx.get("path_planning")
    assert isinstance(plan, dict)
    assert plan.get("success") is True
    assert plan.get("path") and plan["path"][0] == (0, 0)
