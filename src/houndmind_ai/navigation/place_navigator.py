"""Walk to a named place: orient to its heading, then advance its distance.

A place is a polar pose taught by a person (`kernel/place.py`): a heading and a distance from an
anchor, plus the confidence and visit count that record how often the dog has actually got there.
This module is the least clever producer in the tree, deliberately — it publishes one ordinary
`Source.PLACE` intent per cycle and lets the gateway, the interlock and the obstacle stop judge
every step exactly as they judge a command from a hand.

Three rules shape it.

1. **A goal yields to a hazard.** `Source.PLACE = 17` sits under `NAVIGATION = 20`
   (`kernel/commands.py`), so while the reactive navigator is avoiding an obstacle it wins the
   tick and the goal waits. The two producers were never put in one slot: sharing
   `Source.NAVIGATION` would have made them take turns and the dog stutter between a goal and an
   avoidance.
2. **Arrival is dead reckoning, and it says so.** Nothing in this stack measures how far the dog
   walked, so the only honest distance is the one the gateway accepted: each accepted `forward`
   counts `settings.places.step_cm`. That is a calibrated guess, not an odometry — PL7 on the
   device is where `step_cm` gets measured instead of assumed, together with which way a positive
   yaw actually turns a PiDog.
3. **The anchor is a precondition, not a formality.** A stored distance was measured from the pose
   the dog stood at when the place was taught, and nothing at L0 can verify that pose. So the
   request must *say* the dog is at the anchor (`at_anchor: true`) and the place's anchor must be
   the one the runtime navigates in. Otherwise the navigator refuses with a reason rather than
   walking a vector it cannot confirm — the rule the sensors follow, applied to a pose.

Pacing is the routine runner's (`behavior/routine_runner.py`): publish, settle for one tick,
retract, decide again. The gateway drops a repeat of a command it already ran and the motors do
too, so a retraction between steps is what makes the second `forward` a step rather than a no-op.

No I/O at import time: the store is built in `start`, and the file is read **per request**, so a
place created after boot is usable without one.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from difflib import get_close_matches
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.place import DEFAULT_ANCHOR, DEFAULT_CONFIDENCE_STEP, Place
from houndmind_ai.kernel.place_store import DEFAULT_PLACES_PATH, PlaceStore

__all__ = ["PLACE_GOAL_STATES", "PlaceGoal", "PlaceNavigatorModule", "heading_error"]

logger = logging.getLogger(__name__)

# The goal's whole vocabulary. `to_dict` is the only place it reaches a wire, so a client cannot be
# shown a fifth word some future branch invented.
TRAVELLING = "travelling"
ARRIVED = "arrived"
ABANDONED = "abandoned"
REFUSED = "refused"
PLACE_GOAL_STATES = frozenset({TRAVELLING, ARRIVED, ABANDONED, REFUSED})

# The two phases of one step: `publish` puts the step on the board, `settle` reads the gateway's
# answer and retracts, which is what makes the *next* step (even an identical one) a new command.
_PUBLISH = "publish"
_SETTLE = "settle"

DEFAULT_TOLERANCE_CM = 15.0
DEFAULT_TURN_TOLERANCE_DEG = 8.0
DEFAULT_STEP_CM = 25.0
DEFAULT_TIMEOUT_S = 120.0

_FORWARD = "forward"
_STOP = "stop"

# Derived, not spelled: the gateway writes `source.name.lower()` into the command payload, so a
# literal here would be a second definition of the spelling.
_PLACE_SOURCE = Source.PLACE.name.lower()


def _safe_float(value: Any, default: float) -> float:
    """A number from config or the context, or the default. Never `float(x)` bare."""
    if value is None or isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _places_settings(context) -> Mapping[str, Any]:
    """`settings.places`, or an empty mapping when the section is missing or the wrong shape."""
    settings = context.get("settings") or {}
    section = settings.get("places") if isinstance(settings, Mapping) else None
    return section if isinstance(section, Mapping) else {}


def heading_error(target_deg: float, current_deg: float) -> float:
    """The shortest signed turn from `current_deg` to `target_deg`, in [-180, 180).

    Positive reads as "turn right" because that is the convention the tree already uses
    (`navigation/local_planner.py:63-67` reads a positive yaw the same way). Which way a positive
    gyro yaw actually turns a PiDog is a device question, and PL7 answers it.
    """
    return (target_deg - current_deg + 180.0) % 360.0 - 180.0


def _current_heading(context) -> float | None:
    """`current_heading` when the orientation module published one, else None.

    `None` is the whole point: a navigator that cannot tell where it is facing must not guess a
    turn, the same way a sensor that did not answer is not a reading of zero.
    """
    raw = context.get("current_heading")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value % 360.0

def _request(request: object) -> tuple[str, bool]:
    """`(handle, at_anchor)` from a request, or `("", False)` for a request that is not a table."""
    if not isinstance(request, Mapping):
        return "", False
    handle = request.get("id")
    return (handle.strip() if isinstance(handle, str) else ""), request.get("at_anchor") is True


def _closest(handle: str, places: tuple[Place, ...]) -> str | None:
    """The place a user most likely meant, so a refusal suggests instead of only denying."""
    handles: list[str] = []
    for place in places:
        handles.extend((place.id, place.name))
    matches = get_close_matches(handle, handles, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _veto(context) -> str | None:
    """The first refusal aimed at a place intent this tick, if any.

    `motion_verdict` is not enough: it carries the *winner's* answer, so a refused place step
    leaves nothing in it. The decision record keeps a refusal per intent with its source
    (`act/gateway.py::_record`), which is the only place that still names the loser — the route
    `routine_runner._routine_veto` takes for the same reason.
    """
    record = context.get("decision_record")
    for veto in getattr(record, "vetoes", ()) or ():
        if getattr(veto, "source", None) == _PLACE_SOURCE:
            return str(getattr(veto, "reason", "") or "refused")
    return None


@dataclass(frozen=True)
class PlaceGoal:
    """One trip, as it stands: the place, what has been walked, and how it ended.

    `last_command_id` is what makes a step countable exactly once: the gateway leaves an accepted
    command in the context across ticks, so counting per tick would walk the dog to its place
    without it having moved.
    """

    place: Place
    started: float
    walked_cm: float = 0.0
    state: str = TRAVELLING
    reason: str | None = None
    action: str | None = None
    heading_error_deg: float | None = None
    veto: str | None = None
    last_command_id: str | None = None

    def to_dict(self, now: float) -> dict[str, object]:
        """The shape `/state` and the WS carry, for a client that wants to show progress."""
        return {
            "id": self.place.id,
            "name": self.place.name,
            "state": self.state,
            "action": self.action,
            "reason": self.reason,
            "veto": self.veto,
            "heading_error_deg": self.heading_error_deg,
            "walked_cm": round(self.walked_cm, 1),
            "distance_cm": self.place.distance_cm,
            "elapsed_s": round(max(0.0, now - self.started), 2),
            "visits": self.place.visits,
            "confidence": self.place.confidence,
        }



class PlaceNavigatorModule(Module):
    """Turns one `place_request` into ordinary motion intents, one step at a time.

    `start` builds the store, `tick` reads the request and then walks the goal forward by one
    command per two ticks. The module's own state is the goal; there is no second copy of the
    places list, so a place added after boot is found on the next request.
    """

    def __init__(
        self,
        name: str = "place_navigator",
        enabled: bool = True,
        required: bool = False,
        store: PlaceStore | None = None,
        clock: Callable[[], float] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        # Unknown kwargs are tolerated on purpose: `main.cfg()` hands over a whole config section,
        # and a key this module does not know must not take the runtime down (20-hardware rule).
        self.store = store
        self.goal: PlaceGoal | None = None
        # A refused request has no place, so its answer cannot be a `PlaceGoal`; it is kept apart
        # and published under the same context key, so a client reads one shape either way.
        self._rejection: dict[str, object] | None = None
        self._clock = clock or time.monotonic
        self._phase = _PUBLISH

    # ---- lifecycle ---------------------------------------------------------

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        if self.store is None:
            path = _places_settings(context).get("path")
            self.store = PlaceStore(
                path if isinstance(path, str) and path.strip() else DEFAULT_PLACES_PATH
            )
        context.set("place_goal", None)
        super().start(context)

    def stop(self, context) -> None:
        self._retract(context)
        self.goal = None
        context.set("place_goal", None)
        super().stop(context)

    # ---- the loop ----------------------------------------------------------

    def tick(self, context) -> None:
        request = context.get("place_request")
        if request is not None:
            # Consumed once, like `routine_request`: a request is an event, not a state.
            context.set("place_request", None)
            self._accept(context, request)

        goal = self.goal
        if goal is not None and goal.state == TRAVELLING:
            self.goal = self._advance(context, goal)
            goal = self.goal

        if self._rejection is not None:
            context.set("place_goal", self._rejection)
        elif goal is not None:
            context.set("place_goal", goal.to_dict(self._clock()))

    def _accept(self, context, request: object) -> None:
        """Take one `place_request`, or say why not. One goal at a time, by design."""
        handle, at_anchor = _request(request)
        if not handle:
            self._reject("no_place", "the request needs an 'id'", handle)
            return
        if self.store is None:
            self._reject("no_store", "the places store is not loaded", handle)
            return
        if context.get("intent_board") is None:
            self._reject("no_board", "no intent board in the context", handle)
            return

        # Read per request: a place created since boot has to be usable without a restart, and the
        # store is stateless by design ("is the list stale?" has no answer to get wrong).
        report = self.store.load()
        place = report.get(handle) or report.by_name(handle)
        if place is None:
            self._reject(
                "unknown_place",
                f"no place with id or name {handle!r}",
                handle,
                suggestion=_closest(handle, report.places),
            )
            return

        anchor = _places_settings(context).get("anchor")
        anchor = anchor.strip() if isinstance(anchor, str) and anchor.strip() else DEFAULT_ANCHOR
        if place.anchor != anchor:
            self._reject(
                "anchor_mismatch",
                f"{place.id!r} was taught against {place.anchor!r}, not {anchor!r}",
                handle,
            )
            return
        if not at_anchor:
            self._reject(
                "anchor_unconfirmed",
                "the request must confirm the dog stands where the place was taught "
                "('at_anchor': true); nothing here can verify that pose",
                handle,
            )
            return

        self._rejection = None
        self.goal = PlaceGoal(place=place, started=self._clock())
        self._phase = _PUBLISH
        logger.info(
            "Place goal accepted: %s (%.0f cm at %.0f deg, %d visit(s))",
            place.id,
            place.distance_cm,
            place.heading_deg,
            place.visits,
        )

    def _reject(
        self,
        reason: str,
        detail: str,
        handle: str,
        suggestion: str | None = None,
    ) -> None:
        """Record a refused request. The dog does not move, and the reason is readable."""
        self.goal = None
        self._rejection = {
            "id": handle or None,
            "state": REFUSED,
            "reason": reason,
            "detail": detail,
            "suggestion": suggestion,
        }
        logger.warning("Place request refused (%s): %s", reason, detail)

    # ---- one step ----------------------------------------------------------

    def _advance(self, context, goal: PlaceGoal) -> PlaceGoal:
        """One cycle: settle the step already published, or decide and publish the next one."""
        if self._phase == _SETTLE:
            goal = self._settle(context, goal)
            # Retract even when the goal just ended: the stop only has to be seen once, and a
            # retraction is what lets the next goal's first `forward` be a new command.
            self._retract(context)
            self._phase = _PUBLISH
            return goal
        return self._publish(context, goal)

    def _settle(self, context, goal: PlaceGoal) -> PlaceGoal:
        """Read the gateway's answer for the step just published, and count it if it ran.

        Only an accepted `forward` moves the dog, so only an accepted `forward` adds `step_cm`. A
        refused one leaves the count alone and records the veto: a goal that keeps being refused
        must not look like progress until the timeout ends it.
        """
        command = context.get("motion_command")
        if not isinstance(command, Mapping) or command.get("source") != _PLACE_SOURCE:
            veto = _veto(context)
            return replace(goal, veto=veto) if veto else goal

        identifier = command.get("id")
        counted = replace(
            goal,
            last_command_id=identifier if isinstance(identifier, str) else None,
            # Accepted again, so the last refusal is history rather than the current answer.
            veto=None,
        )
        if identifier == goal.last_command_id:
            # The same command the last settle already counted; the gateway leaves it in place
            # across ticks, and counting it twice would walk the dog on paper only.
            return goal
        if command.get("canonical_action") != _FORWARD:
            return counted

        step = max(0.0, _safe_float(_places_settings(context).get("step_cm"), DEFAULT_STEP_CM))
        return replace(counted, walked_cm=goal.walked_cm + step)

    def _publish(self, context, goal: PlaceGoal) -> PlaceGoal:
        """Decide the next step. Arrival and failure are decisions too, and both end the goal."""
        settings = _places_settings(context)
        tolerance = max(0.0, _safe_float(settings.get("tolerance_cm"), DEFAULT_TOLERANCE_CM))
        timeout_s = _safe_float(settings.get("timeout_s"), DEFAULT_TIMEOUT_S)

        # 1. Arrived. Checked before the timeout so a goal that just made it is not abandoned on
        #    the same tick, and before the heading so a place at zero distance needs no heading.
        if goal.walked_cm >= max(0.0, goal.place.distance_cm - tolerance):
            return self._end(context, goal, ARRIVED, None, arrived=True)

        # 2. Out of time: a goal that cannot be reached must stop trying rather than walk on.
        if timeout_s > 0 and self._clock() - goal.started > timeout_s:
            return self._end(context, goal, ABANDONED, "timeout", arrived=False)

        # 3. No heading: the dog cannot say which way it faces, so it must not pick a turn.
        heading = _current_heading(context)
        if heading is None:
            return self._end(context, goal, ABANDONED, "no_heading", arrived=False)

        # 4. Orient first, then advance — the local sequence §6.3 describes, one step at a time.
        turn_tolerance = abs(
            _safe_float(settings.get("turn_tolerance_deg"), DEFAULT_TURN_TOLERANCE_DEG)
        )
        error = heading_error(goal.place.heading_deg, heading)
        action = _FORWARD
        if abs(error) > turn_tolerance:
            action = "turn_right" if error > 0 else "turn_left"
        goal = replace(goal, action=action, heading_error_deg=round(error, 1))
        self._emit(context, action)
        return goal

    def _end(
        self,
        context,
        goal: PlaceGoal,
        state: str,
        reason: str | None,
        *,
        arrived: bool,
    ) -> PlaceGoal:
        """Finish the goal: stop the dog, record the visit once, and keep the outcome visible."""
        goal = self._write_visit(context, goal, arrived=arrived)
        self._emit(context, _STOP)
        if arrived:
            logger.info(
                "Reached place %s: %.0f of %.0f cm, %d visit(s), confidence %s",
                goal.place.id,
                goal.walked_cm,
                goal.place.distance_cm,
                goal.place.visits,
                "unmeasured" if goal.place.confidence is None else f"{goal.place.confidence:.2f}",
            )
        else:
            logger.warning(
                "Place goal %s abandoned (%s) after %.0f cm", goal.place.id, reason, goal.walked_cm
            )
        return replace(goal, state=state, reason=reason, action=_STOP)

    def _write_visit(self, context, goal: PlaceGoal, *, arrived: bool) -> PlaceGoal:
        """Persist the arrival (or the failed approach) **once**, and report the new record.

        A visit is a transition, not a state: the file is written on this tick and not for as long
        as the dog stands there, because a write per tick would rewrite a user's file at 5 Hz.
        """
        if self.store is None:  # pragma: no cover - `_accept` refuses without one
            return goal
        step = _safe_float(
            _places_settings(context).get("confidence_step"), DEFAULT_CONFIDENCE_STEP
        )
        updated, problems = self.store.record_visit(goal.place.id, arrived=arrived, step=step)
        for problem in problems:
            # Reported, not raised: the trip happened, and a file that would not take the note is
            # a defect a user has to see rather than a reason to pretend the dog is still walking.
            logger.warning("Place visit for %s not recorded: %s", goal.place.id, problem)
        if updated is None:
            return goal
        return replace(goal, place=updated)

    # ---- board -------------------------------------------------------------

    def _emit(self, context, action: str) -> None:
        """Publish one step for `Source.PLACE` and move to the settle phase."""
        board = context.get("intent_board")
        if board is None:
            return
        board.publish(action, Source.PLACE)
        self._phase = _SETTLE

    def _retract(self, context) -> None:
        """Withdraw the place intent now: the gateway turns that into `motion_command: None`."""
        board = context.get("intent_board")
        if board is not None:
            board.retract(Source.PLACE)
