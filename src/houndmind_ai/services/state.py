"""The one JSON document every client renders (`docs/CONTROL_API.md` §4).

Clients are dumb on purpose: they render this, and they honour the validity flags in it. That
makes this module the place where "a sensor that did not answer" is turned into something a
human can read without being lied to — an invalid reading stays ``null``/``false`` rather than
becoming a plausible zero.
"""

from __future__ import annotations

from typing import Any

from houndmind_ai.kernel.commands import DEFAULT_MODE, RUNTIME_MODES

__all__ = ["build_health", "build_modules", "build_state", "redact_config"]


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
        "since_s": None if issued_at is None else max(0.0, now - issued_at),
        "vetoed": bool(verdict) and verdict.get("accepted") is False,
        "veto": verdict.get("veto"),
        "tilt_latched": bool(context.get("tilt_latched", False)),
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
    }


def build_health(context) -> dict[str, object]:
    status = _table(context.get("health_status"))
    load = _number(status.get("load_1m"))
    cores = _number(status.get("cpu_cores"))
    cpu_pct = None
    if load is not None and cores:
        cpu_pct = max(0.0, min(100.0, (load / cores) * 100.0))
    degraded = bool(context.get("health_degraded", status.get("degraded", False)))
    return {
        "status": "degraded" if degraded else "ok",
        "cpu_pct": cpu_pct,
        "temp_c": _number(status.get("temp_c")),
        "mem_used_pct": _number(status.get("mem_used_pct")),
        "reasons": list(status.get("degraded_reasons") or []),
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
        "nav": _nav(context),
        "health": build_health(context),
        "modules": counts,
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