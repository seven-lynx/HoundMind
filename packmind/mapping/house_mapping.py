#!/usr/bin/env python3
"""
PiDog House Mapping System (SLAM)
=================================

Advanced SLAM system for PiDog that creates and maintains a persistent map
of the house with obstacle tracking, room detection, and localization.

Features:
- Grid-based occupancy mapping
- Dead reckoning with IMU integration
- Persistent map storage/loading
- Room detection and labeling
- Landmark identification
- Calibration systems
- Path planning integration

Author: 7Lynx
"""

import numpy as np
import json
import time
import math
from typing import Any, Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, asdict
from enum import Enum
import threading
import pickle


class CellType(Enum):
    """Map cell types"""
    UNKNOWN = 0      # Unexplored
    FREE = 1         # Open space
    OBSTACLE = 2     # Static obstacle (wall, furniture)
    DYNAMIC = 3      # Dynamic obstacle (person, pet)
    LANDMARK = 4     # Notable landmark (doorway, corner)
    ROOM_CENTER = 5  # Identified room center


@dataclass
class MapCell:
    """Individual map cell with metadata"""
    cell_type: CellType = CellType.UNKNOWN
    confidence: float = 0.0  # 0.0 to 1.0
    last_observed: float = 0.0  # Timestamp
    observations: int = 0  # Number of times observed
    height_estimate: float = 0.0  # Estimated height of obstacle (cm)
    room_id: Optional[int] = None
    landmark_type: Optional[str] = None


@dataclass
class Position:
    """2D position with orientation"""
    x: float  # Grid coordinates
    y: float  # Grid coordinates
    heading: float  # Degrees (0 = North/Forward)
    confidence: float = 1.0
    timestamp: float = 0.0


@dataclass
class Landmark:
    """Identified landmark in the map"""
    position: Position
    landmark_type: str  # "corner", "doorway", "wall_end", "furniture_corner"
    size_estimate: Tuple[float, float]  # Width, height in cm
    description: str
    confidence: float


@dataclass
class Room:
    """Detected room area"""
    room_id: int
    center: Position
    bounds: Tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    estimated_size: float  # Square meters
    room_type: str  # "living_room", "kitchen", "bedroom", etc.
    doorways: List[Position]
    confidence: float


