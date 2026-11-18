"""Walk a planned route, one waypoint at a time (#306).

`mapping/planner.py` answers "which way"; this module is what walks it. Three rules shape it.

1. **A route is a goal, not a pilot.** It publishes one ordinary `Source.ROUTE` intent per cycle and
   the gateway, the interlock and the obstacle stop judge every step exactly as they judge a hand.
   The planner's clearance column is advice; the live sonar still has the last word.
2. **No pose, no route.** A route is drawn in map coordinates, so without a pose the dog cannot say
   where along it it is. Planning from the `reactive` tier is refused by name rather than walked
   blind, which is the same rule the place navigator applies to a goal it cannot verify.
3. **Arrival is a pose, not a step count.** A waypoint is reached when the dog's pose is within
   `tolerance_cm` of it. The place navigator counts accepted steps because a place is a polar
   vector; a route is a Cartesian point, so the pose is the only comparable thing.

At each arrival the follower takes **one** look at `place_match`. If the camera has confirmed a
place, that id is recorded on the route: the correction itself is `place_recognition`'s job (it
publishes `place_fix` and re-anchors odometry), and re-planning from a corrected pose is the next
session's work — this module never moves the dog on the strength of a view.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.commands import Source
from houndmind_ai.mapping.planner import plan_route

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_TOLERANCE_CM", "RouteFollowerModule"]

DEFAULT_TOLERANCE_CM = 12.0
DEFAULT_HEADING_TOLERANCE_DEG = 20.0
DEFAULT_TIMEOUT_S = 300.0

_PUBLISH = "publish"
_SETTLE = "settle"
_WALKING = "walking"
_DONE = "done"
_REFUSED = "refused"


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pose(context) -> dict | None:
    """The pose, when there is one to navigate from.

    `reactive` is the tier that says "I do not know where I am", so a pose from it is not a pose;
    a `null` pose with a tier that claims one is treated the same way.
    """
    localization = context.get("localization")
    if not isinstance(localization, dict):
        return None
    if localization.get("tier") == "reactive":
        return None
    pose = localization.get("pose")
    if not isinstance(pose, dict):
        return None
    return pose


def _bearing_deg(pose: dict, waypoint: dict) -> float:
    """The signed turn to face a waypoint, in [-180, 180): positive is right, the tree's convention."""
    dx = _safe_float(waypoint.get("x_cm"), 0.0) - _safe_float(pose.get("x"), 0.0)
    dy = _safe_float(waypoint.get("y_cm"), 0.0) - _safe_float(pose.get("y"), 0.0)
    target = math.degrees(math.atan2(dy, dx))
    return (target - _safe_float(pose.get("yaw_deg"), 0.0) + 180.0) % 360.0 - 180.0


def _distance_cm(pose: dict, waypoint: dict) -> float:
    return math.hypot(
        _safe_float(waypoint.get("x_cm"), 0.0) - _safe_float(pose.get("x"), 0.0),
        _safe_float(waypoint.get("y_cm"), 0.0) - _safe_float(pose.get("y"), 0.0),
    )


