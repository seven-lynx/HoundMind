"""The map can answer a distance question, and a wall it has not seen is not a clear corridor."""

from __future__ import annotations

from houndmind_ai.mapping.mapper import (
    MappingModule,
    cell_centre_cm,
    landmark_distance,
    nearest_wall,
    wall_distance,
)


def test_a_cell_centre_is_forward_then_left() -> None:
    # `ix` is left and `iy` forward in the grid, and the returned point uses the scan's order.
    assert cell_centre_cm(3, 2, 10.0) == (20.0, 30.0)


def test_landmark_distance_is_euclidean() -> None:
    assert landmark_distance((0.0, 0.0), (30.0, 40.0)) == 50.0


def test_wall_distance_measures_perpendicular_to_the_segment() -> None:
    assert wall_distance((50.0, 25.0), (0.0, 0.0), (100.0, 0.0)) == 25.0


def test_wall_distance_clamps_past_an_endpoint() -> None:
    # A wall is known between its two ends, so anything beyond is measured to the end.
    assert wall_distance((200.0, 0.0), (0.0, 0.0), (100.0, 0.0)) == 100.0


def test_a_degenerate_wall_is_a_point() -> None:
    assert wall_distance((3.0, 4.0), (0.0, 0.0), (0.0, 0.0)) == 5.0


def test_an_empty_map_knows_no_wall() -> None:
    assert nearest_wall(None, (0.0, 0.0), 200.0) is None
    assert nearest_wall({}, (0.0, 0.0), 200.0) is None
    assert nearest_wall({"cells": {}}, (0.0, 0.0), 200.0) is None


def test_the_nearest_hit_wins() -> None:
    grid = {"cells": {"0,5": 1, "0,10": 3, "0,40": 1}}

    assert nearest_wall(grid, (0.0, 0.0), 500.0) == 50.0


def test_nothing_inside_the_cap_is_not_a_wall_at_the_cap() -> None:
    grid = {"cells": {"0,5": 1}}

    assert nearest_wall(grid, (0.0, 0.0), 40.0) is None
    assert nearest_wall(grid, (0.0, 0.0), 60.0) == 50.0


def test_a_cell_with_no_hit_is_not_a_wall() -> None:
    assert nearest_wall({"cells": {"0,1": 0}}, (0.0, 0.0), 200.0) is None


def test_a_key_the_map_cannot_read_is_skipped_not_raised() -> None:
    grid = {"cells": {"x": 1, "0,1": 2}}

    assert nearest_wall(grid, (0.0, 0.0), 200.0) == 10.0


def test_cell_size_scales_the_answer() -> None:
    assert nearest_wall({"cells": {"0,2": 1}}, (0.0, 0.0), 200.0, cell_size_cm=25.0) == 50.0


def test_ingesting_a_scan_puts_the_wall_where_the_scan_said() -> None:
    module = MappingModule("mapping", enabled=True)
    state: dict = {}

    module._ingest_into_grid(
        {"0": 50.0}, {"cell_size_cm": 10.0, "grid_size": [100, 100]}, state
    )

    assert nearest_wall(state["grid"], (0.0, 0.0), 200.0) == 50.0


def test_a_left_scan_lands_on_the_left_axis() -> None:
    module = MappingModule("mapping", enabled=True)
    state: dict = {}

    module._ingest_into_grid(
        {"90": 30.0}, {"cell_size_cm": 10.0, "grid_size": [100, 100]}, state
    )

    assert nearest_wall(state["grid"], (0.0, 0.0), 200.0) == 30.0
