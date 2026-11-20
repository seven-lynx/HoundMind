"""The stride, measured inside a drawn room: confirm it, or discover it (H4).

`navigation/odometry.py` multiplies counted steps by a 25 cm guess (#285), and
`tools/step_calibrate.py` measures the real one by walking into a wall. These hold the version that
measures it inside a room the user drew, where the room's own walls are the reference and nothing has
to be touched.

Every fixture is synthetic: a dog whose pose over-counts each step by `assumed / true`, a square
room, and a sonar that returns the distance to the wall it is pointed at. No hardware, no motion.
"""

from __future__ import annotations

import math

import pytest

from houndmind_ai.mapping.room_scale import (
    SCALE_AGREEMENT_PCT,
    SCALE_MIN_RANGES,
    RoomScale,
    ScaleSample,
)

ROOM_CM = 400.0
ROOM = [[0, 0], [ROOM_CM, 0], [ROOM_CM, ROOM_CM], [0, ROOM_CM]]


def _room(*, size_cm: dict | None = None) -> dict:
    """A square room in the document frame; `size_cm` is what makes it a *measured* one."""
    room: dict = {"id": "kitchen", "name": "Kitchen", "polygon": [list(v) for v in ROOM]}
    if size_cm is not None:
        room["size_cm"] = size_cm
    return room


def _range_to_wall(at: tuple[float, float], dx: float, dy: float) -> float:
    """Distance from `at` to the square room's boundary along the unit direction `(dx, dy)`."""
    distances = []
    if dx > 0:
        distances.append((ROOM_CM - at[0]) / dx)
    if dx < 0:
        distances.append(at[0] / -dx)
    if dy > 0:
        distances.append((ROOM_CM - at[1]) / dy)
    if dy < 0:
        distances.append(at[1] / -dy)
    return min(distances) if distances else 0.0


class _WalkingDog:
    """A dog whose pose over-counts every step by `assumed_cm / true_cm`.

    `real` is where the dog is in the drawing; `pose` is what the odometry believes, and the sonar
    ranges from the *real* position. That one error model is the whole point: a stride 10 % short
    makes the pose 10 % long, and every wall it ranges disagrees with the drawing by that much.
    """

    def __init__(
        self,
        *,
        assumed_cm: float,
        true_cm: float,
        at: tuple[float, float] = (200.0, 40.0),
        heading_deg: float = 0.0,
    ) -> None:
        self.assumed_cm = assumed_cm
        self.true_cm = true_cm
        self.real = (float(at[0]), float(at[1]))
        self.pose = (float(at[0]), float(at[1]))  # the confirmed origin: pose == real at the start
        self.heading_deg = heading_deg

    def face(self, heading_deg: float) -> None:
        self.heading_deg = heading_deg

    def step(self, count: int) -> list[ScaleSample]:
        """`count` samples, one per gait cycle, each taken *before* the dog moves."""
        taken: list[ScaleSample] = []
        radians = math.radians(self.heading_deg)
        dx, dy = math.sin(radians), math.cos(radians)
        for _ in range(count):
            taken.append(
                ScaleSample(
                    # The runtime speaks `(forward_cm, left_cm)`; the drawing is `[left, forward]`.
                    pose_cm=(self.pose[1], self.pose[0]),
                    heading_deg=self.heading_deg,
                    range_cm=_range_to_wall(self.real, dx, dy),
                    distance_valid=True,
                )
            )
            self.real = (self.real[0] + dx * self.true_cm, self.real[1] + dy * self.true_cm)
            self.pose = (
                self.pose[0] + dx * self.assumed_cm,
                self.pose[1] + dy * self.assumed_cm,
            )
        return taken


def _lap(dog: _WalkingDog, *, steps: int = 5) -> list[ScaleSample]:
    """North, east, south, west: every wall of the room ranged at least once."""
    taken: list[ScaleSample] = []
    for heading in (0.0, 90.0, 180.0, 270.0):
        dog.face(heading)
        taken.extend(dog.step(steps))
    return taken


