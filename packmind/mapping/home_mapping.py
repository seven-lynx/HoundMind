#!/usr/bin/env python3
"""
PiDog Home Mapping System (SLAM)
===============================

Version: 2025.10.29

Modern SLAM system for PiDog that creates and maintains a persistent map
of the home with obstacle tracking, opening and safe path detection, and localization.

Features:
- Grid-based occupancy mapping
- Dead reckoning with IMU integration
- Persistent map storage/loading
- Opening and safe path detection
- Path planning integration

Author: 7Lynx
"""

from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass, asdict
from enum import Enum
import threading
import time
import pickle
import math
import numpy as np


# Minimal placeholder dataclasses for missing types
@dataclass
class Position:
    x: float
    y: float
    heading: float = 0.0
    confidence: float = 1.0
    timestamp: float = 0.0


class CellType(Enum):
    UNKNOWN = 0
    FREE = 1
    OBSTACLE = 2


@dataclass
class MapCell:
    cell_type: CellType = CellType.UNKNOWN
    confidence: float = 0.0
    last_observed: float = 0.0
    observations: int = 0
    height_estimate: float = 0.0
    room_id: int = -1
    landmark_type: str = ''

@dataclass
class SafePath:
    """Detected corridor-like open passage with flanking obstacles and consistent heading.

    A safe path represents a run of FREE cells of at least a minimum length where the
    cross-axis shows obstacles on both sides (like a hallway or clear aisle). It stores
    the approximate centerline as a segment with an orientation and estimated width.
    """
    path_id: int
    start: Position  # segment start (grid coords)
    end: Position    # segment end (grid coords)
    orientation: str  # "horizontal" or "vertical"
    width_cm: float
    length_cells: int
    confidence: float


