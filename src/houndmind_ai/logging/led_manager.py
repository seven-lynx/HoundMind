from __future__ import annotations

import logging
import time

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class LedManagerModule(Module):
    """Centralized RGB LED manager with priority selection."""

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._last_state: tuple[str | None, str | None] = (None, None)
        self._last_ts = 0.0

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("led", {})
        if not settings.get("enabled", True):
            return

        dog = context.get("pidog")
        if dog is None or not hasattr(dog, "rgb_strip"):
            return

        priority = settings.get(
            "priority", ["safety", "navigation", "attention", "emotion"]
        )
        if not isinstance(priority, list):
            priority = ["safety", "navigation", "attention", "emotion"]

        request = self._select_request(context, priority)
        if request is None:
            return

        mode = str(request.get("mode", "patrol"))
        source = str(request.get("source", ""))
        if (source, mode) == self._last_state and time.time() - self._last_ts < float(
            settings.get("cooldown_s", 0.5)
        ):
            return

        self._apply_led(context, source, mode)
        self._last_state = (source, mode)
        self._last_ts = time.time()

    def _select_request(self, context, priority: list[str]) -> dict | None:
        best: dict | None = None
        for source in priority:
            request = context.get(f"led_request:{source}")
            if isinstance(request, dict):
                req = {**request, "source": source}
                best = req
                break
        return best

    def _apply_led(self, context, source: str, mode: str) -> None:
        settings = (context.get("settings") or {}).get("led", {})
        nav = (context.get("settings") or {}).get("navigation", {})
        emotion = (context.get("settings") or {}).get("emotion", {})

        dog = context.get("pidog")
        if dog is None or not hasattr(dog, "rgb_strip"):
            return

        color = settings.get("default_color", "blue")
        if source == "safety":
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

        try:
            dog.rgb_strip.set_mode(
                str(mode_name),
                str(color),
                brightness=float(settings.get("brightness", 0.7)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("LED update failed: %s", exc)
