"""The route hand-off: plan once, walk waypoint by waypoint, refuse what cannot be walked (#306).

The board is the real one — `kernel/intents.IntentBoard` holds no hardware — so these tests assert
exactly what the gateway would see: which source published, which action, and that the intent is
retracted between steps. Nothing here touches the HAL.
"""

from __future__ import annotations

from houndmind_ai.core.runtime import RuntimeContext
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.intents import IntentBoard
from houndmind_ai.navigation.route_follower import RouteFollowerModule

__all__ = [
    "test_a_request_is_planned_and_published_as_a_route",
    "test_planning_from_reactive_is_refused_and_publishes_nothing",
    "test_a_goal_inside_an_obstacle_carries_the_planner_refusal",
    "test_a_goal_inside_a_keep_out_room_is_never_walked",
    "test_a_walk_through_a_keep_out_room_is_refused_before_it_starts",
    "test_a_malformed_request_is_refused_by_name",
    "test_it_walks_forward_when_the_bearing_is_right",
    "test_it_turns_before_it_walks",
    "test_the_intent_is_retracted_between_steps",
    "test_arrival_advances_the_waypoint_without_an_intent",
    "test_the_last_arrival_finishes_the_route",
    "test_one_look_at_the_camera_per_arrival",
    "test_a_route_that_never_arrives_times_out",
]


class _Clock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _context(
    *,
    tier: str = "dead_reckoning",
    x_cm: float = 0.0,
    y_cm: float = 0.0,
    yaw_deg: float = 0.0,
    cells: dict | None = None,
    **settings: object,
) -> tuple[RouteFollowerModule, RuntimeContext, _Clock]:
    clock = _Clock()
    module = RouteFollowerModule("route_follower", enabled=True)
    module._clock = clock
    context = RuntimeContext()
    context.set(
        "settings",
        {
            "route_follower": {"tolerance_cm": 12.0, "timeout_s": 300.0, **settings},
            "mapping": {"cell_size_cm": 10.0, "grid_size": [100, 100]},
        },
    )
    context.set("intent_board", IntentBoard())
    if tier == "reactive":
        context.set("localization", {"tier": "reactive", "pose": None})
    else:
        context.set(
            "localization",
            {"tier": tier, "pose": {"x": x_cm, "y": y_cm, "yaw_deg": yaw_deg}},
        )
    context.set("mapping_state", {"grid": {"cells": cells or {}}})
    return module, context, clock


def _request(context: RuntimeContext, x_cm: float, y_cm: float) -> None:
    context.set("route_request", {"goal_cm": {"x_cm": x_cm, "y_cm": y_cm}})


def test_a_goal_inside_a_keep_out_room_is_never_walked() -> None:
    """#353: the refusal lives where the walking happens, not only in the console's preview.

    A room polygon is a **document** shape (`[x = left, y = forward]`), so this is also the test that the
    follower swaps before it asks - a runtime point tested against a document polygon would miss.
    """
    module, context, _ = _context()
    context.set(
        "home_map",
        {
            "rooms": [
                {
                    "id": "stairs",
                    "name": "stairs",
                    "keep_out": True,
                    "polygon": [[-50, 40], [50, 40], [50, 160], [-50, 160]],
                }
            ]
        },
    )
    # forward 100 / left 0 is document (0, 100): inside the room.
    _request(context, 100.0, 0.0)

    module.tick(context)

    route = context.get("route")
    assert route["state"] == "refused"
    assert route["refusal"] == "goal_in_keep_out"
    assert "stairs" in (route["detail"] or "")
    assert _actions(context) == [], "a refused goal publishes no motion"


def test_a_walk_through_a_keep_out_room_is_refused_before_it_starts() -> None:
    """Neither end is in the room; the straight run between them is."""
    module, context, _ = _context()
    context.set(
        "home_map",
        {
            "rooms": [
                {
                    "id": "stairs",
                    "name": "stairs",
                    "keep_out": True,
                    "polygon": [[-50, 80], [50, 80], [50, 120], [-50, 120]],
                }
            ]
        },
    )
    _request(context, 200.0, 0.0)

    module.tick(context)

    assert context.get("route")["refusal"] == "route_in_keep_out"
    assert _actions(context) == []


