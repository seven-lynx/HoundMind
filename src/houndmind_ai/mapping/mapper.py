from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Any

from houndmind_ai.core.module import Module
from houndmind_ai.mapping.home_map import (
    HomeMap,
    build_document,
    load_home_map,
    write_document,
)

logger = logging.getLogger(__name__)


def _map_path(text: Any, default: str) -> Path:
    """Resolve a configured map path against the repository root, not the working directory.

    A relative path is the shipped default (`data/home_map.json`) and the service does not run from
    the repo root, so resolving against the cwd would put the map where nobody looks for it.
    """
    raw = text if isinstance(text, str) and text.strip() else default
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    return path


class MappingModule(Module):
    """Lightweight mapping module with optional home map persistence.

    This is not full SLAM. It stores sensor snapshots, keeps a hit-histogram grid, and saves a home
    map - grid included - that the next start loads back (`mapping/home_map.py`).
    """

    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.last_save_ts = 0.0
        # A loaded map waits here until the first tick can seed `mapping_state` with it.
        self._loaded: HomeMap | None = None

    def start(self, context) -> None:
        """Load the configured home map and publish what happened either way (L1.3)."""
        settings = (context.get("settings") or {}).get("mapping", {})
        settings = settings if isinstance(settings, dict) else {}
        configured = settings.get("home_map_load_path", "")
        if not (isinstance(configured, str) and configured.strip()):
            context.set(
                "home_map_status",
                {"loaded": False, "reason": "mapping.home_map_load_path is empty"},
            )
            return

        path = _map_path(configured, "data/home_map.json")
        result = load_home_map(path)
        if result.map is None:
            detail = "; ".join(result.problems) or result.reason or "unknown"
            logger.warning("Home map not loaded from %s: %s", path, detail)
            context.set(
                "home_map_status",
                {
                    "loaded": False,
                    "path": str(path),
                    "reason": result.reason,
                    "problems": list(result.problems),
                },
            )
            return

        self._loaded = result.map
        context.set("home_map", result.map.to_document())
        context.set(
            "home_map_status",
            {
                "loaded": True,
                "path": str(path),
                "version": result.map.version,
                "cells": result.map.cell_count,
                "notes": list(result.notes),
            },
        )
        logger.info("Loaded home map from %s (%d cells)", path, result.map.cell_count)

    def _seed_loaded_map(self, context) -> None:
        """Put the persisted cells into `mapping_state` once, before this tick adds to them.

        A live grid wins. The sweep counts hits per cell, so merging a loaded grid into a grid this
        process is already building would double every count it had seen twice.
        """
        loaded = self._loaded
        if loaded is None:
            return
        self._loaded = None
        mapping_state = context.get("mapping_state")
        if not isinstance(mapping_state, dict):
            mapping_state = {"samples": []}
        grid = mapping_state.get("grid")
        if isinstance(grid, dict) and grid.get("cells"):
            logger.debug("A live grid already exists; the loaded map stays read-only")
            return
        mapping_state["grid"] = loaded.as_grid()
        context.set("mapping_state", mapping_state)

    def tick(self, context) -> None:
        settings = (context.get("settings") or {}).get("mapping", {})
        if not settings.get("enabled", True):
            return

        # A map loaded at start seeds the grid before this tick measures into it (L1.3).
        self._seed_loaded_map(context)

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

        if isinstance(scan_angles, dict) and scan_angles:
            # The grid is derived, so the sweep it came from is kept: `home_map.build_document`
            # persists it, and a saved map with no angles could never be re-measured.
            mapping_state["last_sweep"] = {
                "timestamp": time.time(),
                "angles": dict(scan_angles),
            }

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

        # Optionally ingest sweep angles into a simple occupancy grid for
        # lightweight map-aware avoidance. This keeps a histogram of observed
        # hits by grid cell (coordinates in centimeters relative to robot).
        if bool(settings.get("grid_enabled", True)):
            try:
                self._ingest_into_grid(scan_angles, settings, mapping_state)
            except Exception:  # noqa: BLE001
                logger.debug("Grid ingestion failed", exc_info=True)

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
        """Write the map so the next start can read it back (L1.1).

        The document is built by `mapping/home_map.py`, which also loads it: one description of the
        format, so the writer cannot drift from the reader.
        """
        output_path = _map_path(
            settings.get("home_map_path", "data/home_map.json"), "data/home_map.json"
        )
        document = build_document(mapping_state, settings)
        try:
            write_document(output_path, document)
        except OSError as exc:
            # A read-only card or a full disk costs the map, not the walk.
            logger.warning("Home map not written to %s: %s", output_path, exc)
            return
        logger.info(
            "Saved home map to %s (%d cells)", output_path, len(document["grid"]["cells"])
        )

    def stop(self, context) -> None:
        settings = (context.get("settings") or {}).get("mapping", {})
        if settings.get("home_map_enabled", False):
            mapping_state = context.get("mapping_state") or {"samples": []}
            self.save_home_map(mapping_state, settings)

    def _ingest_into_grid(self, angles: dict, settings: dict, mapping_state: dict) -> None:
        if not isinstance(angles, dict) or not angles:
            return
        cell_size_cm = float(settings.get("cell_size_cm", 10.0))
        grid_size = settings.get("grid_size", [100, 100])
        try:
            gx = int(grid_size[0])
            gy = int(grid_size[1])
        except Exception:
            gx, gy = 100, 100
        half_x = gx // 2
        half_y = gy // 2

        grid = mapping_state.get("grid") or {"cells": {}}
        cells = grid.get("cells") or {}

        for key, raw in angles.items():
            try:
                yaw = float(key)
                dist = float(raw)
            except Exception:
                continue
            if dist <= 0:
                continue
            # Convert polar (distance cm, yaw deg) to grid indices. Yaw is
            # degrees where 0 = forward, positive = left.
            rad = math.radians(yaw)
            x_cm = dist * math.cos(rad)  # forward
            y_cm = dist * math.sin(rad)  # left
            ix = int(round(y_cm / cell_size_cm))
            iy = int(round(x_cm / cell_size_cm))
            # Bound to grid size
            if abs(ix) > half_x or abs(iy) > half_y:
                continue
            k = f"{ix},{iy}"
            cells[k] = cells.get(k, 0) + 1

        grid["cells"] = cells
        mapping_state["grid"] = grid

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


