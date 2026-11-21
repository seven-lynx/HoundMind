from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = ("safety", "health", "navigation", "attention", "emotion")

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
        # What the strip was last told: `(style, color, brightness, bps)`. The strip is stateful, so
        # an instruction it is already showing does not need sending again — at 10 Hz a request that
        # never changes used to be re-written every tick, and each write waited for the HAL's bus
        # (#393). A call that failed is not recorded here, so the next tick retries it.
        self._last_sent: tuple[str, str, float, float | None] | None = None

    def start(self, context) -> None:
        """Forget what the strip was showing: a restarted module re-asserts, it does not assume."""
        self._active = None
        self._last_state = (None, None)
        self._last_sent = None
        super().start(context)

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("led", {})
        if not settings.get("enabled", True):
            return

        hal = context.get("hal")
        if hal is None:
            return

        # The module-level tuple is the fallback, never a per-tick copy of it: this list is walked
        # on every tick of a 10 Hz loop.
        priority = settings.get("priority")
        if not isinstance(priority, (list, tuple)):
            priority = DEFAULT_PRIORITY

        selected = self._select_request(context, priority)
        if selected is None:
            if self._active is None:
                return
            # What owned the strip expired and nothing else wants it: go back to idle once, rather
            # than leaving the last expression stuck there forever (§5.2's "then back to idle").
            self._active = None
            self._apply_led(context, _IDLE_SOURCE, "idle", {})
            self._last_state = (_IDLE_SOURCE, "idle")
            self._last_ts = self._clock()
            return

        source, request = selected
        mode = str(request.get("mode", "patrol"))
        now = self._clock()
        # `_safe_float`, not `float`: a live config write could store a non-number here, and a raise
        # would fail this module on every tick (#123).
        if (source, mode) == self._last_state and now - self._last_ts < _safe_float(
            settings.get("cooldown_s", 0.5), 0.5
        ):
            return

        self._apply_led(context, source, mode, request)
        self._active = source
        self._last_state = (source, mode)
        self._last_ts = now

    def _select_request(
        self, context, priority: Sequence[str]
    ) -> tuple[str, Mapping[str, Any]] | None:
        """The highest-priority live request and the source that published it, or `None`.

        Clearing is what makes an expiry a fallback rather than a demotion: the source stops
        occupying its slot, so it can publish again without whoever set it having to write `None`.
        The identity check keeps a concurrent refresh intact — another producer may have written
        between the read and the clear (H-02). The pair is returned rather than a merged dict so a
        live request costs no copy on a tick that sends nothing (#393).
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
            return source, request
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
        elif source == "health":
            # A sensor-health colour is a diagnosis, not an expression: the request names the
            # colour and this chooses only the effect (#78). `safety/sensor_health.py` keeps the
            # request refreshed while the sensors are unhappy and clears it when they recover.
            mode_name = settings.get("health_mode", "breath")
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

        # `_safe_float` rather than `float`: a live config write could store a non-number in a
        # numeric key, and a raise here would fail this module on every tick (#123).
        brightness = _safe_float(settings.get("brightness", 0.7), 0.7)
        params: dict[str, Any] = {
            "style": str(mode_name),
            "color": str(color),
            "brightness": brightness,
        }
        bps = _request_bps(request, settings, source)
        if bps is not None:
            params["bps"] = bps

        # The strip is stateful: an instruction it is already showing is not worth a call. The
        # cooldown above only dedupes inside its own window, so a request that never changes used
        # to be re-sent on the first tick past it, forever (#393).
        signature: tuple[str, str, float, float | None] = (
            params["style"],
            params["color"],
            brightness,
            bps,
        )
        if signature == self._last_sent:
            return

        try:
            hal.action("rgb", params)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LED update failed: %s", exc)
            return
        self._last_sent = signature

