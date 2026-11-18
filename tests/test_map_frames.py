"""Two frames, both correct, both called x/y — pinned so the swap stays in one place (#347).

The defect was not a transposition; it was that a **document** point and a **runtime** point are both
`[x, y]` and mean different axes. `document_point_to_runtime` is the single written swap, and the cases
here are the ones that would otherwise be rediscovered by drawing a mirrored dog: a point one metre to
the dog's left is zero forward and one metre left, and a cell centre taken from the mapper is the point
the planner routes to.
"""

from __future__ import annotations

import pytest

from houndmind_ai.mapping.home_map import document_point_to_runtime, runtime_point_to_document
from houndmind_ai.mapping.mapper import cell_centre_cm
from houndmind_ai.mapping.planner import _centre_of, _index_of


def test_a_document_point_one_metre_left_is_zero_forward_one_metre_left() -> None:
    """The case that makes the two frames impossible to confuse: the axes are swapped, not renumbered."""
    assert document_point_to_runtime([100.0, 0.0]) == (0.0, 100.0)
    assert document_point_to_runtime([0.0, 100.0]) == (100.0, 0.0)


def test_the_swap_round_trips_both_ways() -> None:
    point = (37.5, -12.5)
    assert runtime_point_to_document(document_point_to_runtime(list(point))) == point
    assert document_point_to_runtime(runtime_point_to_document(point)) == point


def test_a_document_vertex_that_is_short_or_nonsense_is_the_origin() -> None:
    """One hand-typed vertex must not make a whole document unreadable."""
    assert document_point_to_runtime([5.0]) == (0.0, 5.0)
    assert document_point_to_runtime("nonsense") == (0.0, 0.0)
    assert document_point_to_runtime(None) == (0.0, 0.0)


def test_a_cell_centre_is_a_runtime_point() -> None:
    """`ix` counts left and `iy` forward, and the pair that comes back is `(forward, left)`."""
    assert cell_centre_cm(0, 10, 10.0) == (100.0, 0.0)
    assert cell_centre_cm(10, 0, 10.0) == (0.0, 100.0)


def test_the_planner_reads_the_point_the_mapper_returned() -> None:
    """The pin: a cell centre goes back to the cell it came from, and the two agree on the axes."""
    assert _index_of(cell_centre_cm(0, 10, 10.0), 10.0) == (0, 10)
    assert _index_of(cell_centre_cm(10, 0, 10.0), 10.0) == (10, 0)
    assert _centre_of((0, 10), 10.0) == (100.0, 0.0)


def test_a_document_wall_lands_in_the_cell_the_mapper_wrote() -> None:
    """The composition that M5 needs: a wall one metre to the left is the cell `ix=10, iy=0`."""
    wall_cm = [100.0, 0.0]
    assert _index_of(document_point_to_runtime(wall_cm), 10.0) == (10, 0)
    # And the mirror of it is a different cell, so a client that forgets the swap cannot pass by luck.
    assert _index_of((wall_cm[0], wall_cm[1]), 10.0) == (0, 10)


@pytest.mark.parametrize("point", [(0.0, 0.0), (-45.0, 45.0), (300.0, -20.0)])
def test_the_round_trip_holds_for_any_point(point: tuple[float, float]) -> None:
    assert _centre_of(_index_of(point, 5.0), 5.0) == pytest.approx(
        (round(point[0] / 5.0) * 5.0, round(point[1] / 5.0) * 5.0)
    )