class RouteFollowerModule(Module):
    """Plan one route on request, then walk it waypoint by waypoint through the gateway."""

    def __init__(
        self, name: str, enabled: bool = True, required: bool = False, **kwargs: object
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.route: dict[str, Any] | None = None
        self._phase = _PUBLISH
        self._started_at = 0.0
        self._clock = time.monotonic

    def _section(self, context) -> dict:
        section = (context.get("settings") or {}).get("route_follower", {})
        return section if isinstance(section, dict) else {}

    def tick(self, context) -> None:
        self._accept_request(context)
        route = self.route
        if route is None or route["state"] in (_DONE, _REFUSED):
            return
        self._advance(context, route)

    # ---- the request -------------------------------------------------------

    def _accept_request(self, context) -> None:
        """Take one `route_request`, plan it, and publish the route or the refusal that ended it.

        The request is `{"goal_cm": {"x_cm": ..., "y_cm": ...}}`. Planning is the only place a route
        begins: a module that also accepted a hand-written waypoint list would let a client skip the
        clearance check the planner exists to do.
        """
        request = context.get("route_request")
        if not isinstance(request, dict):
            return
        context.set("route_request", None)
        goal = request.get("goal_cm")
        if not isinstance(goal, dict):
            self._refuse(context, "bad_request", "route_request needs a goal_cm with x_cm and y_cm")
            return
        pose = _pose(context)
        if pose is None:
            self._refuse(
                context,
                "no_pose",
                "a route is drawn in map coordinates and the dog has no pose to place itself on; "
                "localization is reactive",
            )
            return
        if context.get("intent_board") is None:
            self._refuse(context, "no_board", "no intent board in the context")
            return

        mapping_settings = (context.get("settings") or {}).get("mapping", {}) or {}
        grid = context.get("home_map") or {}
        cells = (grid.get("grid") or {}).get("cells") if isinstance(grid, dict) else None
        if cells is None:
            mapped = context.get("mapping_state") or {}
            cells = (mapped.get("grid") or {}).get("cells") if isinstance(mapped, dict) else {}
        start = (_safe_float(pose.get("x"), 0.0), _safe_float(pose.get("y"), 0.0))
        target = (_safe_float(goal.get("x_cm"), 0.0), _safe_float(goal.get("y_cm"), 0.0))

        plan = plan_route(cells or {}, start, target, mapping_settings)
        if not plan.ok:
            self._refuse(context, plan.refusal or "no_path", plan.detail or "no route")
            return

        tolerance = max(0.0, _safe_float(self._section(context).get("tolerance_cm"), DEFAULT_TOLERANCE_CM))
        waypoints = [waypoint.to_dict() for waypoint in plan.waypoints]
        # The planner starts at the cell the dog already occupies, so its first waypoint is usually
        # under its feet. Dropping it keeps `index` meaning "the next thing to walk to" rather than
        # spending a tick arriving where it already is.
        while waypoints and _distance_cm(pose, waypoints[0]) <= tolerance:
            waypoints.pop(0)

        self._phase = _PUBLISH
        self._started_at = self._clock()
        self.route = {
            "state": _DONE if not waypoints else _WALKING,
            "index": 0,
            "total": len(waypoints),
            "waypoints": waypoints,
            "goal_cm": {"x_cm": target[0], "y_cm": target[1]},
            "refusal": None,
            "detail": None,
            "place": None,
            "ts": time.time(),
        }
        context.set("route", self.route)
        logger.info(
            "Route planned: %d waypoint(s) to (%.0f, %.0f) cm",
            len(waypoints),
            target[0],
            target[1],
        )


    def _refuse(self, context, reason: str, detail: str) -> None:
        """Record a refused request. The dog does not move, and the reason is readable."""
        self.route = {
            "state": _REFUSED,
            "index": 0,
            "total": 0,
            "waypoints": [],
            "goal_cm": None,
            "refusal": reason,
            "detail": detail,
            "place": None,
            "ts": time.time(),
        }
        self._phase = _PUBLISH
        context.set("route", self.route)
        logger.warning("Route refused (%s): %s", reason, detail)

    # ---- one step ----------------------------------------------------------

    def _advance(self, context, route: dict) -> None:
        """Settle the step already published, or decide and publish the next one."""
        if self._phase == _SETTLE:
            self._retract(context)
            self._phase = _PUBLISH
            return
        self._publish(context, route)

    def _publish(self, context, route: dict) -> None:
        """Arrival, a turn, a step forward, or an end — one decision per cycle."""
        settings = self._section(context)
        tolerance = max(0.0, _safe_float(settings.get("tolerance_cm"), DEFAULT_TOLERANCE_CM))
        heading_tolerance = _safe_float(
            settings.get("heading_tolerance_deg"), DEFAULT_HEADING_TOLERANCE_DEG
        )
        timeout_s = _safe_float(settings.get("timeout_s"), DEFAULT_TIMEOUT_S)

        pose = _pose(context)
        if pose is None:
            self._end(context, _REFUSED, "no_pose", "the pose went away mid-route")
            return
        if timeout_s > 0 and self._clock() - self._started_at > timeout_s:
            self._end(context, _REFUSED, "timeout", f"no arrival inside {timeout_s:.0f} s")
            return

        waypoints = route.get("waypoints") or []
        index = int(route.get("index") or 0)
        if index >= len(waypoints):
            self._end(context, _DONE, None, None)
            return
        waypoint = waypoints[index]

        if _distance_cm(pose, waypoint) <= tolerance:
            self._arrive(context, route)
            return
        error = _bearing_deg(pose, waypoint)
        if abs(error) > heading_tolerance:
            self._emit(context, "turn_right" if error > 0 else "turn_left")
            return
        self._emit(context, "forward")

    def _arrive(self, context, route: dict) -> None:
        """Count the waypoint, take one look at the camera's answer, and move on."""
        index = int(route.get("index") or 0) + 1
        # One look, at the arrival tick only: the follower does not poll the matcher, and it never
        # re-plans on a view - the correction belongs to `place_recognition`, which owns the pose.
        match = context.get("place_match")
        place = match.get("place_id") if isinstance(match, dict) and match.get("valid") else None
        route = {
            **route,
            "index": index,
            "place": place or route.get("place"),
            "ts": time.time(),
        }
        self.route = route
        context.set("route", route)
        if index >= len(route.get("waypoints") or []):
            self._end(context, _DONE, None, None)
            return
        logger.info("Route waypoint %d/%d reached", index, len(route.get("waypoints") or []))

    def _end(self, context, state: str, refusal: str | None, detail: str | None) -> None:
        self._retract(context)
        self._phase = _PUBLISH
        route = {
            **(self.route or {}),
            "state": state,
            "refusal": refusal,
            "detail": detail,
            "ts": time.time(),
        }
        self.route = route
        context.set("route", route)
        if state == _REFUSED:
            logger.warning("Route ended (%s): %s", refusal, detail)
        else:
            logger.info("Route finished: %d waypoint(s)", int(route.get("index") or 0))

    # ---- board -------------------------------------------------------------

    def _emit(self, context, action: str) -> None:
        """Publish one step for `Source.ROUTE` and move to the settle phase."""
        board = context.get("intent_board")
        if board is None:
            return
        board.publish(action, Source.ROUTE)
        self._phase = _SETTLE

    def _retract(self, context) -> None:
        """Withdraw the route intent now: the gateway turns that into `motion_command: None`."""
        board = context.get("intent_board")
        if board is not None:
            board.retract(Source.ROUTE)