class HomeMap:
    """Main home mapping system (openings + safe paths)"""
    
    def __init__(self, cell_size_cm: float = 10.0, max_size: Tuple[int, int] = (500, 500)):
        """
        Initialize house map
        
        Args:
            cell_size_cm: Size of each grid cell in centimeters
            max_size: Maximum grid size (width, height)
        """
        self.cell_size_cm = cell_size_cm
        self.max_size = max_size
        self.grid = np.full(max_size, MapCell(), dtype=object)

        # Initialize all cells
        for i in range(max_size[0]):
            for j in range(max_size[1]):
                self.grid[i, j] = MapCell()

        # Current position tracking
        self.current_position = Position(
            x=max_size[0] // 2,  # Start at center
            y=max_size[1] // 2,
            heading=0.0,
            timestamp=time.time()
        )

        # Map metadata
        self.creation_time = time.time()
        self.last_update = time.time()
        self.total_scans = 0
        self.map_bounds = {
            'min_x': max_size[0] // 2,
            'max_x': max_size[0] // 2,
            'min_y': max_size[1] // 2,
            'max_y': max_size[1] // 2
        }

        # Openings: explicitly modeled wall/constriction gaps
        self.openings = {}
        self.next_opening_id = 1
        # Safe paths: corridor-like centerlines
        self.safe_paths = {}
        self.next_safe_path_id = 1

        # Position tracking
        self.position_history = []
        self.odometry_error = 0.0  # Accumulated error estimate

        # Mapping parameters
        self.confidence_threshold = 0.7
        self.max_obstacle_age = 300.0  # 5 minutes for dynamic obstacles
        # Structure thresholds (tunable)
        self.opening_min_width_cm = 60.0
        self.opening_max_width_cm = 120.0
        self.opening_cell_conf_min = 0.6
        # Safe path detection thresholds
        self.safepath_min_width_cm = 40.0
        self.safepath_max_width_cm = 200.0
        self.safepath_min_length_cells = 6
        self.safepath_cell_conf_min = 0.5
        # For performance, skip opening scans if map is tiny
        self._last_opening_scan_ts = 0.0
        self._last_safepath_scan_ts = 0.0

        # Threading for background processing
        self.map_lock = threading.RLock()
        self.processing_thread = None
    
    def update_position(self, delta_x: float, delta_y: float, delta_heading: float, 
                       confidence: float = 0.9):
        """
        Update robot position using dead reckoning
        
        Args:
            delta_x: Change in X position (cm)
            delta_y: Change in Y position (cm) 
            delta_heading: Change in heading (degrees)
            confidence: Confidence in this movement update
        """
        with self.map_lock:
            # Convert cm to grid coordinates
            grid_dx = delta_x / self.cell_size_cm
            grid_dy = delta_y / self.cell_size_cm
            
            # Apply rotation based on current heading
            current_heading_rad = math.radians(self.current_position.heading)
            
            # Rotate movement vector by current heading
            rotated_dx = grid_dx * math.cos(current_heading_rad) - grid_dy * math.sin(current_heading_rad)
            rotated_dy = grid_dx * math.sin(current_heading_rad) + grid_dy * math.cos(current_heading_rad)
            
            # Update position
            new_x = self.current_position.x + rotated_dx
            new_y = self.current_position.y + rotated_dy
            new_heading = (self.current_position.heading + delta_heading) % 360.0
            
            # Bounds checking
            new_x = max(0, min(self.max_size[0] - 1, new_x))
            new_y = max(0, min(self.max_size[1] - 1, new_y))
            
            # Update current position
            old_position = Position(
                x=self.current_position.x,
                y=self.current_position.y,
                heading=self.current_position.heading,
                confidence=self.current_position.confidence,
                timestamp=self.current_position.timestamp
            )
            self.current_position.x = new_x
            self.current_position.y = new_y
            self.current_position.heading = new_heading
            self.current_position.confidence = min(self.current_position.confidence, confidence)
            self.current_position.timestamp = time.time()
            # Add to history
            self.position_history.append(old_position)
            # Keep history manageable
            if len(self.position_history) > 1000:
                self.position_history = self.position_history[-500:]
    
    def _mark_free_path(self, start_x: float, start_y: float, end_x: float, end_y: float):
        """Mark cells as FREE along the path from start to end using Bresenham's algorithm"""
        x0, y0 = int(round(start_x)), int(round(start_y))
        x1, y1 = int(round(end_x)), int(round(end_y))
        # Bresenham's line algorithm
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y = x0, y0
        while True:
            if x == x1 and y == y1:
                break
            if 0 <= x < self.max_size[0] and 0 <= y < self.max_size[1]:
                cell = self.grid[x, y]
                if cell.cell_type == CellType.UNKNOWN:
                    cell.cell_type = CellType.FREE
                    cell.confidence = min(1.0, cell.confidence + 0.1)
                    cell.last_observed = time.time()
                    cell.observations += 1
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    # Removed broken/orphaned background processing and exception handling code
    
    
    # Dynamic obstacle cleanup removed (legacy)
    
    def get_position(self) -> Position:
        """Get current robot position"""
        return Position(
            x=self.current_position.x,
            y=self.current_position.y,
            heading=self.current_position.heading,
            confidence=self.current_position.confidence,
            timestamp=self.current_position.timestamp
        )
    
    def get_map_summary(self) -> Dict:
        """Get summary of current map state"""
        with self.map_lock:
            # Count cell types
            cell_counts = {cell_type: 0 for cell_type in CellType}
            for x in range(self.map_bounds['min_x'], self.map_bounds['max_x'] + 1):
                for y in range(self.map_bounds['min_y'], self.map_bounds['max_y'] + 1):
                    cell_type = self.grid[x, y].cell_type
                    cell_counts[cell_type] += 1
            mapped_area_m2 = (
                (self.map_bounds['max_x'] - self.map_bounds['min_x']) *
                (self.map_bounds['max_y'] - self.map_bounds['min_y']) *
                (self.cell_size_cm / 100) ** 2
            )
            return {
                "position": asdict(self.current_position),
                "map_bounds": self.map_bounds,
                "mapped_area_m2": mapped_area_m2,
                "cell_counts": {cell_type.name: count for cell_type, count in cell_counts.items()},
                "total_scans": self.total_scans,
                "openings": len(self.openings),
                "safe_paths": len(self.safe_paths),
                "odometry_error": self.odometry_error,
                "last_update": self.last_update
            }
    

    # All legacy save/load/serialize/deserialize code removed

    def _is_valid_index(self, x: int, y: int) -> bool:
        return 0 <= x < self.max_size[0] and 0 <= y < self.max_size[1]

    def _cell_conf(self, x: int, y: int) -> float:
        if not self._is_valid_index(x, y):
            return 0.0
        return float(self.grid[x, y].confidence)

    # Remove _doorway_at and _add_doorway_if_new methods entirely

    def _is_obstacle(self, x: int, y: int) -> bool:
        if not self._is_valid_index(x, y):
            return False
        cell = self.grid[x, y]
        return (cell.cell_type == CellType.OBSTACLE and cell.confidence > self.confidence_threshold)

    # Doorway add removed (legacy)

    # ----------------------- Safe path detection -----------------------
    def _detect_safe_paths_global(self) -> None:
        """Scan mapped area to detect corridor-like safe paths.

        A safe path is a run of FREE cells with consistent cross-axis obstacle flanking
        and width within configured limits, extended to at least a minimum length.
        We detect both horizontal and vertical orientations.
        """
        with self.map_lock:
            if (self.map_bounds['max_x'] - self.map_bounds['min_x'] < 10 or
                self.map_bounds['max_y'] - self.map_bounds['min_y'] < 10):
                return  # too small, skip

            min_w_cells = max(1, int(round(self.safepath_min_width_cm / self.cell_size_cm)))
            max_w_cells = max(min_w_cells, int(round(self.safepath_max_width_cm / self.cell_size_cm)))

            step = 3  # coarser sampling for performance
            for x in range(self.map_bounds['min_x'], self.map_bounds['max_x'] + 1, step):
                for y in range(self.map_bounds['min_y'], self.map_bounds['max_y'] + 1, step):
                    if not self._is_valid_index(x, y):
                        continue
                    if self.grid[x, y].cell_type != CellType.FREE or self.grid[x, y].confidence < self.safepath_cell_conf_min:
                        continue

                    # Horizontal candidate (east-west corridor)
                    seg = self._extend_safepath_from(x, y, orientation="horizontal", min_w=min_w_cells, max_w=max_w_cells)
                    if seg is not None:
                        self._add_safe_path_if_new(seg)
                        continue
                    # Vertical candidate (north-south corridor)
                    seg = self._extend_safepath_from(x, y, orientation="vertical", min_w=min_w_cells, max_w=max_w_cells)
                    if seg is not None:
                        self._add_safe_path_if_new(seg)

    def _extend_safepath_from(self, x: int, y: int, orientation: str, min_w: int, max_w: int) -> Optional[SafePath]:
        """Try to extend a safe path segment from a seed cell if corridor conditions hold.

        Returns a SafePath if a sufficiently long segment is found, else None.
        """
        if orientation == "horizontal":
            # First, measure cross-axis width (north/south) at seed
            up = 0
            while self._is_valid_index(x, y - (up + 1)) and self.grid[x, y - (up + 1)].cell_type == CellType.FREE:
                up += 1
                if up > max_w:
                    break
            down = 0
            while self._is_valid_index(x, y + (down + 1)) and self.grid[x, y + (down + 1)].cell_type == CellType.FREE:
                down += 1
                if down > max_w:
                    break
            width_cells = up + 1 + down
            if width_cells < min_w or width_cells > max_w:
                return None
            # Require obstacles beyond edges
            if not any(self._is_obstacle(x, y - d) for d in range(up + 1, up + 3) if self._is_valid_index(x, y - d)):
                return None
            if not any(self._is_obstacle(x, y + d) for d in range(down + 1, down + 3) if self._is_valid_index(x, y + d)):
                return None

            # Extend along x both directions while width stays in [min_w,max_w]
            left_x = x
            right_x = x
            total_len = 1
            accum_width = width_cells
            # Extend left
            cx = x - 1
            while self._is_valid_index(cx, y) and self.grid[cx, y].cell_type == CellType.FREE and self.grid[cx, y].confidence >= self.safepath_cell_conf_min:
                up2 = 0
                while self._is_valid_index(cx, y - (up2 + 1)) and self.grid[cx, y - (up2 + 1)].cell_type == CellType.FREE:
                    up2 += 1
                    if up2 > max_w:
                        break
                down2 = 0
                while self._is_valid_index(cx, y + (down2 + 1)) and self.grid[cx, y + (down2 + 1)].cell_type == CellType.FREE:
                    down2 += 1
                    if down2 > max_w:
                        break
                w2 = up2 + 1 + down2
                if w2 < min_w or w2 > max_w:
                    break
                if not any(self._is_obstacle(cx, y - d) for d in range(up2 + 1, up2 + 3) if self._is_valid_index(cx, y - d)):
                    break
                if not any(self._is_obstacle(cx, y + d) for d in range(down2 + 1, down2 + 3) if self._is_valid_index(cx, y + d)):
                    break
                left_x = cx
                total_len += 1
                accum_width += w2
                cx -= 1
            # Extend right
            cx = x + 1
            while self._is_valid_index(cx, y) and self.grid[cx, y].cell_type == CellType.FREE and self.grid[cx, y].confidence >= self.safepath_cell_conf_min:
                up2 = 0
                while self._is_valid_index(cx, y - (up2 + 1)) and self.grid[cx, y - (up2 + 1)].cell_type == CellType.FREE:
                    up2 += 1
                    if up2 > max_w:
                        break
                down2 = 0
                while self._is_valid_index(cx, y + (down2 + 1)) and self.grid[cx, y + (down2 + 1)].cell_type == CellType.FREE:
                    down2 += 1
                    if down2 > max_w:
                        break
                w2 = up2 + 1 + down2
                if w2 < min_w or w2 > max_w:
                    break
                if not any(self._is_obstacle(cx, y - d) for d in range(up2 + 1, up2 + 3) if self._is_valid_index(cx, y - d)):
                    break
                if not any(self._is_obstacle(cx, y + d) for d in range(down2 + 1, down2 + 3) if self._is_valid_index(cx, y + d)):
                    break
                right_x = cx
                total_len += 1
                accum_width += w2
                cx += 1

            if total_len < self.safepath_min_length_cells:
                return None
            avg_w_cells = accum_width / total_len
            width_cm = avg_w_cells * self.cell_size_cm
            start = Position(x=left_x, y=y, heading=0.0, confidence=1.0)
            end = Position(x=right_x, y=y, heading=0.0, confidence=1.0)
            return SafePath(
                path_id=-1,
                start=start,
                end=end,
                orientation="horizontal",
                width_cm=width_cm,
                length_cells=total_len,
                confidence=0.7,
            )
        else:
            # Vertical
            left = 0  # reuse variables as up/down orientation
            # Measure cross-axis width (east/west) at seed
            west = 0
            while self._is_valid_index(x - (west + 1), y) and self.grid[x - (west + 1), y].cell_type == CellType.FREE:
                west += 1
                if west > max_w:
                    break
            east = 0
            while self._is_valid_index(x + (east + 1), y) and self.grid[x + (east + 1), y].cell_type == CellType.FREE:
                east += 1
                if east > max_w:
                    break
            width_cells = west + 1 + east
            if width_cells < min_w or width_cells > max_w:
                return None
            if not any(self._is_obstacle(x - d, y) for d in range(west + 1, west + 3) if self._is_valid_index(x - d, y)):
                return None
            if not any(self._is_obstacle(x + d, y) for d in range(east + 1, east + 3) if self._is_valid_index(x + d, y)):
                return None

            top_y = y
            bottom_y = y
            total_len = 1
            accum_width = width_cells
            cy = y - 1
            while self._is_valid_index(x, cy) and self.grid[x, cy].cell_type == CellType.FREE and self.grid[x, cy].confidence >= self.safepath_cell_conf_min:
                west2 = 0
                while self._is_valid_index(x - (west2 + 1), cy) and self.grid[x - (west2 + 1), cy].cell_type == CellType.FREE:
                    west2 += 1
                    if west2 > max_w:
                        break
                east2 = 0
                while self._is_valid_index(x + (east2 + 1), cy) and self.grid[x + (east2 + 1), cy].cell_type == CellType.FREE:
                    east2 += 1
                    if east2 > max_w:
                        break
                w2 = west2 + 1 + east2
                if w2 < min_w or w2 > max_w:
                    break
                if not any(self._is_obstacle(x - d, cy) for d in range(west2 + 1, west2 + 3) if self._is_valid_index(x - d, cy)):
                    break
                if not any(self._is_obstacle(x + d, cy) for d in range(east2 + 1, east2 + 3) if self._is_valid_index(x + d, cy)):
                    break
                top_y = cy
                total_len += 1
                accum_width += w2
                cy -= 1

            cy = y + 1
            while self._is_valid_index(x, cy) and self.grid[x, cy].cell_type == CellType.FREE and self.grid[x, cy].confidence >= self.safepath_cell_conf_min:
                west2 = 0
                while self._is_valid_index(x - (west2 + 1), cy) and self.grid[x - (west2 + 1), cy].cell_type == CellType.FREE:
                    west2 += 1
                    if west2 > max_w:
                        break
                east2 = 0
                while self._is_valid_index(x + (east2 + 1), cy) and self.grid[x + (east2 + 1), cy].cell_type == CellType.FREE:
                    east2 += 1
                    if east2 > max_w:
                        break
                w2 = west2 + 1 + east2
                if w2 < min_w or w2 > max_w:
                    break
                if not any(self._is_obstacle(x - d, cy) for d in range(west2 + 1, west2 + 3) if self._is_valid_index(x - d, cy)):
                    break
                if not any(self._is_obstacle(x + d, cy) for d in range(east2 + 1, east2 + 3) if self._is_valid_index(x + d, cy)):
                    break
                bottom_y = cy
                total_len += 1
                accum_width += w2
                cy += 1

            if total_len < self.safepath_min_length_cells:
                return None
            avg_w_cells = accum_width / total_len
            width_cm = avg_w_cells * self.cell_size_cm
            start = Position(x=x, y=top_y, heading=0.0, confidence=1.0)
            end = Position(x=x, y=bottom_y, heading=0.0, confidence=1.0)
            return SafePath(
                path_id=-1,
                start=start,
                end=end,
                orientation="vertical",
                width_cm=width_cm,
                length_cells=total_len,
                confidence=0.7,
            )

    def _add_safe_path_if_new(self, sp: SafePath) -> None:
        # Merge/skip if a similar orientation segment exists overlapping within ~3 cells
        for existing in self.safe_paths.values():
            if existing.orientation != sp.orientation:
                continue
            # Compute midpoint distance
            mx1 = (existing.start.x + existing.end.x) / 2.0
            my1 = (existing.start.y + existing.end.y) / 2.0
            mx2 = (sp.start.x + sp.end.x) / 2.0
            my2 = (sp.start.y + sp.end.y) / 2.0
            if abs(mx1 - mx2) <= 3 and abs(my1 - my2) <= 3:
                return
        sp2 = SafePath(
            path_id=self.next_safe_path_id,
            start=sp.start,
            end=sp.end,
            orientation=sp.orientation,
            width_cm=sp.width_cm,
            length_cells=sp.length_cells,
            confidence=sp.confidence,
        )
        self.safe_paths[self.next_safe_path_id] = sp2
        print(f"🛤️ Safe path detected: {sp.orientation} from ({int(sp.start.x)},{int(sp.start.y)}) to ({int(sp.end.x)},{int(sp.end.y)}) ~{sp.width_cm:.0f}cm wide, len~{sp.length_cells} cells")
        self.next_safe_path_id += 1


class PiDogSLAM:
    """Integration class for PiDog SLAM system"""
    
    def __init__(self, map_file: str = "pidog_house_map.pkl"):
        self.map_file = map_file
        self.step_distance_cm = 15.0  # Average step distance
        self.turn_angle_degrees = 45.0  # Average turn angle
        # Legacy house_map and map loading removed
    
    # All legacy house_map, landmark, and room logic removed
