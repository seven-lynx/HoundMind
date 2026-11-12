"""Runs one routine at a time: one step per tick, and the first refusal ends the run.

A routine is data (`kernel/routine.py`) that the store has already validated
(`kernel/routine_store.py`), so nothing here decides whether a routine is legal — it decides
*when* each step is asked for, and what to do when the answer is no.

Two rules shape the loop.

1. **One step at a time, and the gateway is the authority.** A step is published as a
   `Source.ROUTINE` intent on the board and refreshed like any other producer's; the
   interlock, the obstacle stop and the mode gate all apply to it (`act/gateway.py`), and a
   refusal stops the routine instead of being skipped. Skipping is how a routine that says
   "sit, stand, wag" ends up having wagged without ever standing.
2. **Two equal steps are two steps.** The gateway and the motors both drop a repeat of the
   command they just ran, which is right for a producer that keeps asking every tick and wrong
   for a routine whose step 3 is step 2 again. So the runner retracts its own intent for one
   tick between steps: the retraction clears both dedupe memories, and the repeat runs. That
   is why `_advance` has a `settle` phase rather than publishing as fast as it can.

The retraction is also what paces the run at two ticks per step (400 ms on the shipped loop):
long enough for the gateway to see the step, short enough that a 20-step routine is over in
seconds. Motion that takes longer than that is the HAL's business — a parameterised step with
`wait` runs on the motor worker, never on the tick (`hal/motors.py`).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.kernel.actions import repertoire_from_settings
from houndmind_ai.kernel.commands import Source
from houndmind_ai.kernel.routine import Routine
from houndmind_ai.kernel.routine_store import (
    DEFAULT_ROUTINES_DIR,
    RoutineStore,
    StoreReport,
)

__all__ = ["RUN_STATES", "RoutineRun", "RoutineRunnerModule"]

logger = logging.getLogger(__name__)

# The run's whole vocabulary lives here, and `to_dict` is the only place it reaches a wire, so a
# client cannot be shown a fifth word some future branch invented.
RUNNING = "running"
DONE = "done"
STOPPED = "stopped"
REFUSED = "refused"
RUN_STATES = frozenset({RUNNING, DONE, STOPPED, REFUSED})

# The two phases of one step. `publish` puts the step on the board; `settle` reads the gateway's
# answer and retracts, which is what makes the next step (even an identical one) a new command.
_PUBLISH = "publish"
_SETTLE = "settle"


def _safe_dir(context) -> str:
    """`settings.routines.dir`, or the documented default. Anything else is the default."""
    settings = context.get("settings") or {}
    routines = settings.get("routines") if isinstance(settings, dict) else None
    raw = routines.get("dir") if isinstance(routines, dict) else None
    return raw if isinstance(raw, str) and raw.strip() else DEFAULT_ROUTINES_DIR


@dataclass(frozen=True)
class RoutineRun:
    """One run's public state: what is playing, at which step, and how it ended.

    `index` is the step currently published (0-based); a finished run has `index == total`, so a
    client renders "step 3 of 5" without guessing from the state word.
    """

    routine_id: str
    name: str
    total: int
    index: int = 0
    state: str = RUNNING
    dry_run: bool = False
    action: str | None = None
    veto: str | None = None
    detail: str | None = None
    started_at: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.routine_id,
            "name": self.name,
            "index": self.index,
            "total": self.total,
            "state": self.state,
            "dry_run": self.dry_run,
            "action": self.action,
            "veto": self.veto,
            "detail": self.detail,
            "started_at": self.started_at,
        }


class RoutineRunnerModule(Module):
    """Advances one routine step per tick and publishes it as a `Source.ROUTINE` intent."""

    def __init__(
        self, name: str, enabled: bool = True, required: bool = False, **kwargs: Any
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        # Unknown kwargs are tolerated on purpose: `main.cfg()` hands over a whole config section,
        # and a key this module does not know must not take the runtime down (20-hardware rule).
        self.store: RoutineStore | None = None
        self.report: StoreReport | None = None
        self.run: RoutineRun | None = None
        self._phase = _PUBLISH

    # ---- lifecycle ---------------------------------------------------------

    def start(self, context) -> None:
        if not self.status.enabled:
            return
        directory = _safe_dir(context)
        self.store = RoutineStore(directory)
        self.report = self.store.load(repertoire_from_settings(context.get("settings")))
        context.set("routine_report", self.report)
        context.set("routine_run", None)
        if self.report.refused:
            # Quarantined, not fatal: the runtime boots with a broken file on disk and the report
            # says which file a user has to edit.
            logger.warning(
                "%d routine file(s) refused in %s", self.report.refused, self.report.directory
            )

    def stop(self, context) -> None:
        self._retract(context)
        self.run = None
        context.set("routine_run", None)

    # ---- the loop ----------------------------------------------------------

    def tick(self, context) -> None:
        request = context.get("routine_request")
        if isinstance(request, dict):
            context.set("routine_request", None)
            self._accept(context, request)

        run = self.run
        if run is not None and run.state == RUNNING:
            self._advance(context)
        context.set("routine_run", self.run)

    def _accept(self, context, request: dict) -> None:
        """Take one `routine_request`, or say why not. One run at a time, by design."""
        routine_id = request.get("id")
        reason: str | None = None
        routine: Routine | None = None
        if not isinstance(routine_id, str) or not routine_id:
            reason = "the request needs an 'id'"
        elif self.run is not None and self.run.state == RUNNING:
            reason = f"'{self.run.routine_id}' is still running"
        elif self.report is None:
            reason = "no routines are loaded"
        else:
            routine = self.report.get(routine_id)
            if routine is None:
                reason = f"no routine named '{routine_id}' was loaded"
        if reason is not None or routine is None:
            logger.info("Routine request refused: %s", reason or "the routine is missing")
            context.set(
                "routine_rejection", {"id": routine_id, "reason": reason or "not loaded"}
            )
            return

        self.run = RoutineRun(
            routine_id=routine.id,
            name=routine.name or routine.id,
            total=len(routine.steps),
            dry_run=bool(request.get("dry_run", False)),
            started_at=time.time(),
        )
        self._phase = _PUBLISH
        logger.info(
            "Routine %s started: %d step(s)%s",
            routine.id,
            len(routine.steps),
            ", dry run" if self.run.dry_run else "",
        )

    def _advance(self, context) -> None:
        run = self.run
        if run is None:  # pragma: no cover - only called while a run exists
            return
        if _stop_requested(context):
            context.set("routine_stop", None)
            self._finish(context, STOPPED, detail="stop requested")
            return

        routine = self.report.get(run.routine_id) if self.report is not None else None
        if routine is None:
            self._finish(
                context, REFUSED, veto="missing", detail="the routine is no longer loaded"
            )
            return

        if run.dry_run:
            # Nothing is published, so there is nothing to settle or veto: one step a tick, and
            # the counters move exactly as they would on a real run.
            self._dry_step(context, run)
            return

        if self._phase == _PUBLISH:
            self._publish_step(context, routine, run)
            return

        veto = _routine_veto(context)
        if veto is not None:
            self._finish(context, REFUSED, veto=veto[0], detail=veto[1])
            return
        # Retract before advancing: the gateway and the motors clear their dedupe keys when the
        # command disappears, which is what lets an identical next step run (F-P2-2, #65).
        self._retract(context)
        index = run.index + 1
        self.run = replace(run, index=index, action=None)
        if index >= run.total:
            self._finish(context, DONE)
            return
        self._phase = _PUBLISH

    def _publish_step(self, context, routine: Routine, run: RoutineRun) -> None:
        step = routine.step(run.index)
        if step is None:  # pragma: no cover - `index < total` is checked before publishing
            self._finish(context, DONE)
            return
        board = context.get("intent_board")
        if board is None:
            self._finish(
                context, REFUSED, veto="no_board", detail="no intent board in the context"
            )
            return
        board.publish(step.action, Source.ROUTINE, params=dict(step.params))
        self.run = replace(run, action=step.action)
        self._phase = _SETTLE

    def _dry_step(self, context, run: RoutineRun) -> None:
        index = run.index + 1
        self.run = replace(run, index=index)
        if index >= run.total:
            self._finish(context, DONE)
        else:
            self._phase = _PUBLISH

    def _finish(
        self, context, state: str, veto: str | None = None, detail: str | None = None
    ) -> None:
        """End the run, retract whatever is on the board, and leave the reason in the state."""
        run = self.run
        if run is None:  # pragma: no cover - every caller has a run
            return
        self._retract(context)
        self.run = replace(run, state=state, veto=veto, detail=detail, action=None)
        logger.info(
            "Routine %s %s at step %d/%d%s",
            run.routine_id,
            state,
            min(run.index + 1, run.total),
            run.total,
            f" ({veto})" if veto else "",
        )

    def _retract(self, context) -> None:
        """Withdraw the routine's intent now; the gateway turns that into `motion_command: None`."""
        board = context.get("intent_board")
        if board is not None:
            board.retract(Source.ROUTINE)


def _stop_requested(context) -> bool:
    """A `routine_stop` request is consumed by the run it stops, not by the next one."""
    return bool(context.get("routine_stop"))


def _routine_veto(context) -> tuple[str, str | None] | None:
    """The first refusal this tick aimed at a routine intent, as `(reason, detail)`.

    `motion_verdict` is not enough: it carries the *winner's* answer, so a refused routine step
    leaves nothing there. The decision record keeps a refusal per intent with its source
    (`act/gateway.py::_record`), which is the only place that still names the loser.
    """
    record = context.get("decision_record")
    for veto in getattr(record, "vetoes", ()) or ():
        if getattr(veto, "source", None) == "routine":
            detail = getattr(veto, "detail", None)
            return str(getattr(veto, "reason", "") or "refused"), detail
    return None
