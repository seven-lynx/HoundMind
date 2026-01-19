from __future__ import annotations

import time
import logging

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class HabituationModule(Module):
    """Suppress repeated stimuli temporarily (habituation).

    Tracks recent stimulus counts and exposes `habituation:<stimulus>:habituated`
    in the runtime context as a boolean that other modules may consult.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self._state: dict[str, dict] = {}

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("habituation", {})
        if not settings.get("enabled", True):
            return

        perception = context.get("perception") or {}
        now = time.time()

        stimuli = settings.get("stimuli", ["sound", "touch"])
        window_s = float(settings.get("window_s", 1.0))
        threshold = int(settings.get("threshold", 3))
        recovery_s = float(settings.get("recovery_s", 6.0))

        for stimulus in stimuli:
            detected = False
            try:
                val = perception.get(stimulus)
                detected = val not in (None, False, "N")
            except Exception:
                detected = False

            st = self._state.setdefault(stimulus, {"count": 0, "last_ts": 0.0})
            last = float(st.get("last_ts", 0.0))

            if detected:
                # If last event was recent, increase count, else reset small-window count
                if now - last <= window_s:
                    st["count"] = st.get("count", 0) + 1
                else:
                    st["count"] = 1
                st["last_ts"] = now
            else:
                # If quiet for recovery window, reset habituation counter
                if now - last > recovery_s:
                    st["count"] = 0

            habituated = st.get("count", 0) >= threshold
            st["habituated"] = habituated
            context.set(f"habituation:{stimulus}:habituated", bool(habituated))
