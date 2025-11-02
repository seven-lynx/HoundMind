#!/usr/bin/env python3
"""
PiDog Home Mapping System (SLAM)
===============================

Version: 2025.11.01

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
    # --- Advanced map query API ---
    def get_obstacles_near(self, x: int, y: int, radius: int = 5) -> list:
        """Return list of (i, j) obstacle cells within radius of (x, y)."""
        results = []
        for i in range(max(0, x - radius), min(self.max_size[0], x + radius + 1)):
            for j in range(max(0, y - radius), min(self.max_size[1], y + radius + 1)):
                cell = self.grid[i, j]
                if cell.cell_type == CellType.OBSTACLE and cell.confidence > self.confidence_threshold:
                    results.append((i, j))
        return results

    def get_free_cells_near(self, x: int, y: int, radius: int = 5) -> list:
        """Return list of (i, j) free cells within radius of (x, y)."""
        results = []
        for i in range(max(0, x - radius), min(self.max_size[0], x + radius + 1)):
            for j in range(max(0, y - radius), min(self.max_size[1], y + radius + 1)):
                cell = self.grid[i, j]
                if cell.cell_type == CellType.FREE and cell.confidence > 0.5:
                    results.append((i, j))
        return results

    def get_safe_paths_near(self, x: int, y: int, radius: int = 10) -> list:
        """Return list of SafePath objects whose center is within radius of (x, y)."""
        results = []
        for sp in self.safe_paths.values():
            mx = (sp.start.x + sp.end.x) / 2.0
            my = (sp.start.y + sp.end.y) / 2.0
            if abs(mx - x) <= radius and abs(my - y) <= radius:
                results.append(sp)
        return results

    def get_cells_with_label(self, label: str) -> list:
        """Return list of (i, j) cells with the given semantic label."""
        results = []
        for i in range(self.max_size[0]):
            for j in range(self.max_size[1]):
                if self.grid[i, j].landmark_type == label:
                    results.append((i, j))
        return results

    def find_nearest_label(self, x: int, y: int, label: str) -> Optional[tuple]:
        """Return (i, j) of nearest cell with the given label, or None if not found."""
        min_dist = float('inf')
        nearest = None
        for i, j in self.get_cells_with_label(label):
            dist = (i - x) ** 2 + (j - y) ** 2
            if dist < min_dist:
                min_dist = dist
                nearest = (i, j)
        return nearest

    def is_cell_navigable(self, x: int, y: int) -> bool:
        """Return True if cell is free and not a no-go zone."""
        if not self._is_valid_index(x, y):
            return False
        cell = self.grid[x, y]
        if cell.cell_type != CellType.FREE or cell.confidence < 0.5:
            return False
        if cell.landmark_type and 'no-go' in cell.landmark_type.lower():
            return False
        return True
    def export_map_image(self, filename: str = "house_map.png", show: bool = False):
        """
        Export the current map as an image with overlays for safe paths, openings, and semantic regions.
        Requires matplotlib (pip install matplotlib).
        Args:
            filename: Output image file path
            show: If True, display the image interactively
        """
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
        import numpy as np
        grid_img = np.zeros((self.max_size[1], self.max_size[0], 3), dtype=np.uint8)
        # Color cells by type
        for i in range(self.max_size[0]):
            for j in range(self.max_size[1]):
                cell = self.grid[i, j]
                if cell.cell_type == CellType.OBSTACLE:
                    grid_img[j, i] = [200, 0, 0]  # Red
                elif cell.cell_type == CellType.FREE:
                    grid_img[j, i] = [220, 220, 220]  # Light gray
                else:
                    grid_img[j, i] = [40, 40, 40]  # Dark gray
                # Overlay semantic label (color by label hash)
                if cell.landmark_type:
                    h = abs(hash(cell.landmark_type)) % 255
                    grid_img[j, i] = [(grid_img[j, i][0] + h) % 255, (grid_img[j, i][1] + h//2) % 255, (grid_img[j, i][2] + h//3) % 255]
        fig, ax = plt.subplots(figsize=(10, 10))
        ax.imshow(grid_img, origin='lower')
        # Overlay safe paths
        for sp in self.safe_paths.values():
            ax.plot([sp.start.x, sp.end.x], [sp.start.y, sp.end.y], color='cyan', linewidth=2, label='SafePath')
        # Overlay openings (if any)
        for op in getattr(self, 'openings', {}).values():
            if hasattr(op, 'x') and hasattr(op, 'y'):
                ax.scatter(op.x, op.y, color='yellow', marker='o', s=40, label='Opening')  # type: ignore
        # Overlay anchors (if any)
        if hasattr(self, 'anchors'):
            for aid, pos in self.anchors.items():
                ax.scatter(pos.x, pos.y, color='magenta', marker='s', s=60, label='Anchor')  # 's' is a valid marker (square)  # type: ignore
                ax.text(pos.x, pos.y, str(aid), color='magenta', fontsize=8)
        # Current position
        ax.scatter(self.current_position.x, self.current_position.y, color='lime', marker='o', s=60, label='Robot')  # 'o' is a valid marker  # type: ignore
        ax.set_title('HomeMap Visualization')
        ax.set_xlabel('X (grid)')
        ax.set_ylabel('Y (grid)')
        ax.set_xlim(0, self.max_size[0])
        ax.set_ylim(0, self.max_size[1])
        ax.legend(loc='upper right', fontsize=8)
        plt.tight_layout()
        plt.savefig(filename)
        if show:
            plt.show()
        plt.close(fig)
    def fuse_sensor_data(self, sensor_data: list):
        """
        Fuse multiple sensor readings for improved mapping.
        Args:
            sensor_data: List of dicts, each with keys:
                - 'x', 'y': grid coordinates
                - 'sensor_type': 'camera', 'imu', 'ultrasonic', 'ir', etc.
                - 'reading': sensor reading (meaning depends on type)
                - 'confidence': confidence in this reading (0.0-1.0)
        Example:
            [
                {'x': 10, 'y': 20, 'sensor_type': 'camera', 'reading': 1.0, 'confidence': 0.8},
                {'x': 10, 'y': 20, 'sensor_type': 'ultrasonic', 'reading': 25, 'confidence': 1.0},
            ]
        """
        for entry in sensor_data:
            x = entry.get('x')
            y = entry.get('y')
            sensor_type = entry.get('sensor_type')
            reading = entry.get('reading')
            confidence = entry.get('confidence', 1.0)
            if x is not None and y is not None and sensor_type and reading is not None:
                self.update_cell_from_sensor(x, y, sensor_type, reading, confidence)
    # --- Semantic map annotation support ---
    def set_cell_label(self, x: int, y: int, label: str):
        """Set a semantic label for a single cell (e.g., 'kitchen', 'charging_station', 'no-go')."""
        if not self._is_valid_index(x, y):
            return
        cell = self.grid[x, y]
        cell.landmark_type = label

    def get_cell_label(self, x: int, y: int) -> str:
        """Get the semantic label for a cell, or empty string if none."""
        if not self._is_valid_index(x, y):
            return ''
        return self.grid[x, y].landmark_type

    def annotate_region(self, x0: int, y0: int, x1: int, y1: int, label: str):
        """Set a semantic label for a rectangular region of the map."""
        for i in range(min(x0, x1), max(x0, x1) + 1):
            for j in range(min(y0, y1), max(y0, y1) + 1):
                self.set_cell_label(i, j, label)

    def get_region_labels(self, x0: int, y0: int, x1: int, y1: int) -> set:
        """Get all unique semantic labels in a rectangular region."""
        labels = set()
        for i in range(min(x0, x1), max(x0, x1) + 1):
            for j in range(min(y0, y1), max(y0, y1) + 1):
                label = self.get_cell_label(i, j)
                if label:
                    labels.add(label)
        return labels
    # --- Visual anchor/loop closure support ---
    def register_anchor(self, anchor_id: str, position: Optional[Position] = None, heading: Optional[float] = None):
        """
        Register a visual anchor (e.g., AprilTag, QR code) at the current or given position.
        Args:
            anchor_id: Unique string for the anchor (e.g., tag ID)
            position: Position object (optional, defaults to current position)
            heading: Heading at anchor (optional, defaults to current heading)
        """
        if not hasattr(self, 'anchors'):
            self.anchors = {}
        if position is None:
            position = Position(
                x=self.current_position.x,
                y=self.current_position.y,
                heading=self.current_position.heading,
                confidence=self.current_position.confidence,
                timestamp=time.time(),
            )
        if heading is not None:
            position.heading = heading
        self.anchors[anchor_id] = position

    def get_anchor(self, anchor_id: str) -> Optional[Position]:
        """Return the stored position for a given anchor ID, or None."""
        if hasattr(self, 'anchors') and anchor_id in self.anchors:
            return self.anchors[anchor_id]
        return None

    def correct_position_with_anchor(self, anchor_id: str, update_heading: bool = True) -> bool:
        """
        If a known anchor is detected, snap the robot's position (and optionally heading) to the anchor's stored value.
        Returns True if correction was applied.
        """
        anchor = self.get_anchor(anchor_id)
        if anchor is None:
            return False
        self.current_position.x = anchor.x
        self.current_position.y = anchor.y
        if update_heading:
            self.current_position.heading = anchor.heading
        self.current_position.confidence = 1.0
        self.current_position.timestamp = time.time()
        return True
    def fade_dynamic_obstacles(self, fade_time: float = 300.0, fade_rate: float = 0.05):
        """
        Periodically decay confidence for OBSTACLE cells not observed recently.
        Args:
            fade_time: Time in seconds after which to start fading (default: 5 min)
            fade_rate: Amount to decay confidence per call (default: 0.05)
        """
        now = time.time()
        for i in range(self.max_size[0]):
            for j in range(self.max_size[1]):
                cell = self.grid[i, j]
                if cell.cell_type == CellType.OBSTACLE:
                    time_since_obs = now - cell.last_observed
                    if time_since_obs > fade_time:
                        cell.confidence = max(0.0, cell.confidence - fade_rate)
                        if cell.confidence < self.confidence_threshold:
                            cell.cell_type = CellType.UNKNOWN
    def update_cell_from_sensor(self, x: int, y: int, sensor_type: str, reading: float, confidence: float = 1.0):
        """
        Update a map cell's occupancy probability using Bayesian logic based on sensor input.
        Args:
            x, y: Grid coordinates
            sensor_type: 'camera', 'imu', 'ultrasonic', 'ir', etc.
            reading: Sensor reading (meaning depends on sensor_type)
            confidence: Confidence in this reading (0.0-1.0)
        """
        if not self._is_valid_index(x, y):
            return
        cell = self.grid[x, y]
        prior = cell.confidence
        # Simple Bayesian update: P(occ|z) = (P(z|occ)*P(occ)) / normalization
        # For now, use fixed likelihoods per sensor type
        if sensor_type == 'ultrasonic' or sensor_type == 'ir':
            # reading: distance in cm; if very close, likely obstacle
            if reading < 30:
                p_occ = 0.9 * confidence
                p_free = 0.1 * confidence
            else:
                p_occ = 0.1 * confidence
                p_free = 0.9 * confidence
        elif sensor_type == 'camera':
            # reading: 1.0 = obstacle detected, 0.0 = free, in between = uncertain
            p_occ = reading * confidence
            p_free = (1.0 - reading) * confidence
        elif sensor_type == 'imu':
            # IMU is for position, not direct occupancy, so skip
            return
        else:
            # Unknown sensor, ignore
            return

        # Bayesian update (log odds for numerical stability)
        def to_logodds(p):
            eps = 1e-6
            return math.log(max(eps, min(1-eps, p)) / max(eps, min(1-eps, 1-p)))
        def from_logodds(l):
            return 1.0 / (1.0 + math.exp(-l))

        l_prior = to_logodds(prior)
        l_occ = to_logodds(p_occ)
        l_free = to_logodds(p_free)
        # Update: add log odds (simplified for binary case)
        l_post = l_prior + (l_occ - l_free)
        post = from_logodds(l_post)
        cell.confidence = max(0.0, min(1.0, post))
        # Update cell type if confidence crosses threshold
        if cell.confidence > self.confidence_threshold:
            cell.cell_type = CellType.OBSTACLE
        elif cell.confidence < 1.0 - self.confidence_threshold:
            cell.cell_type = CellType.FREE
        cell.last_observed = time.time()
        cell.observations += 1
    """Main home mapping system (openings + safe paths)"""
    
    def __init__(self, cell_size_cm: float = 10.0, max_size: Tuple[int, int] = (500, 500), config: Optional[object] = None):
        """
        Initialize house map
        Args:
            cell_size_cm: Size of each grid cell in centimeters
            max_size: Maximum grid size (width, height)
            config: Optional config object (PiDogConfig) for user-tunable parameters
        """
        self.config = config
        self.cell_size_cm = getattr(config, 'MAPPING_CELL_SIZE_CM', cell_size_cm) if config else cell_size_cm
        self.max_size = getattr(config, 'MAPPING_MAX_SIZE', max_size) if config else max_size
        self.grid = np.empty(self.max_size, dtype=object)
        for i in range(self.max_size[0]):
            for j in range(self.max_size[1]):
                self.grid[i, j] = MapCell()
        self.current_position = Position(
            x=self.max_size[0] // 2,  # Start at center
            y=self.max_size[1] // 2,
            heading=0.0,
            timestamp=time.time()
        )
        self.total_scans = 0
        self.map_bounds = {
            'min_x': self.max_size[0] // 2,
            'max_x': self.max_size[0] // 2,
            'min_y': self.max_size[1] // 2,
            'max_y': self.max_size[1] // 2
        }
        self.next_opening_id = 1
        self.openings = {}
        self.safe_paths = {}
        self.next_safe_path_id = 1
        self.position_history = []
        self.odometry_error = 0.0  # Accumulated error estimate
        self.confidence_threshold = getattr(config, 'MAPPING_CONFIDENCE_THRESHOLD', 0.7) if config else 0.7
        self.max_obstacle_age = getattr(config, 'MAPPING_MAX_OBSTACLE_AGE', 300.0) if config else 300.0
        self.opening_min_width_cm = getattr(config, 'MAPPING_OPENING_MIN_WIDTH_CM', 60.0) if config else 60.0
        self.opening_max_width_cm = getattr(config, 'MAPPING_OPENING_MAX_WIDTH_CM', 120.0) if config else 120.0
        self.opening_cell_conf_min = getattr(config, 'MAPPING_OPENING_CELL_CONF_MIN', 0.6) if config else 0.6
        self.safepath_min_width_cm = getattr(config, 'MAPPING_SAFEPATH_MIN_WIDTH_CM', 40.0) if config else 40.0
        self.safepath_max_width_cm = getattr(config, 'MAPPING_SAFEPATH_MAX_WIDTH_CM', 200.0) if config else 200.0
        self.safepath_min_length_cells = getattr(config, 'MAPPING_SAFEPATH_MIN_LENGTH_CELLS', 6) if config else 6
        self.safepath_cell_conf_min = getattr(config, 'MAPPING_SAFEPATH_CELL_CONF_MIN', 0.5) if config else 0.5
        self.processing_thread = None
        self.map_lock = threading.Lock()
        self.anchors = {}
    
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
            cell_counts = {cell_type: 0 for cell_type in list(CellType)}
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
                # "last_update": self.last_update  # Removed: attribute not defined
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
    def update_from_scan(self, scan_results: dict, position: Optional[tuple] = None, heading: Optional[float] = None, cell_size_cm: Optional[float] = None):
        """
        Update the occupancy grid from a scan (e.g., {'forward': dist, 'left': dist, ...}).
        Args:
            scan_results: dict of direction->distance (cm)
            position: (x, y) grid coordinates (optional, defaults to map center)
            heading: robot heading in degrees (optional, defaults to 0)
            cell_size_cm: override cell size (optional)
        """
        if not hasattr(self, 'house_map'):
            return
        house_map = getattr(self, 'house_map', None)
        if house_map is None:
            return
        if position is None:
            # Default to map center
            x = house_map.max_size[0] // 2
            y = house_map.max_size[1] // 2
        else:
            x, y = position
        if heading is None:
            heading = 0.0
        if cell_size_cm is None:
            cell_size_cm = house_map.cell_size_cm
        # Map direction to angle offset
        direction_angles = {'forward': 0, 'left': 90, 'right': -90, 'back': 180}
        for direction, dist in scan_results.items():
            if dist <= 0:
                continue
            angle_offset = direction_angles.get(direction, 0)
            theta = math.radians((heading + angle_offset) % 360)
            # Project obstacle position in grid
            obs_x = int(round(x + (dist / cell_size_cm) * math.cos(theta)))
            obs_y = int(round(y + (dist / cell_size_cm) * math.sin(theta)))
            house_map.update_cell_from_sensor(obs_x, obs_y, 'ultrasonic', dist, confidence=1.0)
    """Integration class for PiDog SLAM system"""
    
    def __init__(self, map_file: str = "pidog_house_map.pkl"):
        self.map_file = map_file
        self.step_distance_cm = 15.0  # Average step distance
        self.turn_angle_degrees = 45.0  # Average turn angle
        # Legacy house_map and map loading removed
    
    # All legacy house_map, landmark, and room logic removed
