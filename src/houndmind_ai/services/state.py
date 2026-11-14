"""The one JSON document every client renders (`docs/CONTROL_API.md` §4).

Clients are dumb on purpose: they render this, and they honour the validity flags in it. That
makes this module the place where "a sensor that did not answer" is turned into something a
human can read without being lied to — an invalid reading stays ``null``/``false`` rather than
becoming a plausible zero.
"""

from __future__ import annotations

from typing import Any

from houndmind_ai.kernel.commands import DEFAULT_MODE, RUNTIME_MODES
from houndmind_ai.kernel.decisions import DecisionRecord

__all__ = ["build_health", "build_modules", "build_state", "build_supervisor", "redact_config"]


def _table(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    """A float, or None. ``bool`` is not a measurement and NaN is not a temperature."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return None if number != number else number


def _mode(context) -> str:
    mode = context.get("runtime_mode")
    return mode if isinstance(mode, str) and mode in RUNTIME_MODES else DEFAULT_MODE


def _sensors(context) -> dict[str, object]:
    reading = context.get("sensor_reading")
    tilt = _table(context.get("tilt_warning"))
    # Same precedence as `act/gateway.py::_snapshot`: the reading the HAL filled wins, and the
    # context key covers a producer that is not the sensor module (#119).
    battery = _number(getattr(reading, "battery_v", None))
    if battery is None:
        battery = _number(context.get("battery_voltage"))

    pitch = _number(tilt.get("pitch"))
    roll = _number(tilt.get("roll"))
    return {
        "distance_cm": _number(getattr(reading, "distance_cm", None)),
        "distance_valid": bool(getattr(reading, "distance_valid", False)),
        "touch": str(getattr(reading, "touch", "N") or "N"),
        "touch_valid": bool(getattr(reading, "touch_valid", False)),
        "sound_detected": bool(getattr(reading, "sound_detected", False)),
        "sound_direction": getattr(reading, "sound_direction", None),
        "sound_valid": bool(getattr(reading, "sound_valid", False)),
        "pitch_deg": pitch,
        "roll_deg": roll,
        "imu_valid": pitch is not None and roll is not None,
        "battery_v": battery,
        # The battery feed is absent on some builds, so `valid` follows the value.
        "battery_valid": battery is not None,
    }


def _actuators(context, now: float) -> dict[str, object]:
    command = _table(context.get("motion_command"))
    verdict = _table(context.get("motion_verdict"))
    issued_at = _number(command.get("issued_at"))
    return {
        "last_command": command.get("canonical_action") or command.get("action"),
        # Who won the tick. A client that pressed forward and sees `source: watchdog` with
        # `vetoed: false` can tell "someone else is driving" from "the dog ignored me".
        "source": command.get("source"),
        "since_s": None if issued_at is None else max(0.0, now - issued_at),
        "vetoed": bool(verdict) and verdict.get("accepted") is False,
        "veto": verdict.get("veto"),
        "tilt_latched": bool(context.get("tilt_latched", False)),
        "displaced": len(context.get("motion_cancel") or []),
    }


def _safety(context) -> dict[str, object]:
    """Whether the safety module is overriding right now.

    `tilt_latched` stays in `actuators`, where the contract already puts it; this answers the
    narrower question a client could not ask before (#125): did safety fire, and is the e-stop set.
    Both flags are false while `modules.safety` is disabled, which is the shipped default — that is
    the module not running, not the dog reporting itself safe.
    """
    return {
        "active": bool(context.get("safety_active", False)),
        "emergency_stop": bool(context.get("emergency_stop_active", False)),
    }


def build_supervisor(context) -> dict[str, object]:
    """What the watchdog is doing: holding motion, and what it has restarted or given up on."""
    hold = _table(context.get("watchdog_hold"))
    status = _table(context.get("watchdog_status"))
    return {
        "holding": bool(hold),
        "reason": hold.get("reason"),
        "restarts": list(status.get("restart") or []),
        "failed": list(status.get("failed") or []),
    }


def _nav(context) -> dict[str, object]:
    decision = _table(context.get("navigation_decision"))
    command = _table(context.get("motion_command"))
    # The navigator's own decision, and — when the navigator is the source that won the tick —
    # the command that is actually being executed. No fallback to a producer's private key: a
    # client must not read one module's opinion as the dog's current action.
    decision_name = decision.get("decision")
    if decision_name is None and command.get("source") == "navigation":
        decision_name = command.get("canonical_action")
    return {
        "decision": decision_name,
        "confidence": _number(decision.get("confidence")),
        # A heading corrected by the gyro bias and one that never was look identical in
        # `decision`, so the client has no way to tell a drifting turn from a calibrated one
        # unless this says so (#125).
        "heading_calibrated": bool(context.get("orientation_calibration_ok", False)),
    }


def build_health(context) -> dict[str, object]:
    status = _table(context.get("health_status"))
    load = _number(status.get("load_1m"))
    cores = _number(status.get("cpu_cores"))
    cpu_pct = None
    if load is not None and cores:
        cpu_pct = max(0.0, min(100.0, (load / cores) * 100.0))
    degraded = bool(context.get("health_degraded", status.get("degraded", False)))
    high_water: dict[str, float] = {}
    for key, raw in _table(context.get("health_high_water")).items():
        value = _number(raw)
        if value is not None:
            high_water[str(key)] = value
    return {
        "status": "degraded" if degraded else "ok",
        "cpu_pct": cpu_pct,
        "temp_c": _number(status.get("temp_c")),
        "mem_used_pct": _number(status.get("mem_used_pct")),
        "reasons": list(status.get("degraded_reasons") or []),
        # Session peaks, which is what a support bundle wants: an average hides the thermal spike
        # that throttled vision. Empty while `modules.health` is disabled, the shipped default.
        "high_water": high_water,
    }


def _perf(context) -> dict[str, object]:
    """The loop against its budget, in the units `/modules` already reports for one module.

    `core/runtime.py` publishes this every tick and nothing read it, so the one number that answers
    "is the Pi overrunning?" was visible only as an occasional warning line (#124). `tick_ms` is the
    EMA of the tick duration, not the worst one, and a missing record stays `null` rather than
    becoming a plausible zero.
    """
    perf = _table(context.get("runtime_performance"))
    return {
        "tick_hz_target": _number(perf.get("tick_hz_target")),
        "tick_hz_actual": _number(perf.get("tick_hz_actual")),
        "tick_ms": _millis(perf.get("tick_duration_avg_s")),
        "tick_overrun_ms": _millis(perf.get("tick_overrun_s")),
        "loop_delay_ms": _millis(perf.get("loop_delay_s")),
    }


def _millis(seconds: Any) -> float | None:
    value = _number(seconds)
    return None if value is None else round(value * 1000.0, 2)


def build_modules(context) -> dict[str, object]:
    """Every module and why it is not running. `disabled` is normal, `failed` is a bug."""
    statuses = _table(context.get("module_statuses"))
    durations = _table(context.get("module_tick_durations"))
    entries: list[dict[str, object]] = []
    counts = {"loaded": 0, "disabled": 0, "failed": 0}
    for name, raw in sorted(statuses.items()):
        status = _table(raw)
        if not status.get("enabled", True):
            state = "disabled"
            detail = status.get("disabled_reason")
            counts["disabled"] += 1
        elif status.get("last_error"):
            state = "failed"
            detail = status.get("last_error")
            counts["failed"] += 1
        elif status.get("started"):
            state = "ok"
            detail = None
            counts["loaded"] += 1
        else:
            state = "degraded"
            detail = "not started"
        entries.append(
            {
                "name": name,
                "state": state,
                "tick_ms": _millis(durations.get(name)),
                "detail": detail,
            }
        )
    return {"modules": entries, "counts": counts}


def _decision(context) -> dict[str, Any] | None:
    """The record behind this tick's verdict, or ``None`` before the gateway has decided anything.

    The context holds the ``DecisionRecord`` itself — ``act/gateway.py`` publishes the object and
    lets the boundary serialize it — so this is the same split as ``sensor_reading`` above: a
    dataclass goes in, JSON comes out. ``None`` is honest here; an empty object would claim the
    dog made a choice it has not made yet.
    """
    record = context.get("decision_record")
    return record.to_dict() if isinstance(record, DecisionRecord) else None


def _routines(context) -> dict[str, Any] | None:
    """The routine the runner is playing, or ``None`` before the first run.

    Duck-typed on purpose, the same call `services/api.py::_routine_state` makes: `services` may not
    import `behavior`, and the shape belongs to ``RoutineRun.to_dict()``. One object, three surfaces
    — `GET /routines`' ``current``, this block and the ``routine`` event — so a client can compare
    them without translating between three spellings of the same run.
    """
    run = context.get("routine_run")
    to_dict = getattr(run, "to_dict", None)
    return to_dict() if callable(to_dict) else None


def build_state(context, *, now: float | None = None) -> dict[str, object]:
    """The full snapshot. ``now`` is the caller's monotonic clock, used for ``since_s``."""
    clock = 0.0 if now is None else now
    modules = build_modules(context)
    counts = modules["counts"]
    return {
        "ts": clock,
        "trace_id": context.get("trace_id"),
        "mode": _mode(context),
        "sensors": _sensors(context),
        "actuators": _actuators(context, clock),
        "safety": _safety(context),
        "nav": _nav(context),
        "decision": _decision(context),
        "routines": _routines(context),
        "health": build_health(context),
        "supervisor": build_supervisor(context),
        "modules": counts,
        "perf": _perf(context),
    }


# Keys whose value must never leave the device, even to an `admin` token: a client has no use
# for a path or a credential, and redaction is cheaper than an incident.
_REDACT_KEYS = ("auth_token", "token_path", "api_token", "wifi_password", "password", "secret")


def redact_config(value: Any) -> Any:
    """Copy a config tree with secrets replaced. Total over dict/list/scalar."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, entry in value.items():
            lowered = str(key).lower()
            if any(secret in lowered for secret in _REDACT_KEYS):
                out[key] = "***"
            else:
                out[key] = redact_config(entry)
        return out
    if isinstance(value, list):
        return [redact_config(entry) for entry in value]
    return value