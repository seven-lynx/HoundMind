from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = ("safety", "navigation", "attention", "emotion")

# The idle slot's source; a real source is never an empty string, so it cannot collide with one.
_IDLE_SOURCE = ""


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _deadline(request: Mapping[str, Any]) -> float | None:
    """A monotonic deadline, or `None` when the request has none.

    Missing, `None`, `""`, NaN and anything unparseable all mean "stands until it is replaced" —
    which is what every producer shipped before P3 L1 writes, so their behaviour is unchanged.
    """
    raw = request.get("until_ts")
    if raw is None or raw == "":
        return None
    value = _safe_float(raw, float("nan"))
    if value != value:  # NaN
        return None
    return value


def _request_bps(
    request: Mapping[str, Any], settings: Mapping[str, Any], source: str
) -> float | None:
    """The rate to ask for: the request's own `bps`, else `led.bps[<source>]`, else `None`.

    `None` means "do not send the key at all", so the HAL's own default rate applies
    (`hal/vendor.py::_rgb`). A rate has to be positive to mean anything; zero and negatives are
    dropped rather than passed on as an instruction.
    """
    raw = request.get("bps")
    if raw is None and source:
        raw = (settings.get("bps") or {}).get(source)
    if raw is None:
        return None
    bps = _safe_float(raw, 0.0)
    return bps if bps > 0 else None


class LedManagerModule(Module):
    """Centralized RGB LED manager with priority selection and expiring requests."""

    def __init__(
        self,
        name: str,
        enabled: bool = True,
        required: bool = False,
        clock: Callable[[], float] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)
        # Monotonic by default: a deadline must not move when the wall clock is corrected, the same
        # rule `kernel/intents.py` applies to an intent's hold window. Injectable because a test
        # that sleeps to cross a deadline is slower and flakier than one that owns the clock.
        self._clock = clock or time.monotonic
        self._last_state: tuple[str | None, str | None] = (None, None)
        self._last_ts = 0.0
        # The source whose request owns the strip right now, or None. This is what tells the
        # difference between "nothing is asking" and "what was asking has just expired".
        self._active: str | None = None


    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("led", {})
        if not settings.get("enabled", True):
            return

        hal = context.get("hal")
        if hal is None:
            return

        priority = settings.get("priority", list(DEFAULT_PRIORITY))
        if not isinstance(priority, list):
            priority = list(DEFAULT_PRIORITY)

        request = self._select_request(context, priority)
        if request is None:
            if self._active is None:
                return
            # What owned the strip expired and nothing else wants it: go back to idle once, rather
            # than leaving the last expression stuck there forever (§5.2's "then back to idle").
            self._active = None
            self._apply_led(context, _IDLE_SOURCE, "idle", {})
            self._last_state = (_IDLE_SOURCE, "idle")
            self._last_ts = self._clock()
            return

        mode = str(request.get("mode", "patrol"))
        source = str(request.get("source", ""))
        now = self._clock()
        if (source, mode) == self._last_state and now - self._last_ts < float(
            settings.get("cooldown_s", 0.5)
        ):
            return

        self._apply_led(context, source, mode, request)
        self._active = source
        self._last_state = (source, mode)
        self._last_ts = now

    def _select_request(self, context, priority: list[str]) -> dict | None:
        """The highest-priority live request, clearing any expired one on the way past.

        Clearing is what makes an expiry a fallback rather than a demotion: the source stops
        occupying its slot, so it can publish again without whoever set it having to write `None`.
        The identity check keeps a concurrent refresh intact — another producer may have written
        between the read and the clear (H-02).
        """
        now = self._clock()
        for source in priority:
            key = f"led_request:{source}"
            request = context.get(key)
            if not isinstance(request, dict):
                continue
            deadline = _deadline(request)
            if deadline is not None and now >= deadline:
                if context.get(key) is request:
                    context.set(key, None)
                continue
            return {**request, "source": source}
        return None

    def _apply_led(self, context, source: str, mode: str, request: Mapping[str, Any]) -> None:
        settings = (context.get("settings") or {}).get("led", {})
        nav = (context.get("settings") or {}).get("navigation", {})
        emotion = (context.get("settings") or {}).get("emotion", {})

        hal = context.get("hal")
        if hal is None:
            return

        color = settings.get("default_color", "blue")
        if source == _IDLE_SOURCE:
            mode_name = settings.get("idle_mode", "breath")
        elif source == "safety":
            color = settings.get("safety_color", "red")
            mode_name = settings.get("safety_mode", "boom")
        elif source == "attention":
            color = settings.get("attention_color", "cyan")
            mode_name = settings.get("attention_mode", "listen")
        elif source == "emotion":
            color = (emotion.get("led_colors", {}) or {}).get(
                mode, settings.get("emotion_color", "blue")
            )
            mode_name = settings.get("emotion_mode", "breath")
        else:
            # navigation modes
            if mode == "patrol":
                color = nav.get("led_patrol_color", "green")
                mode_name = settings.get("nav_mode", "breath")
            elif mode == "turn":
                color = nav.get("led_turn_color", "orange")
                mode_name = settings.get("nav_turn_mode", "listen")
            elif mode == "obstacle":
                color = nav.get("led_obstacle_color", "red")
                mode_name = settings.get("nav_obstacle_mode", "bark")
            elif mode == "retreat":
                color = nav.get("led_retreat_color", "red")
                mode_name = settings.get("nav_retreat_mode", "boom")
            else:
                mode_name = settings.get("nav_mode", "breath")

        # A request may carry its own colour: that is the one field a producer already sends
        # (`safety/sensor_health.py:64`) and this manager dropped before P3 L1.
        color = request.get("color", color)

        params: dict[str, Any] = {
            "style": str(mode_name),
            "color": str(color),
            "brightness": float(settings.get("brightness", 0.7)),
        }
        bps = _request_bps(request, settings, source)
        if bps is not None:
            params["bps"] = bps

        try:
            hal.action("rgb", params)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LED update failed: %s", exc)

