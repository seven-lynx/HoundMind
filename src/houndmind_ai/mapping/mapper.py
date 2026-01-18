from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from houndmind_ai.core.module import Module

logger = logging.getLogger(__name__)


class MappingModule(Module):
    """Lightweight mapping module with optional home map persistence.

    This does not implement full SLAM. It stores sensor snapshots and can save
    a "Home Map" file for later analysis or future navigation upgrades.
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.last_save_ts = 0.0

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("mapping", {})
        if not settings.get("enabled", True):
            return

        # Read sensor data and store a basic history for later mapping work.
        sensors = context.get("sensors") or {}
        mapping_state = context.get("mapping_state") or {"samples": []}

        scan_latest = context.get("scan_latest") or {}
        scan_angles = (
            scan_latest.get("angles", {}) if isinstance(scan_latest, dict) else {}
        )
        openings, safe_paths, best_path = self._analyze_scan_openings(
            scan_angles, settings
        )

        sample = {
            "timestamp": time.time(),
            "distance_cm": sensors.get("distance"),
            "touch": sensors.get("touch"),
            "sound": sensors.get("sound_detected"),
            "acc": sensors.get("acc"),
            "gyro": sensors.get("gyro"),
            "openings": openings,
            "safe_paths": safe_paths,
            "best_path": best_path,
        }
        mapping_state["samples"].append(sample)
        max_samples = int(settings.get("sample_history_max", 500))
        if max_samples > 0 and len(mapping_state["samples"]) > max_samples:
            mapping_state["samples"] = mapping_state["samples"][-max_samples:]
        max_age_s = float(settings.get("sample_max_age_s", 0))
        if max_age_s > 0:
            cutoff = time.time() - max_age_s
            mapping_state["samples"] = [
                entry
                for entry in mapping_state["samples"]
                if entry.get("timestamp", 0) >= cutoff
            ]
        context.set("mapping_state", mapping_state)

        context.set(
            "mapping_openings",
            {
                "timestamp": sample["timestamp"],
                "openings": openings,
                "safe_paths": safe_paths,
                "best_path": best_path,
            },
        )

        # Optional path-planning hook (future expansion).
        if settings.get("path_planning_enabled", False):
            hook = context.get("path_planning_hook")
            if callable(hook):
                try:
                    plan = hook(mapping_state, sample, settings)
                    context.set("path_planning", plan)
                except Exception:  # noqa: BLE001
                    logger.debug("Path planning hook failed", exc_info=True)

        # Persist a home map snapshot on a configured interval.
        save_interval = settings.get("home_map_save_interval_s", 30)
        now = time.time()
        if (
            settings.get("home_map_enabled", False)
            and now - self.last_save_ts >= save_interval
        ):
            self.save_home_map(mapping_state, settings)
            self.last_save_ts = now

    def save_home_map(self, mapping_state: dict, settings: dict) -> None:
        """Persist mapping samples to a JSON file for later analysis."""
        output_path = Path(settings.get("home_map_path", "data/home_map.json"))
        if not output_path.is_absolute():
            output_path = Path(__file__).resolve().parents[3] / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

        samples = list(mapping_state.get("samples", []))
        max_samples = int(settings.get("home_map_max_samples", 0))
        max_age_s = float(settings.get("home_map_max_age_s", 0))
        if max_age_s > 0:
            cutoff = time.time() - max_age_s
            samples = [
                entry for entry in samples if entry.get("timestamp", 0) >= cutoff
            ]
        if max_samples > 0 and len(samples) > max_samples:
            samples = samples[-max_samples:]

        payload = {
            "meta": {
                "saved_at": time.time(),
                "cell_size_cm": settings.get("cell_size_cm", 10),
                "grid_size": settings.get("grid_size", [100, 100]),
                "opening_min_width_cm": settings.get("opening_min_width_cm", 60),
                "safe_path_min_width_cm": settings.get("safe_path_min_width_cm", 40),
                "safe_path_score_weight_width": settings.get(
                    "safe_path_score_weight_width", 0.6
                ),
                "safe_path_score_weight_distance": settings.get(
                    "safe_path_score_weight_distance", 0.4
                ),
                "home_map_max_samples": max_samples,
                "home_map_max_age_s": max_age_s,
            },
            "samples": samples,
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Saved home map to %s", output_path)

    def stop(self, context) -> None:
        settings = (context.get("settings") or {}).get("mapping", {})
        if settings.get("home_map_enabled", False):
            mapping_state = context.get("mapping_state") or {"samples": []}
            self.save_home_map(mapping_state, settings)

    @staticmethod
    def _analyze_scan_openings(
        angles: dict, settings: dict
    ) -> tuple[list[dict], list[dict], dict | None]:
        if not isinstance(angles, dict) or not angles:
            return [], [], None

        min_open_width_cm = float(settings.get("opening_min_width_cm", 60))
        max_open_width_cm = float(settings.get("opening_max_width_cm", 120))
        min_open_conf = float(settings.get("opening_cell_conf_min", 0.6))
        min_safe_width_cm = float(settings.get("safe_path_min_width_cm", 40))
        max_safe_width_cm = float(settings.get("safe_path_max_width_cm", 200))
        min_safe_conf = float(settings.get("safe_path_cell_conf_min", 0.5))

        items = []
        for key, dist in angles.items():
            try:
                yaw = int(float(key))
                distance = float(dist)
            except Exception:
                continue
            if distance <= 0:
                continue
            items.append((yaw, distance))

        if not items:
            return [], [], None

        items.sort(key=lambda it: it[0])
        openings: list[dict] = []
        safe_paths: list[dict] = []

        def estimate_width_cm(dist: float, step_deg: float) -> float:
            return max(0.0, dist * (step_deg * 0.0174533))

        step_deg = float(settings.get("scan_step_deg", 0.0))
        if step_deg <= 0.0 and len(items) > 1:
            diffs = [abs(items[i + 1][0] - items[i][0]) for i in range(len(items) - 1)]
            diffs = [d for d in diffs if d > 0]
            if diffs:
                diffs.sort()
                mid = len(diffs) // 2
                step_deg = diffs[mid]
        if step_deg <= 0.0:
            step_deg = 15.0

        for yaw, dist in items:
            width_cm = estimate_width_cm(dist, step_deg)
            conf = min(1.0, dist / 200.0)
            entry = {
                "yaw": yaw,
                "distance_cm": dist,
                "width_cm": width_cm,
                "confidence": conf,
            }
            if (
                min_open_width_cm <= width_cm <= max_open_width_cm
                and conf >= min_open_conf
            ):
                openings.append(entry)
            if (
                min_safe_width_cm <= width_cm <= max_safe_width_cm
                and conf >= min_safe_conf
            ):
                safe_paths.append(entry)

        best_path = None
        if safe_paths:
            weight_width = float(settings.get("safe_path_score_weight_width", 0.6))
            weight_distance = float(
                settings.get("safe_path_score_weight_distance", 0.4)
            )
            best_score = -1.0
            for entry in safe_paths:
                score = (entry["width_cm"] * weight_width) + (
                    entry["distance_cm"] * weight_distance
                )
                if score > best_score:
                    best_score = score
                    best_path = {**entry, "score": score}

        return openings, safe_paths, best_path
