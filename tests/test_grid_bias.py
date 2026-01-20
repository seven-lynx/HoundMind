from houndmind_ai.navigation.obstacle_avoidance import ObstacleAvoidanceModule
from houndmind_ai.core.runtime import RuntimeContext


def test_grid_bias_prefers_sparser_side():
    ctx = RuntimeContext()
    module = ObstacleAvoidanceModule("avoid_test")
    # mapping_state grid with left dense and right sparse
    grid = {"cells": {"-2,1": 5, "-1,1": 3, "1,1": 0, "2,1": 0}}
    ctx.set("mapping_state", {"grid": grid})
    settings = {"use_grid_map": True, "grid_cell_size_cm": 10, "grid_influence_depth_cm": 100, "grid_bias_weight": 0.7}
    # Fallback direction is 'forward' -> expect bias to choose 'right' because left is denser
    choice = module._apply_grid_bias(ctx, settings, "forward")
    assert choice in ("left", "right", "forward")
    assert choice == "right", "Grid bias should prefer right when left is denser"


def test_grid_bias_no_cells_fallback():
    ctx = RuntimeContext()
    module = ObstacleAvoidanceModule("avoid_test")
    ctx.set("mapping_state", {})
    settings = {"use_grid_map": True}
    choice = module._apply_grid_bias(ctx, settings, "left")
    assert choice == "left", "Should return fallback when no grid cells present"
