#!/usr/bin/env python3
"""
PiDog Pathfinding System
========================

A* pathfinding algorithm and navigation utilities for PiDog's house mapping system.
Provides intelligent navigation from current position to target locations while
avoiding obstacles and using the SLAM-generated house map.

Features:
- A* pathfinding algorithm
- Dynamic obstacle avoidance
- Room-to-room navigation
- Landmark-based waypoint navigation
- Path optimization and smoothing

"""

import heapq
import math
from typing import List, Tuple, Optional, Dict, Set
from dataclasses import dataclass
from house_mapping import HouseMap, CellType, Position


@dataclass
class PathNode:
    """Node in the pathfinding graph"""
    x: int
    y: int
    g_cost: float = 0.0  # Cost from start
    h_cost: float = 0.0  # Heuristic cost to goal
    f_cost: float = 0.0  # Total cost
    parent: Optional['PathNode'] = None
    
    def __lt__(self, other):
        return self.f_cost < other.f_cost


class PiDogPathfinder:
    """A* pathfinding system for PiDog navigation"""
    
    def __init__(self, house_map: HouseMap):
        self.house_map = house_map
        self.current_path: List[Tuple[int, int]] = []
        self.path_index = 0
        
        # Pathfinding parameters
        self.diagonal_cost = 1.414  # sqrt(2)
        self.straight_cost = 1.0
        self.obstacle_buffer = 2  # Cells to buffer around obstacles
        
        # Movement costs for different cell types
        self.movement_costs = {
            CellType.FREE: 1.0,
            CellType.UNKNOWN: 2.0,  # Higher cost for unexplored areas
            CellType.OBSTACLE: float('inf'),  # Impassable
            CellType.DYNAMIC: 5.0,  # Higher cost, but passable (might move)
            CellType.LANDMARK: 1.5,  # Slightly higher cost
            CellType.ROOM_CENTER: 0.8  # Lower cost - prefer room centers
        }
    
    def find_path(self, start_pos: Tuple[int, int], goal_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """
        Find optimal path from start to goal using A* algorithm
        
        Args:
            start_pos: Starting position (x, y)
            goal_pos: Goal position (x, y)
            
        Returns:
            List of waypoints from start to goal, empty if no path found
        """
        start_x, start_y = start_pos
        goal_x, goal_y = goal_pos
        
        # Validate positions
        if not self._is_valid_position(start_x, start_y) or not self._is_valid_position(goal_x, goal_y):
            return []
        
        # Initialize A* algorithm
        open_set = []
        closed_set: Set[Tuple[int, int]] = set()
        
        start_node = PathNode(start_x, start_y)
        start_node.h_cost = self._heuristic(start_x, start_y, goal_x, goal_y)
        start_node.f_cost = start_node.h_cost
        
        heapq.heappush(open_set, start_node)
        open_dict = {(start_x, start_y): start_node}
        
        while open_set:
            current_node = heapq.heappop(open_set)
            current_pos = (current_node.x, current_node.y)
            
            # Remove from open dict
            if current_pos in open_dict:
                del open_dict[current_pos]
            
            # Add to closed set
            closed_set.add(current_pos)
            
            # Check if we reached the goal
            if current_node.x == goal_x and current_node.y == goal_y:
                return self._reconstruct_path(current_node)
            
            # Explore neighbors
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    if dx == 0 and dy == 0:
                        continue
                    
                    neighbor_x = current_node.x + dx
                    neighbor_y = current_node.y + dy
                    neighbor_pos = (neighbor_x, neighbor_y)
                    
                    # Skip if invalid or in closed set
                    if not self._is_valid_position(neighbor_x, neighbor_y) or neighbor_pos in closed_set:
                        continue
                    
                    # Calculate movement cost
                    move_cost = self.diagonal_cost if (dx != 0 and dy != 0) else self.straight_cost
                    cell_cost = self._get_cell_cost(neighbor_x, neighbor_y)
                    
                    if cell_cost == float('inf'):
                        continue  # Impassable
                    
                    tentative_g = current_node.g_cost + move_cost * cell_cost
                    
                    # Check if this is a better path to the neighbor
                    if neighbor_pos in open_dict:
                        neighbor_node = open_dict[neighbor_pos]
                        if tentative_g < neighbor_node.g_cost:
                            # Better path found
                            neighbor_node.g_cost = tentative_g
                            neighbor_node.parent = current_node
                            neighbor_node.f_cost = neighbor_node.g_cost + neighbor_node.h_cost
                    else:
                        # New node
                        neighbor_node = PathNode(neighbor_x, neighbor_y)
                        neighbor_node.g_cost = tentative_g
                        neighbor_node.h_cost = self._heuristic(neighbor_x, neighbor_y, goal_x, goal_y)
                        neighbor_node.f_cost = neighbor_node.g_cost + neighbor_node.h_cost
                        neighbor_node.parent = current_node
                        
                        heapq.heappush(open_set, neighbor_node)
                        open_dict[neighbor_pos] = neighbor_node
        
        return []  # No path found
    
    def navigate_to_room(self, target_room_id: int) -> List[Tuple[int, int]]:
        """
        Navigate to a specific room
        
        Args:
            target_room_id: ID of the target room
            
        Returns:
            Path to the room center, empty if room not found
        """
        if target_room_id not in self.house_map.rooms:
            return []
        
        target_room = self.house_map.rooms[target_room_id]
        current_pos = self.house_map.get_position()
        
        start_pos = (int(current_pos.x), int(current_pos.y))
        goal_pos = (int(target_room.center.x), int(target_room.center.y))
        
        return self.find_path(start_pos, goal_pos)
    
    def navigate_to_landmark(self, landmark_id: int) -> List[Tuple[int, int]]:
        """
        Navigate to a specific landmark
        
        Args:
            landmark_id: ID of the target landmark
            
        Returns:
            Path to the landmark, empty if landmark not found
        """
        if landmark_id not in self.house_map.landmarks:
            return []
        
        target_landmark = self.house_map.landmarks[landmark_id]
        current_pos = self.house_map.get_position()
        
        start_pos = (int(current_pos.x), int(current_pos.y))
        goal_pos = (int(target_landmark.position.x), int(target_landmark.position.y))
        
        return self.find_path(start_pos, goal_pos)
    
    def find_exploration_target(self, exploration_radius: int = 50) -> Optional[Tuple[int, int]]:
        """
        Find the best unexplored area to navigate to
        
        Args:
            exploration_radius: Radius to search for unexplored areas
            
        Returns:
            Position of best exploration target, None if no good targets
        """
        current_pos = self.house_map.get_position()
        start_x, start_y = int(current_pos.x), int(current_pos.y)
        
        best_target = None
        best_score = 0.0
        
        # Search in a spiral pattern around current position
        for radius in range(10, exploration_radius, 5):
            for angle in range(0, 360, 30):  # Check every 30 degrees
                target_x = start_x + int(radius * math.cos(math.radians(angle)))
                target_y = start_y + int(radius * math.sin(math.radians(angle)))
                
                if not self._is_valid_position(target_x, target_y):
                    continue
                
                # Score this position based on unknown cells nearby
                score = self._calculate_exploration_score(target_x, target_y)
                
                if score > best_score:
                    # Check if we can actually reach this position
                    path = self.find_path((start_x, start_y), (target_x, target_y))
                    if path:
                        best_score = score
                        best_target = (target_x, target_y)
        
        return best_target
    
    def get_next_waypoint(self) -> Optional[Tuple[int, int]]:
        """
        Get the next waypoint in the current path
        
        Returns:
            Next waypoint position, None if no active path
        """
        if not self.current_path or self.path_index >= len(self.current_path):
            return None
        
        return self.current_path[self.path_index]
    
    def advance_path(self):
        """Advance to the next waypoint in the current path"""
        if self.current_path and self.path_index < len(self.current_path) - 1:
            self.path_index += 1
    
    def set_current_path(self, path: List[Tuple[int, int]]):
        """Set a new path as the current navigation target"""
        self.current_path = path
        self.path_index = 0
    
    def clear_path(self):
        """Clear the current navigation path"""
        self.current_path = []
        self.path_index = 0
    
    def is_path_complete(self) -> bool:
        """Check if we've reached the end of the current path"""
        return not self.current_path or self.path_index >= len(self.current_path) - 1
    
    def _is_valid_position(self, x: int, y: int) -> bool:
        """Check if position is within map bounds"""
        return (0 <= x < self.house_map.max_size[0] and 
                0 <= y < self.house_map.max_size[1])
    
    def _get_cell_cost(self, x: int, y: int) -> float:
        """Get the movement cost for a specific cell"""
        if not self._is_valid_position(x, y):
            return float('inf')
        
        cell = self.house_map.grid[x, y]
        base_cost = self.movement_costs.get(cell.cell_type, 10.0)
        
        # Add buffer cost around obstacles
        if base_cost < float('inf'):
            obstacle_nearby = self._check_obstacle_buffer(x, y)
            if obstacle_nearby:
                base_cost *= 2.0  # Double cost near obstacles
        
        # Reduce cost based on confidence (prefer well-mapped areas)
        confidence_bonus = cell.confidence * 0.5
        return max(0.1, base_cost - confidence_bonus)
    
    def _check_obstacle_buffer(self, x: int, y: int) -> bool:
        """Check if position is within buffer distance of obstacles"""
        for dx in range(-self.obstacle_buffer, self.obstacle_buffer + 1):
            for dy in range(-self.obstacle_buffer, self.obstacle_buffer + 1):
                check_x, check_y = x + dx, y + dy
                
                if (self._is_valid_position(check_x, check_y) and
                    self.house_map.grid[check_x, check_y].cell_type == CellType.OBSTACLE):
                    return True
        
        return False
    
    def _heuristic(self, x1: int, y1: int, x2: int, y2: int) -> float:
        """Calculate heuristic distance (Euclidean distance)"""
        return math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    
    def _reconstruct_path(self, goal_node: PathNode) -> List[Tuple[int, int]]:
        """Reconstruct path from goal node back to start"""
        path = []
        current = goal_node
        
        while current is not None:
            path.append((current.x, current.y))
            current = current.parent
        
        path.reverse()
        return self._smooth_path(path)
    
    def _smooth_path(self, path: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """Smooth path by removing unnecessary waypoints"""
        if len(path) <= 2:
            return path
        
        smoothed = [path[0]]  # Always keep start point
        
        i = 0
        while i < len(path) - 1:
            # Try to find the farthest point we can reach directly
            farthest = i + 1
            
            for j in range(i + 2, len(path)):
                if self._has_clear_line_of_sight(path[i], path[j]):
                    farthest = j
                else:
                    break
            
            smoothed.append(path[farthest])
            i = farthest
        
        return smoothed
    
    def _has_clear_line_of_sight(self, start: Tuple[int, int], end: Tuple[int, int]) -> bool:
        """Check if there's a clear line of sight between two points"""
        x0, y0 = start
        x1, y1 = end
        
        # Bresenham's line algorithm to check each cell along the line
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        
        x, y = x0, y0
        
        while True:
            # Check if current cell is passable
            if (self._is_valid_position(x, y) and
                self._get_cell_cost(x, y) == float('inf')):
                return False
            
            if x == x1 and y == y1:
                break
            
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
        
        return True
    
    def _calculate_exploration_score(self, x: int, y: int) -> float:
        """Calculate exploration score for a position (higher = better for exploration)"""
        if not self._is_valid_position(x, y):
            return 0.0
        
        score = 0.0
        search_radius = 10
        
        # Count unknown cells in the area
        for dx in range(-search_radius, search_radius + 1):
            for dy in range(-search_radius, search_radius + 1):
                check_x, check_y = x + dx, y + dy
                
                if self._is_valid_position(check_x, check_y):
                    cell = self.house_map.grid[check_x, check_y]
                    distance = math.sqrt(dx**2 + dy**2)
                    
                    if cell.cell_type == CellType.UNKNOWN:
                        # Higher score for unknown cells, weighted by distance
                        score += 10.0 / (1.0 + distance * 0.2)
                    elif cell.cell_type == CellType.FREE:
                        # Small bonus for free cells (accessible)
                        score += 1.0 / (1.0 + distance * 0.5)
        
        return score


class NavigationController:
    """High-level navigation controller for PiDog"""
    
    def __init__(self, pathfinder: PiDogPathfinder):
        self.pathfinder = pathfinder
        self.current_target = None
        self.navigation_mode = "manual"  # "manual", "auto_explore", "goto_room", "goto_landmark"
        
    def start_exploration_mode(self):
        """Start automatic exploration mode"""
        self.navigation_mode = "auto_explore"
        target = self.pathfinder.find_exploration_target()
        
        if target:
            current_pos = self.pathfinder.house_map.get_position()
            start_pos = (int(current_pos.x), int(current_pos.y))
            path = self.pathfinder.find_path(start_pos, target)
            
            if path:
                self.pathfinder.set_current_path(path)
                self.current_target = target
                print(f"🔍 Exploration target set: {target}")
                return True
        
        print("❌ No suitable exploration target found")
        return False
    
    def navigate_to_room(self, room_id: int) -> bool:
        """Navigate to a specific room"""
        path = self.pathfinder.navigate_to_room(room_id)
        
        if path:
            self.pathfinder.set_current_path(path)
            self.navigation_mode = "goto_room"
            self.current_target = room_id
            print(f"🏠 Navigation to room {room_id} started")
            return True
        else:
            print(f"❌ Cannot find path to room {room_id}")
            return False
    
    def navigate_to_landmark(self, landmark_id: int) -> bool:
        """Navigate to a specific landmark"""
        path = self.pathfinder.navigate_to_landmark(landmark_id)
        
        if path:
            self.pathfinder.set_current_path(path)
            self.navigation_mode = "goto_landmark"
            self.current_target = landmark_id
            print(f"🎯 Navigation to landmark {landmark_id} started")
            return True
        else:
            print(f"❌ Cannot find path to landmark {landmark_id}")
            return False
    
    def get_next_movement_command(self) -> Optional[Dict]:
        """
        Get the next movement command based on current navigation state
        
        Returns:
            Dictionary with movement command, None if no movement needed
        """
        if self.navigation_mode == "manual":
            return None
        
        waypoint = self.pathfinder.get_next_waypoint()
        if not waypoint:
            # Path completed or no path
            if self.navigation_mode == "auto_explore":
                # Find new exploration target
                if self.start_exploration_mode():
                    return self.get_next_movement_command()
            return None
        
        # Calculate direction to waypoint
        current_pos = self.pathfinder.house_map.get_position()
        current_x, current_y = int(current_pos.x), int(current_pos.y)
        target_x, target_y = waypoint
        
        dx = target_x - current_x
        dy = target_y - current_y
        
        # Check if we're close enough to the waypoint
        distance = math.sqrt(dx**2 + dy**2)
        if distance < 1.5:  # Close enough, advance to next waypoint
            self.pathfinder.advance_path()
            return self.get_next_movement_command()
        
        # Determine movement direction
        angle_to_target = math.degrees(math.atan2(dy, dx))
        current_heading = current_pos.heading
        
        # Calculate turn needed
        angle_diff = (angle_to_target - current_heading + 180) % 360 - 180
        
        if abs(angle_diff) > 30:  # Need to turn
            if angle_diff > 0:
                return {"action": "turn_left", "step_count": 1}
            else:
                return {"action": "turn_right", "step_count": 1}
        else:
            # Move forward
            steps = min(3, int(distance))  # Move 1-3 steps
            return {"action": "forward", "step_count": steps}
    
    def stop_navigation(self):
        """Stop current navigation"""
        self.pathfinder.clear_path()
        self.navigation_mode = "manual"
        self.current_target = None
        print("🛑 Navigation stopped")
    
    def get_navigation_status(self) -> Dict:
        """Get current navigation status"""
        return {
            "mode": self.navigation_mode,
            "target": self.current_target,
            "path_length": len(self.pathfinder.current_path),
            "path_progress": self.pathfinder.path_index,
            "path_complete": self.pathfinder.is_path_complete()
        }