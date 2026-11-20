"""The stride a walk inside a drawn room supports — confirm it, or discover it (H4).

`navigation/odometry.py` turns counted steps into a pose by multiplying by `step_cm`, and that
constant shipped as a **guess**: 25 cm, for a body about 25 cm long (#285). Everything measured
against the pose inherits the error, so `tools/step_calibrate.py` measures the real number by walking
into a wall and watching the ultrasonic. That needs a clear run at a wall in every room a person
wants to map. A room the user drew supplies the same reference for free: the dog ranges a wall,
walks, ranges the same wall again, and **the distance the echo lost is the distance the dog gained**
(`tools/step_calibrate.py:10-13`) — measured against the room, with no tape measure and no
assumption about gait amplitude.

Two modes, and the room decides which one:

- **Confirm** — the room carries `size_cm`, so `mapping/home_map.py::scale_source_for` answers
  `"user"` and the drawing is in real centimetres. The distance from the pose to the wall being
  ranged is then a *drawn* number, and the mode compares it with the ranged one: a least-squares fit
  of range against drawn distance gives the factor the assumed stride is short or long by.
- **Discover** — no dimension exists, so the drawing's numbers are not centimetres and nothing here
  reads one as such. The dog differences its own ranges along one wall instead: the range it lost
  per dead-reckoned centimetre travelled *is* the ratio between the true stride and the assumed one.
  The drawing is still used — it says which wall was ranged, and how much of its perimeter was
  covered — but never how long anything is.

Neither mode applies anything. This is a **library, not a `Module`**: nothing ticks it, nothing is
registered in `main.build_registry`, and `mapping/__init__.py` sets the precedent. A caller feeds
samples and reads `scale_progress`; the value reaches `config/settings.jsonc` only through an
`--apply` a person runs, and that clamp lives in exactly one place
(`navigation/odometry.py::apply_step_value`), shared with `tools/step_calibrate.py`.

Frames: a sample's pose is the runtime's `(forward_cm, left_cm)`; the room is the document's
`[x = left, y = forward]`, named as a plan is read — `+y` north, `+x` east. The pose crosses through
`mapping/home_map.py::runtime_point_to_document` and nowhere else (#347), so a wall is named by the
compass direction of its outward normal and a refusal can say `north edge never ranged`.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from houndmind_ai.mapping.home_map import runtime_point_to_document, scale_source_for
from houndmind_ai.mapping.rooms import edge_distances, point_in_polygon, room_label

__all__ = [
    "SCALE_AGREEMENT_PCT",
    "SCALE_MIN_EDGES_RANGED",
    "SCALE_MIN_PERIMETER_COVERAGE",
    "SCALE_MIN_RANGES",
    "SCALE_MIN_SPREAD_CM",
    "SCALE_RUN_CAP_CM",
    "SCALE_RUN_CAP_S",
    "RoomScale",
    "ScaleSample",
]

#: Accepted ranges a run needs before it will name a stride. One echo is noise; `mapping/planner.py`
#: already treats two hits in the same cell as "a thing", and twelve is the room-sized version of it.
SCALE_MIN_RANGES = 12
#: How far apart the ranged positions have to be. Two ranges closer than this cannot separate a 10 %
#: stride error from echo noise on carpet, so they measure a ratio of nothing.
SCALE_MIN_SPREAD_CM = 150.0
#: Walls that fitted a ratio. One wall gives a ratio, not a scale: any single range fits any stride,
#: and only a second wall can disagree with the first.
SCALE_MIN_EDGES_RANGED = 2
#: Share of the drawn perimeter that has to be observed. A wall nobody ranged is a wall whose place
#: in the drawing is unproven, so the run keeps going until most of the outline is in.
SCALE_MIN_PERIMETER_COVERAGE = 0.8
#: How closely the per-wall ratios must agree, in per cent of their median. Disagreement means the
#: drawing or the stride is wrong, and a value fitted through both is a number nobody can defend.
SCALE_AGREEMENT_PCT = 5.0
#: The run extends itself until the thresholds above are met, then stops. Ten minutes is longer than
#: a room takes and short enough that a stuck dog is noticed.
SCALE_RUN_CAP_S = 600.0
#: ...and it cannot walk the house looking for evidence.
SCALE_RUN_CAP_CM = 2000.0

#: Wall names clockwise from north. The document frame is a floor plan, so a wall is called what a
#: person reading it would call it.
_WALL_NAMES = (
    "north",
    "north-east",
    "east",
    "south-east",
    "south",
    "south-west",
    "west",
    "north-west",
)


@dataclass(frozen=True)
class ScaleSample:
    """One sonar range, taken at a pose the odometry believes.

    `pose_cm` is the runtime's `(forward_cm, left_cm)` and `heading_deg` the heading it was taken at
    (0 = forward, positive = left, `navigation/odometry.py`). `distance_valid` rides beside the value
    for the reason every reading in this tree does: a sonar that missed its echo still holds the last
    number, and that number is not a measurement of this wall.
    """

    pose_cm: tuple[float, float]
    heading_deg: float
    range_cm: float
    distance_valid: bool = True


@dataclass
class _Wall:
    """One drawn edge, and the ranges attributed to it.

    A sample is kept as `(along, drawn_cm, range_cm)`: the pose's projection on the outward normal
    (what discovery differences), the drawn distance to this edge along the heading (what confirm
    compares), and the range itself.
    """

    index: int
    name: str
    a: tuple[float, float]
    b: tuple[float, float]
    normal: tuple[float, float]
    length_cm: float
    samples: list[tuple[float, float, float]] = field(default_factory=list)


def _finite(value: Any) -> float | None:
    """A finite float, or `None`. `True` is not a distance and NaN is not a reading."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _pair(value: Any) -> tuple[float, float] | None:
    """Two finite floats from a `[x, y]` pair, or `None`.

    Zero-filling would be worse than refusing: `(0, 0)` is a real place inside a room, so a pose or a
    vertex that could not be read would otherwise arrive as a measurement taken at the origin.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) < 2:
        return None
    first = _finite(value[0])
    second = _finite(value[1])
    if first is None or second is None:
        return None
    return first, second


def _polygon_points(room: Any) -> list[tuple[float, float]]:
    """A room's usable vertices, in order — the rule `mapping/rooms.py::_vertices` applies.

    That helper is private to `rooms`, and this module reads `rooms` rather than editing it, so the
    rule is restated: a vertex that cannot be read is **dropped**, never zeroed, because one bad
    corner would otherwise move the room to the origin and every wall with it.
    """
    if not isinstance(room, Mapping):
        return []
    polygon = room.get("polygon")
    if not isinstance(polygon, Sequence) or isinstance(polygon, (str, bytes)):
        return []
    points = [point for point in (_pair(vertex) for vertex in polygon) if point is not None]
    return points if len(points) >= 3 else []


def _signed_area(points: Sequence[tuple[float, float]]) -> float:
    """The polygon's signed area: its sign is how a shape says which side is out."""
    total = 0.0
    for index, (ax, ay) in enumerate(points):
        bx, by = points[(index + 1) % len(points)]
        total += ax * by - bx * ay
    return total / 2.0