def test_a_room_with_no_dimension_discovers_the_stride() -> None:
    """The drawing says where the walls are, never how long they are: the ranges do the measuring."""
    dog = _WalkingDog(assumed_cm=10.0, true_cm=9.0)
    run = RoomScale(_room(), step_cm=dog.assumed_cm)
    for sample in _lap(dog):
        assert run.add(sample) is True

    progress = run.finish()

    assert progress["mode"] == "discover"
    assert progress["verdict"] == "measured", progress["reason"]
    assert progress["scale_cm"] == pytest.approx(9.0, rel=0.05)
    assert progress["criteria"]["min_ranges"]["have"] == 20
    assert progress["criteria"]["min_perimeter_coverage"]["have"] == 1.0


def test_a_room_with_a_dimension_confirms_the_stride() -> None:
    """Confirm compares the drawn wall distance with the ranged one; the fit is the same ratio."""
    dog = _WalkingDog(assumed_cm=10.0, true_cm=9.0)
    run = RoomScale(
        _room(size_cm={"width_cm": ROOM_CM, "depth_cm": ROOM_CM}), step_cm=dog.assumed_cm
    )
    for sample in _lap(dog):
        assert run.add(sample) is True

    progress = run.finish()

    assert progress["mode"] == "confirm"
    assert progress["verdict"] == "measured", progress["reason"]
    assert progress["scale_cm"] == pytest.approx(9.0, rel=0.05)


def test_a_room_whose_north_edge_is_never_ranged_refuses_by_name() -> None:
    """Coverage is a criterion, not a shrug: the refusal says which wall is missing."""
    dog = _WalkingDog(assumed_cm=10.0, true_cm=9.0, at=(200.0, 300.0))
    run = RoomScale(_room(), step_cm=dog.assumed_cm)
    for heading in (90.0, 180.0, 270.0):
        dog.face(heading)
        for sample in dog.step(7):
            run.add(sample)

    progress = run.finish()

    assert progress["verdict"] == "refused"
    assert progress["scale_cm"] is None
    assert "north edge never ranged" in progress["reason"]
    assert "75% of the drawn perimeter observed" in progress["reason"]


def test_a_run_that_stops_early_reports_the_counters_it_had() -> None:
    dog = _WalkingDog(assumed_cm=10.0, true_cm=9.0)
    run = RoomScale(_room(), step_cm=dog.assumed_cm)
    for sample in dog.step(3):
        run.add(sample)

    progress = run.finish("operator stopped")

    assert progress["verdict"] == "refused"
    assert progress["stopped_by"] == "operator stopped"
    assert progress["scale_cm"] is None
    assert progress["counters"] == {
        "samples": 3,
        "accepted": 3,
        "invalid": 0,
        "unmatched": 0,
        "outside_room": 0,
        "refused": 0,
    }
    assert f"3/{SCALE_MIN_RANGES} ranges" in progress["reason"]


def test_walls_that_disagree_refuse_rather_than_averaging() -> None:
    """0.9 on one wall and 1.1 on another is a wrong drawing or a wrong walk, not a mean."""
    run = RoomScale(_room(), step_cm=10.0)
    for sample in _WalkingDog(assumed_cm=10.0, true_cm=9.0).step(8):
        run.add(sample)  # the north wall, at 0.9
    for sample in _WalkingDog(
        assumed_cm=10.0, true_cm=11.0, at=(200.0, 200.0), heading_deg=90.0
    ).step(8):
        run.add(sample)  # the east wall, at 1.1

    progress = run.finish()

    assert progress["verdict"] == "refused"
    assert progress["scale_cm"] is None
    assert "walls disagree" in progress["reason"]
    assert progress["criteria"]["agreement_pct"]["have"] > SCALE_AGREEMENT_PCT



