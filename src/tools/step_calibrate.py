"""Measure how far one `forward` command actually carries the dog.

Why this exists: `navigation/odometry.py` multiplies counted steps by `step_cm`, which shipped as
**25 cm** — a guess. `hal/vendor.py:573` shows one command is one *gait cycle*
(`do_action(key, step_count=1)`), and the vendor reference itself lists "how far `legs_move` really
travels" as unknown, so 25 cm for a body about 25 cm long is implausible. If the true stride is ~8 cm,
every stored place anchor is three times too far, and the pose the map is drawn from is wrong by the
same factor (#285).

The method: walk toward a wall and watch the ultrasonic. Each cycle is one command, and the distance
the sensor loses is the distance the dog gained - measured against the room, not against a tape, with
no assumption about gait amplitude. A fit over the cycles resists one bad echo; the residual says how
much to trust the number.

**This drives the dog into a wall.** `--confirm-clearance` is mandatory and `--stop-at` defaults to
45 cm. Every step is evaluated by the same :class:`~houndmind_ai.act.interlock.Interlock` the runtime
uses (battery floor, tilt latch, obstacle rule, speed clamp); a veto **ends the run and reports the
veto** rather than being retried. `--fake` runs the whole loop against a simulated wall for tests and
for anyone who wants to see the output without a dog.

    python -m tools.step_calibrate --confirm-clearance --surface hardwood
    python -m tools.step_calibrate --confirm-clearance --measure reverse --commands 6
    python -m tools.step_calibrate --fake                       # no hardware, no motion
    python -m tools.step_calibrate --confirm-clearance --measure head-zero

It prints a `surface_step_cm` block to paste into `config/settings.jsonc`. It does not edit that file:
the config is comment-rich user data, and a tool that rewrites it would take the comments with it.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from houndmind_ai.act.interlock import Interlock, interlock_limits_from_settings
from houndmind_ai.hal.fake import FakeDogHAL
from houndmind_ai.hal.iface import DogHAL, SensorSnapshot
from houndmind_ai.kernel.commands import Command

__all__ = ["Cycle", "RunReport", "main", "run_calibration"]

#: Stop this far from the wall, whatever the operator asked for. The interlock's own obstacle rule
#: fires at 12 cm; this is the deliberate margin in front of it.
DEFAULT_STOP_AT_CM = 45.0
DEFAULT_COMMANDS = 5
DEFAULT_SPEED = 150
#: Let the gait finish and the echo settle before reading again.
DEFAULT_PAUSE_S = 0.4
#: Walk floor on the pack, deliberately above the interlock's 6.4 V veto (#292). Two walking attempts
#: on the bench dog at 7.78-7.85 V idle **rebooted the Pi mid-gait** — under-voltage latched, boots
#: 20 s apart — while `--measure head-zero` on the same pack was fine both times. The interlock
#: protects the servos from an abusive pack; this protects the *measurement* from a pack that will not
#: survive it, because a brownout costs the steps, the pose and the trace at once.
MIN_RUN_VOLTS = 7.9
#: A missed echo is normal on carpet (`docs/pidog/PIDOG-SENSORS.md`), so retry before giving up.
ECHO_ATTEMPTS = 3
ECHO_PAUSE_S = 0.05
#: More veer than this and the run is not a measurement of the *stride*, it is a measurement of a
#: crooked walk: the beam leaves the perpendicular and the cosine error grows with every cycle.
MAX_DRIFT_DEG = 5.0
#: Fewer cycles than this is a hint, not a constant.
MIN_CYCLES_FOR_MEASUREMENT = 3
LINEAR_ACTIONS = {"distance": "forward", "reverse": "backward"}


@dataclass(frozen=True)
class Cycle:
    """One issued command, and what the sensor lost (or gained, reversing) around it."""

    index: int
    before_cm: float
    after_cm: float
    acc: tuple[float, float, float] | None = None
    gyro: tuple[float, float, float] | None = None

    @property
    def delta_cm(self) -> float:
        """Distance closed, positive in the direction of travel."""
        return abs(self.before_cm - self.after_cm)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "before_cm": round(self.before_cm, 2),
            "after_cm": round(self.after_cm, 2),
            "delta_cm": round(self.delta_cm, 2),
            "acc": list(self.acc) if self.acc is not None else None,
            "gyro": list(self.gyro) if self.gyro is not None else None,
        }



def _fit(cycles: list[Cycle]) -> tuple[float, float] | None:
    """Least-squares slope of distance against cycle, and the RMS residual, in cm.

    The slope is per *cycle*, fitted over `(0, before)` then `(n, after)` for each cycle, so one
    outlier echo tilts the line a little instead of setting the answer. That is the difference
    between a measurement and the last sample taken.
    """
    if not cycles:
        return None
    points = [(0.0, cycles[0].before_cm)]
    points.extend((float(cycle.index), cycle.after_cm) for cycle in cycles)
    if len(points) < 2:
        return None
    mean_x = sum(point[0] for point in points) / len(points)
    mean_y = sum(point[1] for point in points) / len(points)
    denominator = sum((point[0] - mean_x) ** 2 for point in points)
    if denominator == 0:
        return None
    slope = sum((point[0] - mean_x) * (point[1] - mean_y) for point in points) / denominator
    residual = math.sqrt(
        sum((point[1] - (mean_y + slope * (point[0] - mean_x))) ** 2 for point in points)
        / len(points)
    )
    return slope, residual


@dataclass
class RunReport:
    """Everything one run measured, and every reason it might not count."""

    surface: str
    measure: str
    speed: int
    stop_at_cm: float
    min_volts: float = MIN_RUN_VOLTS
    cycles: list[Cycle] = field(default_factory=list)
    dropped_echoes: int = 0
    stopped: list[str] = field(default_factory=list)
    veto: str | None = None
    veto_detail: str | None = None
    refused: str | None = None
    drift_deg: float | None = None
    drift_measured: bool = False
    volts_before: float | None = None
    volts_after: float | None = None
    distance_cm: float | None = None

    @property
    def per_cycle_cm(self) -> float | None:
        fitted = _fit(self.cycles)
        return abs(fitted[0]) if fitted is not None else None

    @property
    def residual_cm(self) -> float | None:
        fitted = _fit(self.cycles)
        return fitted[1] if fitted is not None else None

    @property
    def veered(self) -> bool:
        return (
            self.drift_measured
            and self.drift_deg is not None
            and abs(self.drift_deg) > MAX_DRIFT_DEG
        )

    @property
    def accepted(self) -> bool:
        """A number worth writing into config: enough cycles, no veto, no veer."""
        return (
            self.refused is None
            and self.veto is None
            and len(self.cycles) >= MIN_CYCLES_FOR_MEASUREMENT
            and not self.veered
        )

    @property
    def verdict(self) -> str:
        if self.refused is not None:
            return "refused"
        if self.veto is not None:
            return f"stopped by the interlock ({self.veto})"
        if self.veered:
            assert self.drift_deg is not None  # implied by `veered`
            return f"rejected: veered {self.drift_deg:.1f} deg (limit {MAX_DRIFT_DEG:g})"
        if len(self.cycles) >= MIN_CYCLES_FOR_MEASUREMENT:
            return "measured"
        if self.cycles:
            return f"weak: {len(self.cycles)} cycle(s), need {MIN_CYCLES_FOR_MEASUREMENT}"
        return "no data"

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface or None,
            "measure": self.measure,
            "speed": self.speed,
            "stop_at_cm": self.stop_at_cm,
            "min_volts": self.min_volts,
            "verdict": self.verdict,
            "accepted": self.accepted,
            "cm_per_cycle": None if self.per_cycle_cm is None else round(self.per_cycle_cm, 3),
            "residual_cm": None if self.residual_cm is None else round(self.residual_cm, 3),
            "cycles": [cycle.to_dict() for cycle in self.cycles],
            "dropped_echoes": self.dropped_echoes,
            "stopped": list(self.stopped),
            "veto": self.veto,
            "veto_detail": self.veto_detail,
            "refused": self.refused,
            "drift_deg": None if self.drift_deg is None else round(self.drift_deg, 2),
            "drift_measured": self.drift_measured,
            "volts_before": self.volts_before,
            "volts_after": self.volts_after,
            "distance_cm": None if self.distance_cm is None else round(self.distance_cm, 2),
        }



def _sample(
    hal: DogHAL, sleep: Any
) -> tuple[SensorSnapshot | None, float | None, int]:
    """One valid distance reading, retrying a missed echo, with the snapshot it came from.

    Returns `(snapshot, cm, dropped)`. `cm` is `None` when every attempt missed, which is a real
    outcome on carpet and must not be read as "far away" - the validity flag is the truth.
    """
    dropped = 0
    snapshot: SensorSnapshot | None = None
    for attempt in range(ECHO_ATTEMPTS):
        snapshot = hal.read()
        distance = snapshot.distance_cm
        if snapshot.distance_valid and distance is not None and distance > 0:
            return snapshot, float(distance), dropped
        dropped += 1
        if attempt < ECHO_ATTEMPTS - 1:
            sleep(ECHO_PAUSE_S)
    return snapshot, None, dropped


def _issue(
    interlock: Interlock,
    hal: DogHAL,
    report: RunReport,
    action: str,
    params: dict[str, Any],
    snapshot: SensorSnapshot,
) -> bool:
    """Evaluate one command, then execute the interlock's *verdict* — never the raw request.

    That is the whole safety story of this tool: the same `Interlock` the runtime uses decides, and
    a refusal sets `report.veto` and stops the walk. The clamped parameters are executed, so a
    speed the envelope lowered is the speed the servos see.
    """
    command = Command(action=action, params=dict(params), issued_at=time.monotonic())
    verdict = interlock.evaluate(command, snapshot)
    if not verdict.accepted:
        report.veto = verdict.veto or "refused"
        report.veto_detail = verdict.detail
        return False
    hal.action(verdict.action, dict(verdict.params))
    return True


def _walk(
    hal: DogHAL,
    interlock: Interlock,
    report: RunReport,
    *,
    action: str,
    commands: int,
    stop_at_cm: float,
    min_volts: float,
    speed: int,
    pause_s: float,
    sleep: Any,
) -> None:
    """Issue `commands` gait cycles toward the wall, recording what each one bought."""
    previous: SensorSnapshot | None = None
    drift = 0.0
    drift_seen = False

    for index in range(1, commands + 1):
        snapshot, before, dropped = _sample(hal, sleep)
        report.dropped_echoes += dropped
        if snapshot is None or before is None:
            report.stopped.append("no distance reading before the step")
            break
        if report.volts_before is None and snapshot.battery_valid:
            report.volts_before = snapshot.battery_v

        # The pack floor (#292). Before the first step it refuses the run outright; mid-walk it ends
        # the run, because the remaining cycles would measure a gait the pack can no longer carry.
        volts = snapshot.battery_v if snapshot.battery_valid else None
        if volts is not None and volts < min_volts:
            if index == 1:
                report.refused = (
                    f"pack {volts:.2f} V is below the {min_volts:.2f} V walk floor; charge it - "
                    "a gait on this pack rebooted the Pi mid-run (#292)"
                )
            else:
                report.veto = "pack_sag"
                report.veto_detail = (
                    f"{volts:.2f} V fell below {min_volts:.2f} V after {index - 1} cycle(s)"
                )
            break

        # Gyro Z integrated between snapshots: coarse, because the snapshots are seconds apart, but
        # enough to reject a run that veered instead of a stride that was measured.
        if previous is not None and snapshot.gyro is not None and previous.gyro is not None:
            drift += 0.5 * (previous.gyro[2] + snapshot.gyro[2]) * max(
                0.0, snapshot.ts - previous.ts
            )
            drift_seen = True

        if action == "forward" and before <= stop_at_cm:
            report.stopped.append(f"stop_at {stop_at_cm:g} cm reached at {before:.0f} cm")
            break

        if not _issue(
            interlock, hal, report, action, {"steps": 1, "speed": speed, "wait": True}, snapshot
        ):
            break

        sleep(max(0.0, pause_s))
        after_snapshot, after, dropped = _sample(hal, sleep)
        report.dropped_echoes += dropped
        if after_snapshot is None or after is None:
            report.stopped.append("lost the echo after a step")
            break
        if after_snapshot.battery_valid:
            report.volts_after = after_snapshot.battery_v

        report.cycles.append(
            Cycle(
                index=index,
                before_cm=before,
                after_cm=after,
                acc=after_snapshot.acc,
                gyro=after_snapshot.gyro,
            )
        )
        previous = after_snapshot

    report.drift_measured = drift_seen
    report.drift_deg = drift if drift_seen else None



def _head_zero(
    hal: DogHAL,
    interlock: Interlock,
    report: RunReport,
    *,
    pause_s: float,
    sleep: Any,
) -> None:
    """Level the head and report the reading: the reference pose every distance run assumes."""
    snapshot, _distance, dropped = _sample(hal, sleep)
    report.dropped_echoes += dropped
    if snapshot is None:
        report.stopped.append("no sensor reading")
        return
    if snapshot.battery_valid:
        report.volts_before = snapshot.battery_v

    if not _issue(
        interlock, hal, report, "head", {"yaw": 0, "pitch": 0, "speed": 70, "wait": True}, snapshot
    ):
        return

    sleep(max(0.0, pause_s))
    snapshot, distance, dropped = _sample(hal, sleep)
    report.dropped_echoes += dropped
    report.distance_cm = distance
    if snapshot is not None and snapshot.battery_valid:
        report.volts_after = snapshot.battery_v


def run_calibration(
    hal: DogHAL,
    *,
    surface: str = "",
    measure: str = "distance",
    commands: int = DEFAULT_COMMANDS,
    stop_at_cm: float = DEFAULT_STOP_AT_CM,
    speed: int = DEFAULT_SPEED,
    pause_s: float = DEFAULT_PAUSE_S,
    min_volts: float = MIN_RUN_VOLTS,
    settings: dict[str, Any] | None = None,
    confirmed: bool = False,
    sleep: Any = time.sleep,
) -> RunReport:
    """Run one measurement. `confirmed` is the clearance gate, and it is enforced here too.

    The gate is not only in `main`: a caller that drives the dog has to say out loud that the floor
    is clear, and a library that would move a robot because a flag defaulted to True is a bug.
    """
    report = RunReport(
        surface=surface,
        measure=measure,
        speed=speed,
        stop_at_cm=stop_at_cm,
        min_volts=min_volts,
    )
    if measure not in (*LINEAR_ACTIONS, "head-zero"):
        report.refused = f"unknown measure {measure!r}"
        return report
    if not confirmed:
        report.refused = "clearance not confirmed (--confirm-clearance)"
        return report

    interlock = Interlock(interlock_limits_from_settings(settings or {}))

    if measure == "head-zero":
        _head_zero(hal, interlock, report, pause_s=pause_s, sleep=sleep)
        return report

    _walk(
        hal,
        interlock,
        report,
        action=LINEAR_ACTIONS[measure],
        commands=max(0, int(commands)),
        stop_at_cm=stop_at_cm,
        min_volts=min_volts,
        speed=speed,
        pause_s=pause_s,
        sleep=sleep,
    )
    return report


def format_report(report: RunReport) -> list[str]:
    """The lines `main` prints, without the prefix, so a test can assert on meaning, not layout."""
    lines = [
        f"surface {report.surface or '(none)'}, measure {report.measure}, "
        f"speed {report.speed}, stop_at {report.stop_at_cm:g} cm, "
        f"walk floor {report.min_volts:g} V"
    ]
    for cycle in report.cycles:
        lines.append(
            f"  {cycle.index:2d}  {cycle.before_cm:6.1f} -> {cycle.after_cm:6.1f} cm"
            f"   {cycle.delta_cm:5.1f} cm"
        )
    if report.measure == "head-zero":
        distance = "unknown" if report.distance_cm is None else f"{report.distance_cm:.1f} cm"
        lines.append(f"  head at yaw 0, pitch 0; distance {distance}")
    per_cycle = report.per_cycle_cm
    residual = report.residual_cm
    if report.cycles and per_cycle is not None:
        spread = "" if residual is None else f", residual {residual:.2f} cm RMS"
        lines.append(f"cm/cycle {per_cycle:.2f} ({len(report.cycles)} cycles{spread})")
    if report.dropped_echoes:
        lines.append(f"dropped echoes: {report.dropped_echoes}")
    if report.drift_deg is not None:
        lines.append(f"drift {report.drift_deg:+.1f} deg (gyro-integrated, approximate)")
    elif report.cycles:
        lines.append("drift unmeasured (no gyro)")
    if report.volts_before is not None or report.volts_after is not None:
        before = "-" if report.volts_before is None else f"{report.volts_before:.2f}"
        after = "-" if report.volts_after is None else f"{report.volts_after:.2f}"
        lines.append(f"pack {before} -> {after} V")
    for reason in report.stopped:
        lines.append(f"stopped: {reason}")
    if report.veto is not None:
        lines.append(f"veto {report.veto}: {report.veto_detail or 'no detail'}")
    if report.refused is not None:
        lines.append(f"refused: {report.refused}")
    lines.append(f"verdict: {report.verdict}")
    return lines


def snippet(report: RunReport) -> str:
    """A paste-ready `odometry` block, or a comment naming why there is no value to save."""
    per_cycle = report.per_cycle_cm
    if not report.accepted or per_cycle is None:
        return f"// nothing to save: {report.verdict}"
    surface = report.surface or "unknown-surface"
    block = json.dumps(
        {"surface": surface, "surface_step_cm": {surface: round(per_cycle, 2)}}, indent=2
    )
    # Drop the outer braces so the block nests inside `config/settings.jsonc`'s `settings` table.
    inner = block.splitlines()[1:-1]
    return '"odometry": {\n' + "\n".join(inner) + "\n}"


class _WallDogHAL(FakeDogHAL):
    """`FakeDogHAL` with a wall it walks toward, so `--fake` exercises the real loop.

    Each issued `forward` takes `step_cm` off the reading, exactly as a dog closing on a wall would.
    It is a simulation and says so: `--fake` prints that nothing is moving. The point is that the
    measurement path — sampling, the interlock, the fit, the report — is the same code the device
    runs, so a test of `--fake` is a test of the tool.
    """

    def __init__(
        self,
        distance_cm: float = 150.0,
        step_cm: float = 8.0,
        now: Any = None,
    ) -> None:
        super().__init__(now=now)
        # The wall is the fake's own truth, kept apart from the published reading so a flaky echo
        # (a test wrapper) can hide a sample without the simulation forgetting where the wall is.
        self._wall_cm = float(distance_cm)
        self.set_distance(self._wall_cm)
        self.set_imu(0.0, 0.0)
        # A stationary head and a dog that does not veer: the drift line is exercised, and it reads
        # zero until a real dog proves otherwise.
        self.set_acc((0.0, 0.0, 1.0))
        self.set_gyro((0.0, 0.0, 0.0))
        self.set_battery(8.0)
        self._step_cm = step_cm

    def action(self, name: str, params: dict[str, Any]) -> None:
        super().action(name, params)
        if name == "forward":
            self._wall_cm = max(0.0, self._wall_cm - self._step_cm)
            self.set_distance(self._wall_cm)
        elif name == "backward":
            self._wall_cm = self._wall_cm + self._step_cm
            self.set_distance(self._wall_cm)


def _load_settings(path: str | None) -> dict[str, Any]:
    """The `settings` table, so the interlock runs with this machine's envelope.

    Same idiom as `tools/hardware_checkup.py`: a measurement exists to test hardware, so a config
    that will not load degrades to the compiled limits with one line saying why.
    """
    from houndmind_ai.core.config import load_config

    try:
        return dict(load_config(Path(path) if path else None).settings)
    except Exception as exc:  # noqa: BLE001 - missing file, bad JSON, or a schema problem
        print(
            f"[step_calibrate] settings not loaded ({exc}); using the compiled limits",
            file=sys.stderr,
        )
        return {}


def main(argv: list[str] | None = None, hal: DogHAL | None = None) -> int:
    """Run one measurement. `hal` is the injection seam: `None` opens the real dog."""
    parser = argparse.ArgumentParser(
        description="Measure centimetres per gait cycle against a wall (drives the dog)"
    )
    parser.add_argument(
        "--measure",
        choices=("distance", "reverse", "head-zero"),
        default="distance",
        help="Forward against a wall, backward away from one, or just level the head",
    )
    parser.add_argument(
        "--surface", default="", help="Floor surface this run is for (e.g. hardwood, carpet)"
    )
    parser.add_argument(
        "--commands", type=int, default=DEFAULT_COMMANDS, help="Gait cycles to issue"
    )
    parser.add_argument(
        "--stop-at",
        type=float,
        default=DEFAULT_STOP_AT_CM,
        help=f"Stop this many cm from the wall (default {DEFAULT_STOP_AT_CM:g})",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=DEFAULT_SPEED,
        help="Servo speed; the interlock may lower it",
    )
    parser.add_argument(
        "--pause", type=float, default=DEFAULT_PAUSE_S, help="Settle time after each step (s)"
    )
    parser.add_argument(
        "--min-volts",
        type=float,
        default=MIN_RUN_VOLTS,
        help=(
            f"Refuse to walk below this pack voltage (default {MIN_RUN_VOLTS:g} V). Kept above the "
            "interlock's 6.4 V veto because a gait on a sagging pack reboots the Pi (#292)"
        ),
    )
    parser.add_argument(
        "--record-trace", default=None, help="Write the per-cycle trace as JSON (for L3.4)"
    )
    parser.add_argument(
        "--confirm-clearance",
        action="store_true",
        help="Required on hardware: the floor ahead is clear and a hand is on the power",
    )
    parser.add_argument(
        "--fake", action="store_true", help="Simulated wall: no hardware, no motion"
    )
    parser.add_argument(
        "--fake-step-cm",
        type=float,
        default=8.0,
        help="The stride the simulated wall answers with",
    )
    parser.add_argument("--config", default=None, help="Path to settings.jsonc")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args(argv)

    if args.fake and hal is None:
        hal = _WallDogHAL(step_cm=args.fake_step_cm)
        # stderr on purpose: `--json` writes a document to stdout and nothing else.
        print("[step_calibrate] --fake: simulated wall, no hardware and no motion", file=sys.stderr)
    confirmed = bool(args.confirm_clearance or args.fake)

    if not confirmed:
        print("[step_calibrate] Refusing to drive the dog.", file=sys.stderr)
        print(
            "[step_calibrate] This walks into a wall. Check the floor ahead is clear, then re-run "
            "with --confirm-clearance. For a dry look at the output, use --fake.",
            file=sys.stderr,
        )
        return 2

    settings = {} if args.fake else _load_settings(args.config)
    opened = hal is None
    if hal is None:
        from houndmind_ai.hal.vendor import PidogHAL

        try:
            hal = PidogHAL(settings)
        except Exception as exc:  # noqa: BLE001 - no vendor stack, no run
            print(f"[step_calibrate] cannot open the HAL: {exc}", file=sys.stderr)
            return 1

    try:
        report = run_calibration(
            hal,
            surface=args.surface,
            measure=args.measure,
            commands=args.commands,
            stop_at_cm=args.stop_at,
            speed=args.speed,
            pause_s=args.pause,
            min_volts=args.min_volts,
            settings=settings,
            confirmed=confirmed,
        )
    finally:
        if opened:
            try:
                hal.close()
            except Exception as exc:  # noqa: BLE001 - a failed close must not hide the run
                print(f"[step_calibrate] HAL close failed: {exc}", file=sys.stderr)

    if args.record_trace:
        trace_path = Path(args.record_trace)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"[step_calibrate] trace written to {trace_path}")

    if args.json:
        print(json.dumps({"report": report.to_dict(), "snippet": snippet(report)}, indent=2))
    else:
        for line in format_report(report):
            print(f"[step_calibrate] {line}")
        if report.measure != "head-zero":
            print("[step_calibrate] paste into config/settings.jsonc:")
            for line in snippet(report).splitlines():
                print(f"[step_calibrate]   {line}")

    if report.refused is not None:
        return 2
    if report.veto is not None:
        return 1
    if report.measure == "head-zero":
        return 0 if report.distance_cm is not None else 1
    return 0 if report.cycles else 1


if __name__ == "__main__":
    sys.exit(main())