def _wall_name(normal: tuple[float, float]) -> str:
    """The compass name of a wall, from the direction its outward normal points."""
    angle = math.degrees(math.atan2(normal[0], normal[1]))
    return _WALL_NAMES[int(round(angle / 45.0)) % len(_WALL_NAMES)]


def _walls(room: Any) -> list[_Wall]:
    """The room's edges, each with the outward normal its name comes from."""
    points = _polygon_points(room)
    if not points:
        return []
    sign = 1.0 if _signed_area(points) >= 0.0 else -1.0
    walls: list[_Wall] = []
    for index, a in enumerate(points):
        b = points[(index + 1) % len(points)]
        ex, ey = b[0] - a[0], b[1] - a[1]
        length = math.hypot(ex, ey)
        if length <= 0.0:
            continue  # a repeated vertex is not a wall
        # Counter-clockwise means the interior is left of `a -> b`, so the outward normal is right.
        normal = (sign * ey / length, -sign * ex / length)
        walls.append(_Wall(index, _wall_name(normal), a, b, normal, length))
    return walls


def _ray_edge(
    origin: tuple[float, float],
    direction: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float | None:
    """How far along `direction` the segment `a`-`b` is, or `None` when the ray misses it."""
    ox, oy = origin
    dx, dy = direction
    ex, ey = b[0] - a[0], b[1] - a[1]
    denominator = dx * ey - dy * ex
    if abs(denominator) < 1e-12:
        return None  # parallel to the wall
    fx, fy = a[0] - ox, a[1] - oy
    distance = (fx * ey - ex * fy) / denominator
    along = (dy * fx - dx * fy) / denominator
    if distance < 0.0 or along < -1e-9 or along > 1.0 + 1e-9:
        return None
    return distance


def _slope(points: Sequence[tuple[float, float]]) -> float | None:
    """Least-squares slope of `y` against `x`, or `None` when `x` does not spread.

    The fit `tools/step_calibrate.py::_fit` uses, for the same reason: one bad echo tilts a line a
    little instead of setting the answer.
    """
    if len(points) < 2:
        return None
    mean_x = sum(point[0] for point in points) / len(points)
    mean_y = sum(point[1] for point in points) / len(points)
    denominator = sum((point[0] - mean_x) ** 2 for point in points)
    if denominator <= 0.0:
        return None
    return sum((point[0] - mean_x) * (point[1] - mean_y) for point in points) / denominator


def _join(names: Sequence[str]) -> str:
    """`a`, `a and b`, `a, b and c` — the way a person lists walls."""
    items = [str(name) for name in names]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + f" and {items[-1]}"


class RoomScale:
    """The stride one walk inside one drawn room supports (H4).

    Construct it with the room and the stride currently assumed, hand it every sample the run takes,
    and read `report()` — nothing is published into a context and nothing moves. `finish()` is the
    same answer with the verdict closed, so a run that stopped early cannot look like one still
    collecting.
    """

    def __init__(
        self,
        room: Any,
        *,
        step_cm: float,
        surface: str = "",
        mode: str | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._room = room if isinstance(room, Mapping) else {}
        self._walls = _walls(room)
        self._surface = surface.strip() if isinstance(surface, str) else ""
        assumed = _finite(step_cm)
        self._step_cm = assumed if assumed is not None and assumed > 0.0 else 0.0
        measured = scale_source_for([self._room]) == "user"
        # A room with no dimension cannot be confirmed — there is nothing to confirm against — so a
        # caller asking for `confirm` on one is answered with discovery, and `mode` in the report
        # says which ran. Discovery may be asked for on a measured room: a dimension the user typed
        # is not proof, which is the whole reason this run exists.
        self._mode = "discover" if mode == "discover" or not measured else "confirm"
        self._clock = clock or time.monotonic
        self._started = self._clock()
        self._last_pose: tuple[float, float] | None = None
        self._travelled_cm = 0.0
        self._samples = 0
        self._accepted = 0
        self._invalid = 0
        self._unmatched = 0
        self._outside = 0
        self._refused_samples = 0
        self._finished = False
        self._stop_reason = ""

    def add(self, sample: ScaleSample) -> bool:
        """Take one sample; `True` when it was a range against one of this room's walls."""
        self._samples += 1
        if self._finished or self._cap_reason() is not None:
            self._refused_samples += 1
            return False
        pose = _pair(sample.pose_cm)
        if pose is None:
            self._invalid += 1
            return False
        document = runtime_point_to_document(pose)
        if self._last_pose is not None:
            self._travelled_cm += math.hypot(
                document[0] - self._last_pose[0], document[1] - self._last_pose[1]
            )
        self._last_pose = document
        if not sample.distance_valid:
            self._invalid += 1
            return False
        ranged = _finite(sample.range_cm)
        if ranged is None or ranged <= 0.0:
            self._invalid += 1
            return False
        drawn = edge_distances(document, self._room)
        if drawn is None:
            self._invalid += 1  # `None`, never zero: an unusable distance is not evidence
            return False
        if self._mode == "confirm" and not point_in_polygon(
            document, self._room.get("polygon")
        ):
            # Only a measured room is in centimetres, so "inside it" is a fact here - and
            # meaningless in `discover`, where the drawing has no scale to be inside of.
            self._outside += 1
            return False
        hit = self._hit(document, sample.heading_deg)
        if hit is None:
            self._unmatched += 1
            return False
        wall, distance = hit
        along = document[0] * wall.normal[0] + document[1] * wall.normal[1]
        wall.samples.append((along, distance, ranged))
        self._accepted += 1
        return True

    def finish(self, reason: str = "") -> dict[str, Any]:
        """Close the run and return the report it publishes.

        A run that stops early reports the counters it had rather than a value it cannot defend: the
        verdict becomes `refused` and `reason` names the criterion that was still short.
        """
        self._finished = True
        self._stop_reason = reason.strip() if isinstance(reason, str) else ""
        return self.report()

    def report(self) -> dict[str, Any]:
        """`scale_progress`: the counters, the per-wall ratios, and one verdict.

        While the run is open the verdict is `collecting` and `reason` names what is still missing;
        once it is closed — `finish()`, or a cap — that same string is the refusal. `measured` means
        the *run* produced a value, not that the configuration changed: `step_cm_source` stays
        `assumed` until an `--apply` writes one.
        """
        assessed = self._assess()
        problems = self._problems(assessed)
        if not problems:
            verdict = "measured"
        elif self._finished or self._cap_reason() is not None:
            verdict = "refused"
        else:
            verdict = "collecting"
        return {
            "mode": self._mode,
            "verdict": verdict,
            "reason": "; ".join(problems) if problems else None,
            "room": room_label(self._room),
            "surface": self._surface or None,
            "step_cm": round(self._step_cm, 2),
            "ratio": assessed["ratio"],
            # A value is published only when the run measured one. A refused or collecting run
            # keeps its per-wall ratios for the report, and no number a caller could apply.
            "scale_cm": None if problems else assessed["scale_cm"],
            "walls": assessed["walls"],
            "counters": {
                "samples": self._samples,
                "accepted": self._accepted,
                "invalid": self._invalid,
                "unmatched": self._unmatched,
                "outside_room": self._outside,
                "refused": self._refused_samples,
            },
            "criteria": self._criteria(assessed),
            "stopped_by": self._stop_reason or None,
            "elapsed_s": round(self._elapsed(), 1),
            "travelled_cm": round(self._travelled_cm, 1),
        }

    def _hit(self, origin: tuple[float, float], heading_deg: Any) -> tuple[_Wall, float] | None:
        """The nearest drawn wall the sonar was pointed at, and the drawn distance to it."""
        heading = _finite(heading_deg)
        radians = math.radians(heading if heading is not None else 0.0)
        # The runtime's heading is 0 = forward, positive = left, and the document's `+x` is the dog's
        # left, so a left turn sends the ray towards `+x`.
        direction = (math.sin(radians), math.cos(radians))
        best: tuple[_Wall, float] | None = None
        for wall in self._walls:
            distance = _ray_edge(origin, direction, wall.a, wall.b)
            if distance is None:
                continue
            if best is None or distance < best[1]:
                best = (wall, distance)
        return best

    def _assess(self) -> dict[str, Any]:
        """The per-wall fits and the run-level numbers the verdict is read from."""
        perimeter = sum(wall.length_cm for wall in self._walls)
        ranged_length = 0.0
        fitted: list[tuple[str, float]] = []
        unfitted: list[str] = []
        walls: list[dict[str, Any]] = []
        ranges: list[float] = []
        for wall in self._walls:
            if self._mode == "confirm":
                points = [(drawn, ranged) for _along, drawn, ranged in wall.samples]
            else:
                points = [(along, ranged) for along, _drawn, ranged in wall.samples]
            slope = _slope(points)
            ratio: float | None = None
            if slope is not None:
                # Discovery: the range falls as the dog advances along the outward normal, so the
                # slope is negative and the stride ratio is its magnitude. Confirm: the drawn
                # distance grows exactly as the range does, so the slope *is* the ratio.
                candidate = slope if self._mode == "confirm" else -slope
                ratio = candidate if candidate > 0.0 else None
            ranges.extend(ranged for _along, _drawn, ranged in wall.samples)
            if wall.samples:
                ranged_length += wall.length_cm
            if wall.samples and ratio is None:
                unfitted.append(wall.name)
            if ratio is not None:
                fitted.append((wall.name, ratio))
            walls.append(
                {
                    "index": wall.index,
                    "name": wall.name,
                    "length_cm": round(wall.length_cm, 1),
                    "ranges": len(wall.samples),
                    "ratio": None if ratio is None else round(ratio, 4),
                }
            )
        values = sorted(ratio for _name, ratio in fitted)
        # The middle of an odd count, the upper middle of an even one — the convention
        # `navigation/odometry.py::apply_step_value` uses, so two callers cannot average differently.
        median = values[len(values) // 2] if values else None
        agreement = None
        if len(values) >= 2 and median:
            agreement = (values[-1] - values[0]) / median * 100.0
        scale = None
        if median is not None and self._step_cm > 0.0:
            scale = round(self._step_cm * median, 2)
        return {
            "walls": walls,
            "fitted": fitted,
            "unfitted": unfitted,
            "ratios": values,
            "agreement_pct": agreement,
            "spread_cm": (max(ranges) - min(ranges)) if ranges else 0.0,
            "coverage": (ranged_length / perimeter) if perimeter > 0.0 else 0.0,
            "scale_cm": scale,
            "ratio": None if median is None else round(median, 4),
            "missing": [wall.name for wall in self._walls if not wall.samples],
        }

    def _problems(self, assessed: dict[str, Any]) -> list[str]:
        """The criteria this run has not met, in the order a person would read them."""
        if not self._walls:
            return ["the room has no drawn walls"]
        problems: list[str] = []
        missing = assessed["missing"]
        if missing:
            plural = "s" if len(missing) > 1 else ""
            problems.append(f"{_join(missing)} edge{plural} never ranged")
        for name in assessed["unfitted"]:
            problems.append(f"the {name} wall's ranges do not fit a stride")
        fitted = len(assessed["ratios"])
        if fitted < SCALE_MIN_EDGES_RANGED:
            plural = "s" if fitted != 1 else ""
            problems.append(f"{fitted} wall{plural} fitted a ratio, {SCALE_MIN_EDGES_RANGED} needed")
        coverage = assessed["coverage"]
        if coverage < SCALE_MIN_PERIMETER_COVERAGE:
            problems.append(
                f"{coverage:.0%} of the drawn perimeter observed, "
                f"{SCALE_MIN_PERIMETER_COVERAGE:.0%} needed"
            )
        if self._accepted < SCALE_MIN_RANGES:
            problems.append(f"{self._accepted}/{SCALE_MIN_RANGES} ranges")
        spread = assessed["spread_cm"]
        if spread < SCALE_MIN_SPREAD_CM:
            problems.append(f"ranged spread {spread:.0f} cm, {SCALE_MIN_SPREAD_CM:.0f} cm needed")
        agreement = assessed["agreement_pct"]
        if fitted >= SCALE_MIN_EDGES_RANGED and agreement is not None:
            if agreement > SCALE_AGREEMENT_PCT:
                listed = ", ".join(f"{name} {ratio:.2f}" for name, ratio in assessed["fitted"])
                problems.append(f"walls disagree beyond {SCALE_AGREEMENT_PCT:g}%: {listed}")
        capped = self._cap_reason()
        if capped is not None:
            problems.append(capped)
        return problems

    def _criteria(self, assessed: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Every constant with how far this run has got against it, so a console can show progress."""
        fitted = len(assessed["ratios"])
        agreement = assessed["agreement_pct"]
        coverage = assessed["coverage"]
        spread = assessed["spread_cm"]
        elapsed = self._elapsed()
        return {
            "min_ranges": {
                "needed": SCALE_MIN_RANGES,
                "have": self._accepted,
                "met": self._accepted >= SCALE_MIN_RANGES,
            },
            "min_spread_cm": {
                "needed": SCALE_MIN_SPREAD_CM,
                "have": round(spread, 1),
                "met": spread >= SCALE_MIN_SPREAD_CM,
            },
            "min_edges_ranged": {
                "needed": SCALE_MIN_EDGES_RANGED,
                "have": fitted,
                "met": fitted >= SCALE_MIN_EDGES_RANGED,
            },
            "min_perimeter_coverage": {
                "needed": SCALE_MIN_PERIMETER_COVERAGE,
                "have": round(coverage, 3),
                "met": coverage >= SCALE_MIN_PERIMETER_COVERAGE,
            },
            "agreement_pct": {
                "needed": SCALE_AGREEMENT_PCT,
                "have": None if agreement is None else round(agreement, 2),
                "met": agreement is not None and agreement <= SCALE_AGREEMENT_PCT,
            },
            "run_cap_s": {
                "needed": SCALE_RUN_CAP_S,
                "have": round(elapsed, 1),
                "met": elapsed < SCALE_RUN_CAP_S,
            },
            "run_cap_cm": {
                "needed": SCALE_RUN_CAP_CM,
                "have": round(self._travelled_cm, 1),
                "met": self._travelled_cm < SCALE_RUN_CAP_CM,
            },
        }

    def _cap_reason(self) -> str | None:
        """Why the run may not take another sample, or `None` while it may."""
        if self._elapsed() >= SCALE_RUN_CAP_S:
            return f"run cap reached: {SCALE_RUN_CAP_S:g} s"
        if self._travelled_cm >= SCALE_RUN_CAP_CM:
            return f"run cap reached: {SCALE_RUN_CAP_CM:g} cm walked"
        return None

    def _elapsed(self) -> float:
        return max(0.0, self._clock() - self._started)