class HouseMap:
    """Main house mapping system"""
    
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
        
        # Landmarks and rooms
        self.landmarks: Dict[int, Landmark] = {}
        self.rooms: Dict[int, Room] = {}
        self.next_landmark_id = 1
        self.next_room_id = 1
        
        # Position tracking
        self.position_history: List[Position] = []
        self.odometry_error = 0.0  # Accumulated error estimate
        
        # Mapping parameters
        self.confidence_threshold = 0.7
        self.max_obstacle_age = 300.0  # 5 minutes for dynamic obstacles
        
        # Threading for background processing
        self.map_lock = threading.RLock()
        self.processing_thread = None
        self.running = False
    
    def start_mapping(self):
        """Start background map processing"""
        self.running = True
        self.processing_thread = threading.Thread(target=self._background_processing, daemon=True)
        self.processing_thread.start()
        print("🗺️ House mapping system started")
    
    def stop_mapping(self):
        """Stop background processing"""
        self.running = False
        if self.processing_thread:
            self.processing_thread.join(timeout=2.0)
        print("🗺️ House mapping system stopped")
    
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
            
            # Update map bounds
            self._update_map_bounds(new_x, new_y)
            
            # Accumulate odometry error
            movement_distance = math.sqrt(grid_dx**2 + grid_dy**2)
            self.odometry_error += movement_distance * 0.02  # 2% error per movement
    
    def add_obstacle_scan(self, distance: float, angle_degrees: float, 
                         obstacle_type: CellType = CellType.OBSTACLE):
        """
        Add obstacle observation from ultrasonic scan
        
        Args:
            distance: Distance to obstacle (cm)
            angle_degrees: Angle relative to robot heading (degrees)
            obstacle_type: Type of obstacle detected
        """
        with self.map_lock:
            if distance <= 0 or distance > 300:  # Invalid or too far
                return
            
            # Convert to grid coordinates
            angle_rad = math.radians(self.current_position.heading + angle_degrees)
            
            # Calculate obstacle position
            grid_distance = distance / self.cell_size_cm
            obs_x = self.current_position.x + grid_distance * math.cos(angle_rad)
            obs_y = self.current_position.y + grid_distance * math.sin(angle_rad)
            
            # Bounds checking
            if not (0 <= obs_x < self.max_size[0] and 0 <= obs_y < self.max_size[1]):
                return
            
            obs_x_int = int(round(obs_x))
            obs_y_int = int(round(obs_y))
            
            # Mark cells along the path as FREE (ray tracing)
            self._mark_free_path(
                self.current_position.x, self.current_position.y,
                obs_x, obs_y
            )
            
            # Mark obstacle cell
            cell = self.grid[obs_x_int, obs_y_int]
            cell.cell_type = obstacle_type
            cell.observations += 1
            cell.last_observed = time.time()
            cell.confidence = min(1.0, cell.confidence + 0.2)
            
            if obstacle_type == CellType.OBSTACLE:
                cell.height_estimate = max(cell.height_estimate, 20.0)  # Assume minimum height
            
            self.total_scans += 1
            self.last_update = time.time()
            
            # Check for landmark patterns
            self._detect_landmarks_around(obs_x_int, obs_y_int)
    
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
            # Don't mark the end point (that's the obstacle)
            if x == x1 and y == y1:
                break
                
            # Mark as free if within bounds
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
    
    def _detect_landmarks_around(self, x: int, y: int):
        """Detect potential landmarks around a given position"""
        # Look for corner patterns, wall endpoints, etc.
        corner_pattern = self._detect_corner_pattern(x, y)
        if corner_pattern:
            self._add_landmark(x, y, "corner", corner_pattern)
        
        wall_end = self._detect_wall_end(x, y)
        if wall_end:
            self._add_landmark(x, y, "wall_end", wall_end)
    
    def _detect_corner_pattern(self, x: int, y: int) -> Optional[str]:
        """Detect if position forms a corner pattern"""
        # Check 3x3 area around point for L-shaped obstacle patterns
        obstacle_positions = []
        
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                nx, ny = x + dx, y + dy
                if (0 <= nx < self.max_size[0] and 0 <= ny < self.max_size[1]):
                    cell = self.grid[nx, ny]
                    if (cell.cell_type == CellType.OBSTACLE and 
                        cell.confidence > self.confidence_threshold):
                        obstacle_positions.append((dx, dy))
        
        # Check for corner patterns (L-shapes)
        corner_patterns = [
            [(-1, 0), (0, 0), (0, -1)],  # Top-left corner
            [(1, 0), (0, 0), (0, -1)],   # Top-right corner
            [(-1, 0), (0, 0), (0, 1)],   # Bottom-left corner
            [(1, 0), (0, 0), (0, 1)]     # Bottom-right corner
        ]
        
        for i, pattern in enumerate(corner_patterns):
            if all(pos in obstacle_positions for pos in pattern):
                return f"corner_{['tl', 'tr', 'bl', 'br'][i]}"
        
        return None
    
    def _detect_wall_end(self, x: int, y: int) -> Optional[str]:
        """Detect if position is a wall endpoint"""
        # Check if there's a line of obstacles ending at this point
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]  # N, S, E, W
        
        for dx, dy in directions:
            wall_length = 0
            # Check how far the wall extends
            for i in range(1, 6):  # Check up to 5 cells
                nx, ny = x + dx * i, y + dy * i
                if (0 <= nx < self.max_size[0] and 0 <= ny < self.max_size[1]):
                    cell = self.grid[nx, ny]
                    if (cell.cell_type == CellType.OBSTACLE and 
                        cell.confidence > self.confidence_threshold):
                        wall_length += 1
                    else:
                        break
            
            # Check if there's free space on the other side
            if wall_length >= 3:  # At least 3 cells of wall
                opposite_x, opposite_y = x - dx, y - dy
                if (0 <= opposite_x < self.max_size[0] and 0 <= opposite_y < self.max_size[1]):
                    opposite_cell = self.grid[opposite_x, opposite_y]
                    if opposite_cell.cell_type == CellType.FREE:
                        return f"wall_end_{['n', 's', 'e', 'w'][directions.index((dx, dy))]}"
        
        return None
    
    def _add_landmark(self, x: int, y: int, landmark_type: str, description: str):
        """Add a landmark to the map"""
        # Check if landmark already exists nearby
        for landmark in self.landmarks.values():
            distance = math.sqrt((landmark.position.x - x)**2 + (landmark.position.y - y)**2)
            if distance < 3.0 and landmark.landmark_type == landmark_type:
                return  # Too close to existing landmark
        
        # Create new landmark
        landmark = Landmark(
            position=Position(x=x, y=y, heading=0.0, timestamp=time.time()),
            landmark_type=landmark_type,
            size_estimate=(self.cell_size_cm, self.cell_size_cm),
            description=description,
            confidence=0.8
        )
        
        self.landmarks[self.next_landmark_id] = landmark
        
        # Mark cell as landmark
        if 0 <= x < self.max_size[0] and 0 <= y < self.max_size[1]:
            self.grid[x, y].cell_type = CellType.LANDMARK
            self.grid[x, y].landmark_type = landmark_type
        
        print(f"🎯 New landmark detected: {landmark_type} at ({x}, {y})")
        self.next_landmark_id += 1
    
    def _update_map_bounds(self, x: float, y: float):
        """Update the known bounds of the mapped area"""
        self.map_bounds['min_x'] = min(self.map_bounds['min_x'], int(x))
        self.map_bounds['max_x'] = max(self.map_bounds['max_x'], int(x))
        self.map_bounds['min_y'] = min(self.map_bounds['min_y'], int(y))
        self.map_bounds['max_y'] = max(self.map_bounds['max_y'], int(y))
    
    def _background_processing(self):
        """Background processing for map optimization and room detection"""
        while self.running:
            try:
                # Room detection every 30 seconds
                if int(time.time()) % 30 == 0:
                    self._detect_rooms()
                
                # Cleanup old dynamic obstacles every 60 seconds
                if int(time.time()) % 60 == 0:
                    self._cleanup_dynamic_obstacles()
                
                time.sleep(1.0)
                
            except Exception as e:
                print(f"⚠️ Map processing error: {e}")
                time.sleep(5.0)
    
    def _detect_rooms(self):
        """Detect room boundaries and centers using flood fill"""
        with self.map_lock:
            # Find connected free space regions
            visited = np.zeros(self.max_size, dtype=bool)
            room_regions = []
            
            for x in range(self.map_bounds['min_x'], self.map_bounds['max_x'] + 1):
                for y in range(self.map_bounds['min_y'], self.map_bounds['max_y'] + 1):
                    if not visited[x, y] and self.grid[x, y].cell_type == CellType.FREE:
                        region = self._flood_fill_room(x, y, visited)
                        if len(region) > 50:  # Minimum room size (50 cells)
                            room_regions.append(region)
            
            # Process detected regions into rooms
            for i, region in enumerate(room_regions):
                if i not in self.rooms:  # New room
                    center_x = sum(pos[0] for pos in region) / len(region)
                    center_y = sum(pos[1] for pos in region) / len(region)
                    
                    min_x = min(pos[0] for pos in region)
                    max_x = max(pos[0] for pos in region)
                    min_y = min(pos[1] for pos in region)
                    max_y = max(pos[1] for pos in region)
                    
                    # Estimate room size in square meters
                    width_m = (max_x - min_x) * self.cell_size_cm / 100
                    height_m = (max_y - min_y) * self.cell_size_cm / 100
                    area_m2 = width_m * height_m
                    
                    room = Room(
                        room_id=self.next_room_id,
                        center=Position(x=center_x, y=center_y, heading=0.0),
                        bounds=(min_x, min_y, max_x, max_y),
                        estimated_size=area_m2,
                        room_type=self._classify_room_type(area_m2, region),
                        doorways=[],
                        confidence=0.7
                    )
                    
                    self.rooms[self.next_room_id] = room
                    print(f"🏠 New room detected: {room.room_type} ({area_m2:.1f}m²)")
                    self.next_room_id += 1
    
    def _flood_fill_room(self, start_x: int, start_y: int, visited: np.ndarray) -> List[Tuple[int, int]]:
        """Flood fill to find connected free space"""
        stack = [(start_x, start_y)]
        region = []
        
        while stack:
            x, y = stack.pop()
            
            if (x < 0 or x >= self.max_size[0] or 
                y < 0 or y >= self.max_size[1] or
                visited[x, y]):
                continue
            
            cell = self.grid[x, y]
            if cell.cell_type != CellType.FREE:
                continue
            
            visited[x, y] = True
            region.append((x, y))
            
            # Add neighbors
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                stack.append((x + dx, y + dy))
        
        return region
    
    def _classify_room_type(self, area_m2: float, region: List[Tuple[int, int]]) -> str:
        """Classify room type based on size and shape"""
        if area_m2 < 5:
            return "closet"
        elif area_m2 < 10:
            return "bathroom"
        elif area_m2 < 15:
            return "bedroom"
        elif area_m2 < 25:
            return "kitchen"
        else:
            return "living_room"
    
    def _cleanup_dynamic_obstacles(self):
        """Remove old dynamic obstacles that may have moved"""
        current_time = time.time()
        with self.map_lock:
            for x in range(self.max_size[0]):
                for y in range(self.max_size[1]):
                    cell = self.grid[x, y]
                    if (cell.cell_type == CellType.DYNAMIC and
                        current_time - cell.last_observed > self.max_obstacle_age):
                        cell.cell_type = CellType.UNKNOWN
                        cell.confidence = 0.0
    
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
                "landmarks": len(self.landmarks),
                "rooms": len(self.rooms),
                "odometry_error": self.odometry_error,
                "last_update": self.last_update
            }
    
    def save_map(self, filename: str):
        """Save map to file"""
        map_data = {
            "metadata": {
                "cell_size_cm": self.cell_size_cm,
                "max_size": self.max_size,
                "creation_time": self.creation_time,
                "last_update": self.last_update,
                "total_scans": self.total_scans,
                "map_bounds": self.map_bounds
            },
            "position": asdict(self.current_position),
            "landmarks": {k: asdict(v) for k, v in self.landmarks.items()},
            "rooms": {k: asdict(v) for k, v in self.rooms.items()},
            "grid_data": self._serialize_grid()
        }
        
        with open(filename, 'wb') as f:
            pickle.dump(map_data, f)
        
        print(f"🗺️ Map saved to {filename}")
    
    def load_map(self, filename: str) -> bool:
        """Load map from file"""
        try:
            with open(filename, 'rb') as f:
                map_data = pickle.load(f)
            
            # Restore metadata
            metadata = map_data["metadata"]
            self.cell_size_cm = metadata["cell_size_cm"]
            self.max_size = tuple(metadata["max_size"])
            self.creation_time = metadata["creation_time"]
            self.last_update = metadata["last_update"]
            self.total_scans = metadata["total_scans"]
            self.map_bounds = metadata["map_bounds"]
            
            # Restore position
            pos_data = map_data["position"]
            self.current_position = Position(**pos_data)
            
            # Restore landmarks
            self.landmarks = {}
            for k, v in map_data["landmarks"].items():
                landmark = Landmark(
                    position=Position(**v["position"]),
                    landmark_type=v["landmark_type"],
                    size_estimate=tuple(v["size_estimate"]),
                    description=v["description"],
                    confidence=v["confidence"]
                )
                self.landmarks[int(k)] = landmark
            
            # Restore rooms
            self.rooms = {}
            for k, v in map_data["rooms"].items():
                room = Room(
                    room_id=v["room_id"],
                    center=Position(**v["center"]),
                    bounds=tuple(v["bounds"]),
                    estimated_size=v["estimated_size"],
                    room_type=v["room_type"],
                    doorways=[Position(**pos) for pos in v["doorways"]],
                    confidence=v["confidence"]
                )
                self.rooms[int(k)] = room
            
            # Restore grid
            self._deserialize_grid(map_data["grid_data"])
            
            print(f"✓ Map loaded from {filename}")
            return True
            
        except Exception as e:
            print(f"✗ Failed to load map: {e}")
            return False
    
    def _serialize_grid(self) -> List:
        """Serialize grid for saving"""
        grid_data = []
        for x in range(self.max_size[0]):
            for y in range(self.max_size[1]):
                cell = self.grid[x, y]
                if cell.cell_type != CellType.UNKNOWN or cell.observations > 0:
                    grid_data.append({
                        "x": x, "y": y,
                        "cell_type": cell.cell_type.value,
                        "confidence": cell.confidence,
                        "last_observed": cell.last_observed,
                        "observations": cell.observations,
                        "height_estimate": cell.height_estimate,
                        "room_id": cell.room_id,
                        "landmark_type": cell.landmark_type
                    })
        return grid_data
    
    def _deserialize_grid(self, grid_data: List):
        """Deserialize grid from loaded data"""
        # Initialize empty grid
        self.grid = np.full(self.max_size, MapCell(), dtype=object)
        for i in range(self.max_size[0]):
            for j in range(self.max_size[1]):
                self.grid[i, j] = MapCell()
        
        # Load saved cells
        for cell_data in grid_data:
            x, y = cell_data["x"], cell_data["y"]
            if 0 <= x < self.max_size[0] and 0 <= y < self.max_size[1]:
                cell = self.grid[x, y]
                cell.cell_type = CellType(cell_data["cell_type"])
                cell.confidence = cell_data["confidence"]
                cell.last_observed = cell_data["last_observed"]
                cell.observations = cell_data["observations"]
                cell.height_estimate = cell_data["height_estimate"]
                cell.room_id = cell_data["room_id"]
                cell.landmark_type = cell_data["landmark_type"]