def test_an_invalid_range_is_counted_and_never_fitted() -> None:
    """A missed echo still holds the last number; it is not a measurement of this wall."""
    dog = _WalkingDog(assumed_cm=10.0, true_cm=9.0)
    run = RoomScale(_room(), step_cm=dog.assumed_cm)
    for sample in _lap(dog):
        run.add(sample)
    at = (90.0, 200.0)
    assert run.add(ScaleSample(pose_cm=at, heading_deg=0.0, range_cm=float("nan"))) is False
    assert (
        run.add(ScaleSample(pose_cm=at, heading_deg=0.0, range_cm=360.0, distance_valid=False))
        is False
    )

    progress = run.finish()

    assert progress["verdict"] == "measured"
    assert progress["counters"]["invalid"] == 2
    assert progress["scale_cm"] == pytest.approx(9.0, rel=0.05)


def test_a_range_taken_outside_a_measured_room_is_counted_not_fitted() -> None:
    """In confirm mode the drawing is centimetres, so "outside it" is a fact this run can state."""
    dog = _WalkingDog(assumed_cm=10.0, true_cm=9.0)
    run = RoomScale(
        _room(size_cm={"width_cm": ROOM_CM, "depth_cm": ROOM_CM}), step_cm=dog.assumed_cm
    )
    for sample in _lap(dog):
        run.add(sample)
    assert run.add(ScaleSample(pose_cm=(500.0, 200.0), heading_deg=0.0, range_cm=300.0)) is False

    progress = run.finish()

    assert progress["counters"]["outside_room"] == 1
    assert progress["scale_cm"] == pytest.approx(9.0, rel=0.05)


def test_discovery_does_not_read_the_drawing_in_centimetres() -> None:
    """The same samples against a room drawn twice as large must name the same stride."""
    samples = _lap(_WalkingDog(assumed_cm=10.0, true_cm=9.0))

    small = RoomScale(_room(), step_cm=10.0)
    for sample in samples:
        small.add(sample)
    large_room = _room()
    large_room["polygon"] = [[0, 0], [800, 0], [800, 800], [0, 800]]
    large = RoomScale(large_room, step_cm=10.0)
    for sample in samples:
        large.add(sample)

    assert small.report()["scale_cm"] == large.report()["scale_cm"]


def test_the_run_cap_stops_the_collection_and_names_it() -> None:
    class _Clock:
        now = 0.0

        def __call__(self) -> float:
            return self.now

    clock = _Clock()
    dog = _WalkingDog(assumed_cm=10.0, true_cm=9.0)
    run = RoomScale(_room(), step_cm=dog.assumed_cm, clock=clock)
    for sample in dog.step(3):
        run.add(sample)
    clock.now = 700.0
    for sample in dog.step(3):
        assert run.add(sample) is False

    progress = run.report()

    assert progress["verdict"] == "refused"
    assert "run cap reached: 600 s" in progress["reason"]
    assert progress["counters"]["refused"] == 3


def test_a_room_with_no_polygon_is_named_rather_than_guessed() -> None:
    run = RoomScale({"id": "kitchen", "name": "Kitchen"}, step_cm=10.0)
    assert run.add(ScaleSample(pose_cm=(0.0, 0.0), heading_deg=0.0, range_cm=100.0)) is False

    progress = run.finish()

    assert progress["verdict"] == "refused"
    assert progress["reason"] == "the room has no drawn walls"


def test_the_apply_gate_is_one_policy_shared_with_step_calibrate() -> None:
    """The clamp a room run recommends is the clamp `step_calibrate --apply` enforces."""
    from houndmind_ai.navigation.odometry import (
        APPLY_CONSISTENCY,
        APPLY_MAX_FRACTION,
        APPLY_MIN_SAMPLES,
        apply_step_value,
    )
    from tools.step_calibrate import Cycle, RunReport, apply_value

    covered = [8.0, 8.1, 7.9, 8.0, 8.05]
    report = RunReport(surface="hardwood", measure="forward", speed=100, stop_at_cm=45.0)
    for index, distance in enumerate(covered):
        before = 150.0 - index * distance
        report.cycles.append(Cycle(index=index, before_cm=before, after_cm=before - distance))

    assert apply_value(report, current_cm=8.0) == apply_step_value(covered, current_cm=8.0)
    assert (APPLY_MIN_SAMPLES, APPLY_CONSISTENCY, APPLY_MAX_FRACTION) == (5, 0.10, 0.20)

