from __future__ import annotations

import logging
import time
from typing import Any

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


class LocalPlannerModule(Module):
    """Simple local planner that exposes mapping-derived short-range hints.

    This module is intentionally lightweight for Pi3: it reads `mapping_openings`
    from the runtime context and publishes a `local_plan` entry. It does not
    perform heavy pathfinding or global planning.
    """

    def __init__(
        self, name: str = "local_planner", enabled: bool = True, required: bool = False
    ) -> None:
        super().__init__(name, enabled=enabled, required=required)

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("navigation", {})
        if not settings.get("planner_enabled", True):
            return

        mapping = context.get("mapping_openings") or {}
        best_path = mapping.get("best_path") if isinstance(mapping, dict) else None
        now = time.time()

        plan = {"timestamp": now, "source": "mapping", "valid": False}
        if isinstance(best_path, dict):
            conf = _safe_float(best_path.get("confidence", best_path.get("score", 0.0)), 0.0)
            min_conf = _safe_float(settings.get("planner_min_confidence", 0.6), 0.6)
            max_age_s = _safe_float(settings.get("planner_max_age_s", 2.0), 2.0)
            sample_ts = mapping.get("timestamp", now)
            sample_ts_val = _safe_float(sample_ts, now)
            age_ok = (now - sample_ts_val) <= max_age_s if max_age_s > 0 else True
            if conf >= min_conf and age_ok:
                yaw = best_path.get("yaw")
                yaw = _safe_float(yaw, 0.0)
                direction = "forward"
                if yaw < 0:
                    direction = "left"
                elif yaw > 0:
                    direction = "right"
                plan.update(
                    {
                        "valid": True,
                        "yaw": yaw,
                        "direction": direction,
                        "score": _safe_float(best_path.get("score", 0.0), 0.0),
                        "confidence": conf,
                    }
                )

        context.set("local_plan", plan)

        # Optionally emit a lightweight mapping recommendation for downstream
        # modules (navigation already supports mapping bias but this keeps a
        # separate, non-forcing hint channel).
        if plan.get("valid"):
            context.set(
                "mapping_recommendation",
                {
                    "timestamp": now,
                    "direction": plan["direction"],
                    "confidence": plan["confidence"],
                },
            )