class PiDogSLAM:
    """Integration class for PiDog SLAM system"""
    
    def __init__(self, map_file: str = "pidog_house_map.pkl"):
        self.house_map = HouseMap()
        self.map_file = map_file
        self.step_distance_cm = 15.0  # Average step distance
        self.turn_angle_degrees = 45.0  # Average turn angle
        
        # Load existing map if available
        self.house_map.load_map(map_file)
    
    def start(self):
        """Start SLAM system"""
        self.house_map.start_mapping()
    
    def stop(self):
        """Stop SLAM system and save map"""
        self.house_map.stop_mapping()
        self.house_map.save_map(self.map_file)
    
    def update_from_movement(self, action: str, step_count: int = 1):
        """Update position based on PiDog movement action"""
        if action == "forward":
            self.house_map.update_position(
                delta_x=self.step_distance_cm * step_count,
                delta_y=0.0,
                delta_heading=0.0,
                confidence=0.9
            )
        elif action == "backward":
            self.house_map.update_position(
                delta_x=-self.step_distance_cm * step_count,
                delta_y=0.0,
                delta_heading=0.0,
                confidence=0.9
            )
        elif action == "turn_left":
            self.house_map.update_position(
                delta_x=0.0,
                delta_y=0.0,
                delta_heading=self.turn_angle_degrees * step_count,
                confidence=0.95
            )
        elif action == "turn_right":
            self.house_map.update_position(
                delta_x=0.0,
                delta_y=0.0,
                delta_heading=-self.turn_angle_degrees * step_count,
                confidence=0.95
            )
    
    def update_from_scan(self, scan_data: Dict[str, float]):
        """Update map from ultrasonic scan data"""
        current_time = time.time()
        
        # Process each scan direction
        angle_mapping = {
            'forward': 0.0,
            'left': 45.0,
            'right': -45.0
        }
        
        for direction, distance in scan_data.items():
            if direction in angle_mapping and distance > 0:
                self.house_map.add_obstacle_scan(
                    distance=distance,
                    angle_degrees=angle_mapping[direction],
                    obstacle_type=CellType.OBSTACLE
                )
    
    def get_navigation_info(self) -> Dict:
        """Get information for navigation decisions"""
        summary = self.house_map.get_map_summary()
        position = self.house_map.get_position()
        
        return {
            "current_position": position,
            "map_summary": summary,
            "nearby_landmarks": self._get_nearby_landmarks(),
            "room_info": self._get_current_room_info(),
            "suggested_direction": self._suggest_exploration_direction()
        }
    
    def _get_nearby_landmarks(self, radius: float = 50.0) -> List[Dict]:
        """Get landmarks near current position"""
        current_pos = self.house_map.current_position
        nearby = []
        
        for landmark_id, landmark in self.house_map.landmarks.items():
            distance = math.sqrt(
                (landmark.position.x - current_pos.x) ** 2 +
                (landmark.position.y - current_pos.y) ** 2
            )
            
            if distance <= radius:
                nearby.append({
                    "id": landmark_id,
                    "type": landmark.landmark_type,
                    "distance": distance * self.house_map.cell_size_cm,
                    "description": landmark.description,
                    "confidence": landmark.confidence
                })
        
        return sorted(nearby, key=lambda x: x["distance"])
    
    def _get_current_room_info(self) -> Optional[Dict]:
        """Get information about current room"""
        current_pos = self.house_map.current_position
        
        for room_id, room in self.house_map.rooms.items():
            min_x, min_y, max_x, max_y = room.bounds
            if (min_x <= current_pos.x <= max_x and 
                min_y <= current_pos.y <= max_y):
                return {
                    "room_id": room_id,
                    "room_type": room.room_type,
                    "size_m2": room.estimated_size,
                    "center_distance": math.sqrt(
                        (room.center.x - current_pos.x) ** 2 +
                        (room.center.y - current_pos.y) ** 2
                    ) * self.house_map.cell_size_cm
                }
        
        return None
    
    def _suggest_exploration_direction(self) -> Dict[str, Any]:
        """Suggest best direction for exploration"""
        current_pos = self.house_map.current_position

        # Check areas around current position for unexplored regions
        directions = {
            "forward": (0, 1),
            "left": (1, 0),
            "right": (-1, 0),
            "backward": (0, -1),
        }

        exploration_scores: Dict[str, int] = {}

        for direction, (dx, dy) in directions.items():
            score = 0

            # Look ahead in this direction
            for distance in range(1, 20):  # Check 20 cells ahead
                x = int(current_pos.x + dx * distance)
                y = int(current_pos.y + dy * distance)

                if (0 <= x < self.house_map.max_size[0] and 0 <= y < self.house_map.max_size[1]):
                    cell = self.house_map.grid[x, y]

                    if cell.cell_type == CellType.UNKNOWN:
                        # Higher score for unknown cells, weighted by distance
                        score += 10  # Bonus for unexplored areas
                    elif cell.cell_type == CellType.FREE:
                        # Small bonus for free cells (accessible)
                        score += 5  # Good for free movement
                    elif cell.cell_type == CellType.OBSTACLE:
                        score -= 20  # Penalty for obstacles
                        break
                else:
                    break

            exploration_scores[direction] = score

        # Pick the direction with the highest score (tie-breaker is dict order)
        best_kv = max(exploration_scores.items(), key=lambda kv: kv[1])
        best_direction = best_kv[0]
        best_score = best_kv[1]

        return {
            "suggested_direction": best_direction,
            "confidence": min(1.0, best_score / 100.0),
            "all_scores": exploration_scores,
            "reason": "unexplored_area" if best_score > 50 else "open_space",
        }