# ------------------------------------------------------------------ map geometry
#
# The grid is robot-centric: `_ingest_into_grid` writes one hit count per cell, keyed "ix,iy", where
# `ix` is centimetres to the dog's left and `iy` centimetres forward, both divided by
# `cell_size_cm`. Every point below is `(forward_cm, left_cm)` - the order the scan conversion
# already uses - and every function is pure, so a test (or a future consumer) can ask the map a
# question without standing up a runtime.

Point = tuple[float, float]


def cell_centre_cm(ix: int, iy: int, cell_size_cm: float = 10.0) -> Point:
    """The centre of a grid cell as `(forward_cm, left_cm)`."""
    return (iy * cell_size_cm, ix * cell_size_cm)


def landmark_distance(point_cm: Point, landmark_cm: Point) -> float:
    """Straight-line distance in centimetres between the dog and one landmark."""
    return math.hypot(landmark_cm[0] - point_cm[0], landmark_cm[1] - point_cm[1])


def wall_distance(point_cm: Point, start_cm: Point, end_cm: Point) -> float:
    """Distance from a point to a wall segment, clamped to its two ends.

    Anything past an endpoint is measured to that endpoint: a wall is only known between the
    corners someone surveyed, and extending it to an imaginary infinite line would report a
    distance to something the dog never saw.
    """
    fx = end_cm[0] - start_cm[0]
    fy = end_cm[1] - start_cm[1]
    length_sq = fx * fx + fy * fy
    if length_sq == 0.0:
        return landmark_distance(point_cm, start_cm)
    along = ((point_cm[0] - start_cm[0]) * fx + (point_cm[1] - start_cm[1]) * fy) / length_sq
    along = max(0.0, min(1.0, along))
    return landmark_distance(point_cm, (start_cm[0] + along * fx, start_cm[1] + along * fy))


def nearest_wall(
    grid: dict[str, Any] | None,
    point_cm: Point,
    max_cm: float,
    *,
    cell_size_cm: float = 10.0,
) -> float | None:
    """Distance to the nearest cell the sweep has recorded a hit in, capped at `max_cm`.

    `grid` is `mapping_state["grid"]` exactly as :meth:`MappingModule._ingest_into_grid` writes
    it. `None` means *no wall this map knows about* inside `max_cm` - an empty or stale grid is
    "unknown", not "clear", so callers must not read it as an obstacle-free corridor. That
    distinction is the reason this returns `None` rather than a sentinel distance.
    """
    if not isinstance(grid, dict):
        return None
    cells = grid.get("cells")
    if not isinstance(cells, dict) or not cells:
        return None
    best: float | None = None
    for key, hits in cells.items():
        try:
            ix_text, iy_text = str(key).split(",", 1)
            hit_count = int(hits or 0)
            ix = int(ix_text)
            iy = int(iy_text)
        except (TypeError, ValueError):
            continue
        if hit_count <= 0:
            continue
        distance = landmark_distance(point_cm, cell_centre_cm(ix, iy, cell_size_cm))
        if distance > max_cm:
            continue
        if best is None or distance < best:
            best = distance
    return best
