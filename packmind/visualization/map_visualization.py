#!/usr/bin/env python3
"""
PiDog Map Visualization System
==============================

Visualization tools for PiDog's house mapping system.
Creates ASCII and exportable representations of the house map
for debugging, monitoring, and manual editing.

Features:
- ASCII map visualization in terminal
- Export to JSON and CSV formats
- Real-time map display
- Path visualization
- Room and landmark highlighting

Author: 7Lynx
"""

import json
import time
from typing import Dict, List, Tuple, Optional

# Support both package and script execution imports
try:
    from packmind.mapping.home_mapping import HomeMap, CellType, Position  # preferred import
except Exception:
    try:
        from mapping.home_mapping import HomeMap, CellType, Position  # relative folder execution
    except Exception:
        try:
            raise ImportError("Home mapping module not found")
        except Exception:
            from home_mapping import HomeMap, CellType, Position


class MapVisualizer:
    """Visualization system for PiDog house maps"""
    
    def __init__(self, house_map: HomeMap):
        self.house_map = house_map
        
        # ASCII characters for different cell types
        self.cell_chars = {
            CellType.UNKNOWN: '.',
            CellType.FREE: ' ',
            CellType.OBSTACLE: '█',
        }
        
        # Colors for terminal display (ANSI escape codes)
        self.cell_colors = {
            CellType.UNKNOWN: '\033[90m',  # Dark gray
            CellType.FREE: '\033[97m',     # White
            CellType.OBSTACLE: '\033[91m', # Red
        }
        
        self.reset_color = '\033[0m'
    
    def print_map(self, show_bounds_only: bool = True, show_colors: bool = True, 
                  show_path: Optional[List[Tuple[int, int]]] = None):
        """
        Print ASCII representation of the map
        
        Args:
            show_bounds_only: Only show the mapped area
            show_colors: Use ANSI colors in terminal
            show_path: Path to highlight on the map
        """
        if show_bounds_only:
            min_x = max(0, self.house_map.map_bounds['min_x'] - 2)
            max_x = min(self.house_map.max_size[0], self.house_map.map_bounds['max_x'] + 3)
            min_y = max(0, self.house_map.map_bounds['min_y'] - 2)
            max_y = min(self.house_map.max_size[1], self.house_map.map_bounds['max_y'] + 3)
        else:
            min_x, min_y = 0, 0
            max_x, max_y = self.house_map.max_size
        
        # Get current position
        current_pos = self.house_map.get_position()
        robot_x, robot_y = int(current_pos.x), int(current_pos.y)
        
        # Convert path to set for quick lookup
        path_set = set(show_path) if show_path else set()
        
        print(f"\n🗺️ PiDog House Map (Session {int(time.time()) % 10000})")
        print(f"Position: ({robot_x}, {robot_y}) @ {current_pos.heading:.0f}° | Confidence: {current_pos.confidence:.2f}")
        print(f"Map bounds: X[{min_x}-{max_x}] Y[{min_y}-{max_y}] | Cell size: {self.house_map.cell_size_cm}cm")
        print("=" * (max_x - min_x + 5))
        
        # Print column numbers (every 5th)
        print("   ", end="")
        for x in range(min_x, max_x):
            if x % 5 == 0:
                print(f"{x%10}", end="")
            else:
                print(" ", end="")
        print()
        
        # Print map rows
        for y in range(min_y, max_y):
            # Row number
            if y % 5 == 0:
                print(f"{y:2d} ", end="")
            else:
                print("   ", end="")
            
            # Print cells in row
            for x in range(min_x, max_x):
                # Check if this is robot position
                if x == robot_x and y == robot_y:
                    char = '🤖'
                    if show_colors:
                        print(f"\033[95m{char}\033[0m", end="")  # Magenta robot
                    else:
                        print(char, end="")
                
                # Check if this is on the path
                elif (x, y) in path_set:
                    char = '→'
                    if show_colors:
                        print(f"\033[96m{char}\033[0m", end="")  # Cyan path
                    else:
                        print(char, end="")
                
                # Regular cell
                else:
                    cell = self.house_map.grid[x, y]
                    char = self.cell_chars.get(cell.cell_type, '?')
                    
                    if show_colors and cell.cell_type in self.cell_colors:
                        color = self.cell_colors[cell.cell_type]
                        print(f"{color}{char}{self.reset_color}", end="")
                    else:
                        print(char, end="")
            
            print()  # New line after each row
        
        # Print legend
        print("\nLegend:")
        legend_items = [
            ("🤖", "Robot Position"),
            ("→", "Navigation Path"),
            ("█", "Obstacles"),
            (" ", "Free Space"),
            (".", "Unknown"),
            ("*", "Anchor/Visual Tag")
        ]
        
        for i, (char, description) in enumerate(legend_items):
            if i % 2 == 0:
                print(f"{char} {description:<18}", end="")
            else:
                print(f"{char} {description}")
        
        if len(legend_items) % 2 == 1:
            print()  # Final newline if odd number of legend items
    
    def print_anchor_summary(self):
        """Print summary of detected visual anchors (AprilTags, QR codes, etc.)"""
        anchors = getattr(self.house_map, 'anchors', {})
        if not anchors:
            print("🔖 No visual anchors detected yet")
            return
        print(f"\n🔖 Detected Anchors ({len(anchors)}):")
        print("-" * 50)
        for anchor_id, pos in anchors.items():
            print(f"Anchor {anchor_id}: ({pos.x:.1f}, {pos.y:.1f}) heading={getattr(pos, 'heading', 0.0):.1f}° confidence={getattr(pos, 'confidence', 1.0):.2f}")
        print()
    
    # Landmarks are now handled as anchors or semantic labels
    
    def export_to_json(self, filename: str) -> bool:
        """
        Export map to JSON format
        
        Args:
            filename: Output filename
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get map summary
            map_summary = self.house_map.get_map_summary()
            
            # Extract occupied cells
            occupied_cells = []
            for x in range(self.house_map.max_size[0]):
                for y in range(self.house_map.max_size[1]):
                    cell = self.house_map.grid[x, y]
                    if cell.cell_type != CellType.UNKNOWN or cell.observations > 0:
                        occupied_cells.append({
                            "x": x,
                            "y": y,
                            "type": cell.cell_type.name,
                            "confidence": cell.confidence,
                            "observations": cell.observations,
                            "last_observed": cell.last_observed
                        })
            
            # Create export data
            export_data = {
                "metadata": {
                    "export_time": time.time(),
                    "cell_size_cm": self.house_map.cell_size_cm,
                    "map_bounds": self.house_map.map_bounds,
                    "total_scans": self.house_map.total_scans
                },
                "summary": map_summary,
                "cells": occupied_cells,
                "anchors": [
                    {"id": anchor_id, "x": pos.x, "y": pos.y, "heading": getattr(pos, 'heading', 0.0), "confidence": getattr(pos, 'confidence', 1.0)}
                    for anchor_id, pos in getattr(self.house_map, 'anchors', {}).items()
                ]
            }
            
            # Write to file
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2)
            
            print(f"✓ Map exported to {filename}")
            return True
            
        except Exception as e:
            print(f"✗ Export failed: {e}")
            return False
    
    def export_to_csv(self, filename: str) -> bool:
        """
        Export map grid to CSV format
        
        Args:
            filename: Output filename
            
        Returns:
            True if successful, False otherwise
        """
        try:
            import csv
            
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                
                # Write header
                writer.writerow(['x', 'y', 'cell_type', 'confidence', 'observations', 'last_observed'])
                
                # Write cell data
                for x in range(self.house_map.max_size[0]):
                    for y in range(self.house_map.max_size[1]):
                        cell = self.house_map.grid[x, y]
                        if cell.cell_type != CellType.UNKNOWN or cell.observations > 0:
                            writer.writerow([
                                x, y, 
                                cell.cell_type.name,
                                cell.confidence,
                                cell.observations,
                                cell.last_observed
                            ])
            
            print(f"✓ Map exported to CSV: {filename}")
            return True
            
        except Exception as e:
            print(f"✗ CSV export failed: {e}")
            return False
    
    def create_map_report(self) -> str:
        """
        Create a comprehensive text report of the map
        
        Returns:
            Formatted text report
        """
        report_lines = []
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Header
        report_lines.append("=" * 60)
        report_lines.append("PiDog House Map Report")
        report_lines.append("=" * 60)
        report_lines.append(f"Generated: {current_time}")
        report_lines.append("")
        
        # Map summary
        summary = self.house_map.get_map_summary()
        report_lines.append("Map Overview:")
        report_lines.append("-" * 20)
        report_lines.append(f"Total scans performed: {summary['total_scans']}")
        report_lines.append(f"Mapped area: {summary['mapped_area_m2']:.1f} square meters")
        report_lines.append(f"Current position: ({summary['position']['x']:.1f}, {summary['position']['y']:.1f})")
        report_lines.append(f"Position confidence: {summary['position']['confidence']:.3f}")
        report_lines.append("")
        
        # Cell type statistics
        report_lines.append("Cell Statistics:")
        report_lines.append("-" * 20)
        for cell_type, count in summary['cell_counts'].items():
            if count > 0:
                report_lines.append(f"{cell_type.replace('_', ' ').title()}: {count} cells")
        report_lines.append("")
        
        # Anchors
        anchors = getattr(self.house_map, 'anchors', {})
        if anchors:
            report_lines.append(f"Detected Anchors ({len(anchors)}):")
            report_lines.append("-" * 20)
            for anchor_id, pos in anchors.items():
                report_lines.append(f"Anchor {anchor_id}: ({pos.x:.1f}, {pos.y:.1f}) heading={getattr(pos, 'heading', 0.0):.1f}° confidence={getattr(pos, 'confidence', 1.0):.2f}")
            report_lines.append("")
        
        return "\n".join(report_lines)
    
    def save_report(self, filename: str) -> bool:
        """
        Save comprehensive map report to file
        
        Args:
            filename: Output filename
            
        Returns:
            True if successful, False otherwise
        """
        try:
            report = self.create_map_report()
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(report)
            
            print(f"✓ Map report saved to {filename}")
            return True
            
        except Exception as e:
            print(f"✗ Report save failed: {e}")
            return False


class LiveMapDisplay:
    """Live updating map display for monitoring"""
    
    def __init__(self, visualizer: MapVisualizer, update_interval: float = 2.0):
        self.visualizer = visualizer
        self.update_interval = update_interval
        self.running = False
    
    def start_live_display(self):
        """Start live map display (blocking)"""
        import os
        
        self.running = True
        
        try:
            while self.running:
                # Clear screen (works on most terminals)
                os.system('cls' if os.name == 'nt' else 'clear')
                
                # Display current map
                self.visualizer.print_map(show_colors=True)
                print("\nPress Ctrl+C to stop live display")
                
                time.sleep(self.update_interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Live display stopped")
            self.running = False
    
    def stop_display(self):
        """Stop the live display"""
        self.running = False


def create_map_visualizer(house_map) -> MapVisualizer:
    """
    Factory function to create a map visualizer
    
    Args:
        house_map: HouseMap instance to visualize
        
    Returns:
        Configured MapVisualizer instance
    """
    return MapVisualizer(house_map)


# Example usage functions
def demo_visualization(house_map):
    """Demo the visualization system"""
    visualizer = MapVisualizer(house_map)
    
    print("🎨 Map Visualization Demo")
    print("=" * 30)
    
    # Show current map
    visualizer.print_map()
    
    # Show summaries
    visualizer.print_anchor_summary()
    
    # Export examples
    timestamp = int(time.time())
    visualizer.export_to_json(f"map_export_{timestamp}.json")
    visualizer.export_to_csv(f"map_export_{timestamp}.csv")
    visualizer.save_report(f"map_report_{timestamp}.txt")


if __name__ == "__main__":
    print("🗺️ PiDog Map Visualization System")
    print("This module provides visualization tools for PiDog house maps.")
    print("Import and use with your HouseMap instance.")