def _actions(context: RuntimeContext) -> list[str]:
    board = context.get("intent_board")
    return [command.action for command in board.latest() if command.source is Source.ROUTE]


def _route(index: int = 0, total: int = 2) -> dict:
    return {
        "state": "walking",
        "index": index,
        "total": total,
        "waypoints": [
            {"x_cm": 50.0, "y_cm": 0.0, "clearance_cm": None},
            {"x_cm": 100.0, "y_cm": 0.0, "clearance_cm": None},
        ][:total],
        "goal_cm": {"x_cm": 100.0, "y_cm": 0.0},
        "refusal": None,
        "detail": None,
        "place": None,
        "ts": 0.0,
    }

def test_a_request_is_planned_and_published_as_a_route() -> None:
    module, context, _ = _context()

    _request(context, 100.0, 0.0)
    module.tick(context)

    route = context.get("route")
    assert route["state"] == "walking"
    assert route["index"] == 0
    assert route["total"] == 1, "the waypoint under the dog's feet is not one to walk to"
    assert route["waypoints"][-1] == {"x_cm": 100.0, "y_cm": 0.0, "clearance_cm": None}
    assert context.get("route_request") is None, "a request is consumed once"


def test_planning_from_reactive_is_refused_and_publishes_nothing() -> None:
    """A route is drawn in map coordinates; with no pose there is no 'along it' to be at."""
    module, context, _ = _context(tier="reactive")

    _request(context, 100.0, 0.0)
    module.tick(context)

    route = context.get("route")
    assert route["state"] == "refused"
    assert route["refusal"] == "no_pose"
    assert _actions(context) == []


def test_a_goal_inside_an_obstacle_carries_the_planner_refusal() -> None:
    module, context, _ = _context(cells={"0,10": 3})

    _request(context, 100.0, 0.0)
    module.tick(context)

    route = context.get("route")
    assert route["refusal"] == "goal_blocked"
    assert "obstacle" in route["detail"]


def test_a_malformed_request_is_refused_by_name() -> None:
    module, context, _ = _context()

    context.set("route_request", {"goal": [1, 2]})
    module.tick(context)

    assert context.get("route")["refusal"] == "bad_request"


def test_it_walks_forward_when_the_bearing_is_right() -> None:
    module, context, _ = _context()

    _request(context, 100.0, 0.0)
    module.tick(context)

    assert _actions(context) == ["forward"]


def test_it_turns_before_it_walks() -> None:
    """Facing +y with the goal at +x is a 90 degree turn, and this tree calls that a left one."""
    module, context, _ = _context(yaw_deg=90.0)

    _request(context, 100.0, 0.0)
    module.tick(context)

    assert _actions(context) == ["turn_left"]


def test_the_intent_is_retracted_between_steps() -> None:
    module, context, _ = _context()

    _request(context, 100.0, 0.0)
    module.tick(context)
    assert _actions(context) == ["forward"]

    module.tick(context)

    assert _actions(context) == [], "the settle tick withdraws what it published"


def test_arrival_advances_the_waypoint_without_an_intent() -> None:
    module, context, _ = _context(x_cm=50.0)
    module.route = _route()

    module.tick(context)

    assert context.get("route")["index"] == 1
    assert _actions(context) == []


def test_the_last_arrival_finishes_the_route() -> None:
    module, context, _ = _context(x_cm=100.0)
    module.route = _route(index=1)

    module.tick(context)

    route = context.get("route")
    assert route["state"] == "done"
    assert route["index"] == 2
    assert _actions(context) == []


def test_one_look_at_the_camera_per_arrival() -> None:
    """The follower records the confirmation; it never moves the dog on the strength of a view."""
    module, context, _ = _context(x_cm=50.0)
    context.set(
        "place_match", {"valid": True, "place_id": "kitchen", "score": 0.8, "reason": None}
    )
    module.route = _route()

    module.tick(context)

    assert context.get("route")["place"] == "kitchen"


def test_a_route_that_never_arrives_times_out() -> None:
    module, context, clock = _context(timeout_s=10.0)

    _request(context, 100.0, 0.0)
    module.tick(context)

    clock.advance(11.0)
    module.tick(context)  # settle
    module.tick(context)  # decide again, past the deadline

    route = context.get("route")
    assert route["refusal"] == "timeout"
    assert route["state"] == "refused"

