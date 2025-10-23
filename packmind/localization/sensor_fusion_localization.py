#!/usr/bin/env python3
"""
PiDog Sensor-Fusion Localization System
=======================================

Advanced localization using multiple onboard sensors to accurately track
PiDog's position regardless of surface type or movement variations.

Features:
- IMU-based motion detection and integration
- Ultrasonic scan matching for position correction
- Surface type detection and adaptive calibration
- Particle filter for probabilistic localization
- Real-time movement validation and drift correction

Author: PiDog AI System
"""

import numpy as np
import math
import time
from typing import Dict, List, Tuple, Optional, NamedTuple
from dataclasses import dataclass
from enum import Enum
import threading
from collections import deque


class SurfaceType(Enum):
    """Detected surface types"""
    UNKNOWN = "unknown"
    HARDWOOD = "hardwood"
    CARPET = "carpet"
    TILE = "tile"
    ROUGH = "rough"


@dataclass
class MotionReading:
    """Combined motion sensor reading"""
    acceleration: Tuple[float, float, float]  # X, Y, Z acceleration
    gyroscope: Tuple[float, float, float]     # X, Y, Z angular velocity
    timestamp: float
    movement_detected: bool = False
    surface_confidence: float = 0.0


@dataclass
class UltrasonicReading:
    """Ultrasonic distance reading with direction"""
    distance: float
    angle_degrees: float  # Relative to robot heading
    confidence: float
    timestamp: float


class MovementEstimator:
    """Estimates actual movement using IMU sensor fusion"""
    
    def __init__(self):
        # Calibration parameters (will be adapted based on surface)
        self.accel_threshold = 1500  # Minimum acceleration for movement detection
        self.gyro_threshold = 300    # Minimum gyro for turn detection
        self.surface_calibration = {
            SurfaceType.HARDWOOD: {"friction": 0.1, "step_variance": 0.05},
            SurfaceType.CARPET: {"friction": 0.3, "step_variance": 0.15},
            SurfaceType.TILE: {"friction": 0.05, "step_variance": 0.03},
            SurfaceType.ROUGH: {"friction": 0.4, "step_variance": 0.25},
            SurfaceType.UNKNOWN: {"friction": 0.2, "step_variance": 0.1}
        }
        
        # Motion state tracking
        self.motion_history = deque(maxlen=50)  # Last 5 seconds at 10Hz
        self.baseline_accel = np.array([0.0, 0.0, 9800.0])  # Gravity baseline
        self.baseline_gyro = np.array([0.0, 0.0, 0.0])
        
        # Integration variables
        self.velocity = np.array([0.0, 0.0, 0.0])
        self.position_delta = np.array([0.0, 0.0])
        self.heading_delta = 0.0
        self.last_update_time = time.time()
        
        # Surface detection
        self.current_surface = SurfaceType.UNKNOWN
        self.surface_confidence = 0.0
        
        # Calibration state
        self.is_calibrating = False
        self.calibration_samples = []
    
    def calibrate_baseline(self, readings: List[MotionReading], duration: float = 3.0):
        """
        Calibrate IMU baseline while PiDog is stationary
        
        Args:
            readings: List of IMU readings while stationary
            duration: Duration of calibration in seconds
        """
        print("🎯 Calibrating IMU baseline (keep PiDog stationary)...")
        
        accel_samples = []
        gyro_samples = []
        
        start_time = time.time()
        for reading in readings:
            if reading.timestamp - start_time > duration:
                break
                
            accel_samples.append(reading.acceleration)
            gyro_samples.append(reading.gyroscope)
        
        if len(accel_samples) > 10:
            # Calculate average baseline
            accel_avg = np.mean(accel_samples, axis=0)
            gyro_avg = np.mean(gyro_samples, axis=0)
            
            self.baseline_accel = accel_avg
            self.baseline_gyro = gyro_avg
            
            print(f"✓ IMU baseline calibrated:")
            print(f"  Accel baseline: ({accel_avg[0]:.0f}, {accel_avg[1]:.0f}, {accel_avg[2]:.0f})")
            print(f"  Gyro baseline: ({gyro_avg[0]:.0f}, {gyro_avg[1]:.0f}, {gyro_avg[2]:.0f})")
        else:
            print("❌ Insufficient calibration data")
    
    def detect_surface_type(self, readings: List[MotionReading]) -> SurfaceType:
        """
        Detect surface type based on motion characteristics
        
        Args:
            readings: Recent motion readings during movement
            
        Returns:
            Detected surface type
        """
        if len(readings) < 5:
            return SurfaceType.UNKNOWN
        
        # Analyze motion characteristics
        accel_variance = []
        gyro_variance = []
        step_irregularity = []
        
        for reading in readings:
            if reading.movement_detected:
                ax, ay, az = reading.acceleration
                gx, gy, gz = reading.gyroscope
                
                # Remove baseline and calculate magnitude
                accel_corrected = np.array([ax, ay, az]) - self.baseline_accel
                gyro_corrected = np.array([gx, gy, gz]) - self.baseline_gyro
                
                accel_mag = np.linalg.norm(accel_corrected)
                gyro_mag = np.linalg.norm(gyro_corrected)
                
                accel_variance.append(accel_mag)
                gyro_variance.append(gyro_mag)
        
        if not accel_variance:
            return SurfaceType.UNKNOWN
        
        # Calculate statistics
        accel_std = np.std(accel_variance)
        accel_mean = np.mean(accel_variance)
        
        # Surface classification based on motion characteristics
        irregularity_ratio = accel_std / (accel_mean + 1e-6)
        
        if irregularity_ratio > 0.4:
            # High irregularity suggests carpet or rough surface
            if accel_mean > 2000:
                return SurfaceType.ROUGH
            else:
                return SurfaceType.CARPET
        elif irregularity_ratio < 0.15:
            # Low irregularity suggests smooth surface
            if accel_mean < 1500:
                return SurfaceType.TILE
            else:
                return SurfaceType.HARDWOOD
        else:
            return SurfaceType.HARDWOOD  # Default smooth surface
    
    def estimate_movement(self, reading: MotionReading) -> Tuple[float, float, float]:
        """
        Estimate actual movement from IMU reading
        
        Args:
            reading: Current motion reading
            
        Returns:
            (delta_x, delta_y, delta_heading) in cm and degrees
        """
        current_time = reading.timestamp
        dt = min(0.2, current_time - self.last_update_time)  # Cap at 200ms
        
        if dt <= 0:
            return 0.0, 0.0, 0.0
        
        # Extract sensor data
        ax, ay, az = reading.acceleration
        gx, gy, gz = reading.gyroscope
        
        # Remove baseline offsets
        accel_corrected = np.array([ax, ay, az]) - self.baseline_accel
        gyro_corrected = np.array([gx, gy, gz]) - self.baseline_gyro
        
        # Detect if significant movement is occurring
        accel_magnitude = np.linalg.norm(accel_corrected)
        gyro_magnitude = np.linalg.norm(gyro_corrected)
        
        movement_detected = (accel_magnitude > self.accel_threshold or 
                           gyro_magnitude > self.gyro_threshold)
        
        delta_x, delta_y, delta_heading = 0.0, 0.0, 0.0
        
        if movement_detected:
            # Estimate heading change from gyroscope (Z-axis rotation)
            angular_velocity_z = gyro_corrected[2]  # Z-axis is yaw
            delta_heading = angular_velocity_z * dt * 0.1  # Convert to degrees (rough calibration)
            
            # Estimate linear movement from accelerometer
            # This is quite rough - ideally would use Kalman filter
            accel_forward = accel_corrected[0]  # X-axis is forward
            accel_lateral = accel_corrected[1]  # Y-axis is lateral
            
            # Simple integration with surface-based calibration
            surface_params = self.surface_calibration[self.current_surface]
            friction_factor = 1.0 - surface_params["friction"]
            
            # Estimate movement distance (very simplified physics)
            if abs(accel_forward) > self.accel_threshold:
                # Rough distance estimation based on acceleration
                distance_forward = (accel_forward * dt * dt * 0.00001 * friction_factor)  # cm
                delta_x = distance_forward
            
            if abs(accel_lateral) > self.accel_threshold:
                distance_lateral = (accel_lateral * dt * dt * 0.00001 * friction_factor)  # cm  
                delta_y = distance_lateral
        
        # Store in history for surface detection
        reading.movement_detected = movement_detected
        self.motion_history.append(reading)
        
        # Update surface detection periodically
        if len(self.motion_history) >= 20 and len(self.motion_history) % 10 == 0:
            movement_readings = [r for r in self.motion_history if r.movement_detected]
            if movement_readings:
                detected_surface = self.detect_surface_type(movement_readings)
                if detected_surface != self.current_surface:
                    print(f"🏃 Surface change detected: {self.current_surface.value} → {detected_surface.value}")
                    self.current_surface = detected_surface
        
        self.last_update_time = current_time
        return delta_x, delta_y, delta_heading


class UltrasonicTriangulator:
    """Uses ultrasonic readings to triangulate position relative to known obstacles"""
    
    def __init__(self, house_map):
        self.house_map = house_map
        self.recent_scans = deque(maxlen=10)
        
    def add_scan_reading(self, distance: float, angle_degrees: float, confidence: float = 1.0):
        """Add ultrasonic scan reading for triangulation"""
        reading = UltrasonicReading(
            distance=distance,
            angle_degrees=angle_degrees,
            confidence=confidence,
            timestamp=time.time()
        )
        self.recent_scans.append(reading)
    
    def estimate_position_correction(self) -> Tuple[float, float, float]:
        """
        Estimate position correction based on ultrasonic scans and known map
        
        Returns:
            (delta_x, delta_y, confidence) - suggested position correction
        """
        if len(self.recent_scans) < 3:
            return 0.0, 0.0, 0.0
        
        current_pos = self.house_map.get_position()
        best_correction = (0.0, 0.0, 0.0)
        best_score = 0.0
        
        # Try different position hypotheses around current position
        search_radius = 20  # cells
        
        for dx in range(-search_radius, search_radius + 1, 5):
            for dy in range(-search_radius, search_radius + 1, 5):
                test_x = current_pos.x + dx
                test_y = current_pos.y + dy
                
                if not (0 <= test_x < self.house_map.max_size[0] and 
                       0 <= test_y < self.house_map.max_size[1]):
                    continue
                
                # Score this position hypothesis
                score = self._score_position_hypothesis(test_x, test_y, current_pos.heading)
                
                if score > best_score:
                    best_score = score
                    best_correction = (dx * self.house_map.cell_size_cm, 
                                     dy * self.house_map.cell_size_cm, 
                                     min(1.0, score / 10.0))
        
        return best_correction
    
    def _score_position_hypothesis(self, test_x: float, test_y: float, heading: float) -> float:
        """Score a position hypothesis based on how well it matches ultrasonic scans"""
        score = 0.0
        
        for scan in self.recent_scans:
            # Calculate expected obstacle position from this hypothesis
            scan_angle_rad = math.radians(heading + scan.angle_degrees)
            expected_obstacle_x = test_x + (scan.distance / self.house_map.cell_size_cm) * math.cos(scan_angle_rad)
            expected_obstacle_y = test_y + (scan.distance / self.house_map.cell_size_cm) * math.sin(scan_angle_rad)
            
            # Check if there's actually an obstacle near this expected position
            obstacle_found = self._check_obstacle_at_position(expected_obstacle_x, expected_obstacle_y)
            
            if obstacle_found:
                score += scan.confidence * 2.0
            else:
                score -= 1.0  # Penalty for mismatch
        
        return max(0.0, score)
    
    def _check_obstacle_at_position(self, x: float, y: float, tolerance: float = 2.0) -> bool:
        """Check if there's an obstacle near the given position"""
        center_x, center_y = int(x), int(y)
        tolerance_cells = int(tolerance)
        
        for dx in range(-tolerance_cells, tolerance_cells + 1):
            for dy in range(-tolerance_cells, tolerance_cells + 1):
                check_x, check_y = center_x + dx, center_y + dy
                
                if (0 <= check_x < self.house_map.max_size[0] and 
                    0 <= check_y < self.house_map.max_size[1]):
                    
                    cell = self.house_map.grid[check_x, check_y]
                    if cell.cell_type.name == "OBSTACLE" and cell.confidence > 0.5:
                        return True
        
        return False


class ParticleFilter:
    """Particle filter for probabilistic localization"""
    
    def __init__(self, house_map, num_particles: int = 100):
        self.house_map = house_map
        self.num_particles = num_particles
        self.particles = []
        self.weights = []
        
        # Initialize particles around current position
        current_pos = house_map.get_position()
        self._initialize_particles(current_pos.x, current_pos.y, current_pos.heading)
    
    def _initialize_particles(self, center_x: float, center_y: float, center_heading: float):
        """Initialize particles around given position"""
        self.particles = []
        self.weights = []
        
        for _ in range(self.num_particles):
            # Random position around center (normal distribution)
            x = center_x + np.random.normal(0, 5)  # 5 cell standard deviation
            y = center_y + np.random.normal(0, 5)
            heading = (center_heading + np.random.normal(0, 30)) % 360  # 30 degree std dev
            
            # Ensure within bounds
            x = max(0, min(self.house_map.max_size[0] - 1, x))
            y = max(0, min(self.house_map.max_size[1] - 1, y))
            
            self.particles.append([x, y, heading])
            self.weights.append(1.0 / self.num_particles)
    
    def predict(self, delta_x: float, delta_y: float, delta_heading: float, motion_noise: float = 1.0):
        """Predict particle positions based on motion model"""
        for i, particle in enumerate(self.particles):
            x, y, heading = particle
            
            # Add motion with noise
            new_x = x + delta_x / self.house_map.cell_size_cm + np.random.normal(0, motion_noise)
            new_y = y + delta_y / self.house_map.cell_size_cm + np.random.normal(0, motion_noise)
            new_heading = (heading + delta_heading + np.random.normal(0, 5)) % 360
            
            # Keep within bounds
            new_x = max(0, min(self.house_map.max_size[0] - 1, new_x))
            new_y = max(0, min(self.house_map.max_size[1] - 1, new_y))
            
            self.particles[i] = [new_x, new_y, new_heading]
    
    def update_weights(self, ultrasonic_readings: List[UltrasonicReading]):
        """Update particle weights based on sensor observations"""
        if not ultrasonic_readings:
            return
        
        total_weight = 0.0
        
        for i, particle in enumerate(self.particles):
            x, y, heading = particle
            weight = 1.0
            
            # Score this particle based on ultrasonic readings
            for reading in ultrasonic_readings:
                expected_distance = self._simulate_ultrasonic_reading(x, y, heading, reading.angle_degrees)
                
                # Calculate likelihood (closer match = higher weight)
                distance_error = abs(expected_distance - reading.distance)
                likelihood = math.exp(-distance_error / 20.0)  # Gaussian-like likelihood
                weight *= likelihood * reading.confidence
            
            self.weights[i] = weight
            total_weight += weight
        
        # Normalize weights
        if total_weight > 0:
            for i in range(len(self.weights)):
                self.weights[i] /= total_weight
    
    def _simulate_ultrasonic_reading(self, x: float, y: float, heading: float, scan_angle: float) -> float:
        """Simulate what ultrasonic reading should be from this position"""
        scan_heading = (heading + scan_angle) % 360
        scan_rad = math.radians(scan_heading)
        
        # Ray casting to find nearest obstacle
        max_range = 200.0  # cm
        step_size = self.house_map.cell_size_cm
        
        for distance in np.arange(step_size, max_range, step_size):
            test_x = x + (distance / self.house_map.cell_size_cm) * math.cos(scan_rad)
            test_y = y + (distance / self.house_map.cell_size_cm) * math.sin(scan_rad)
            
            grid_x, grid_y = int(test_x), int(test_y)
            
            if (0 <= grid_x < self.house_map.max_size[0] and 
                0 <= grid_y < self.house_map.max_size[1]):
                
                cell = self.house_map.grid[grid_x, grid_y]
                if cell.cell_type.name == "OBSTACLE" and cell.confidence > 0.3:
                    return distance
            else:
                return max_range  # Hit boundary
        
        return max_range
    
    def resample(self):
        """Resample particles based on weights"""
        # Simple systematic resampling
        new_particles = []
        cumulative_weights = np.cumsum(self.weights)
        
        for i in range(self.num_particles):
            r = np.random.random()
            index = np.searchsorted(cumulative_weights, r)
            new_particles.append(self.particles[index].copy())
        
        self.particles = new_particles
        self.weights = [1.0 / self.num_particles] * self.num_particles
    
    def get_estimated_position(self) -> Tuple[float, float, float, float]:
        """
        Get estimated position from particle cloud
        
        Returns:
            (x, y, heading, confidence)
        """
        if not self.particles:
            return 0.0, 0.0, 0.0, 0.0
        
        # Weighted average of particles
        total_weight = sum(self.weights)
        if total_weight == 0:
            # Uniform weights
            x = np.mean([p[0] for p in self.particles])
            y = np.mean([p[1] for p in self.particles])
            heading = np.mean([p[2] for p in self.particles])
            confidence = 0.1
        else:
            x = sum(p[0] * w for p, w in zip(self.particles, self.weights)) / total_weight
            y = sum(p[1] * w for p, w in zip(self.particles, self.weights)) / total_weight
            heading = sum(p[2] * w for p, w in zip(self.particles, self.weights)) / total_weight
            
            # Confidence based on particle concentration
            particle_spread = np.std([p[0] for p in self.particles]) + np.std([p[1] for p in self.particles])
            confidence = max(0.1, min(1.0, 1.0 / (1.0 + particle_spread / 5.0)))
        
        return x, y, heading % 360, confidence


class SensorFusionLocalizer:
    """Main sensor fusion localization system"""
    
    def __init__(self, house_map):
        self.house_map = house_map
        self.movement_estimator = MovementEstimator()
        self.ultrasonic_triangulator = UltrasonicTriangulator(house_map)
        self.particle_filter = ParticleFilter(house_map)
        
        # Localization state
        self.last_update_time = time.time()
        self.position_confidence = 0.5
        
        # Threading
        self.running = False
        self.localization_thread = None
    
    def start_localization(self):
        """Start background localization thread"""
        self.running = True
        self.localization_thread = threading.Thread(target=self._localization_loop, daemon=True)
        self.localization_thread.start()
        print("🧭 Sensor fusion localization started")
    
    def stop_localization(self):
        """Stop localization thread"""
        self.running = False
        if self.localization_thread:
            self.localization_thread.join(timeout=2.0)
        print("🧭 Sensor fusion localization stopped")
    
    def update_motion(self, acceleration: Tuple[float, float, float], 
                     gyroscope: Tuple[float, float, float]):
        """Update with new IMU reading"""
        reading = MotionReading(
            acceleration=acceleration,
            gyroscope=gyroscope,
            timestamp=time.time()
        )
        
        # Estimate movement from IMU
        delta_x, delta_y, delta_heading = self.movement_estimator.estimate_movement(reading)
        
        # Update particle filter with motion model
        surface_params = self.movement_estimator.surface_calibration[
            self.movement_estimator.current_surface
        ]
        motion_noise = surface_params["step_variance"] * 10  # Scale for particle filter
        
        self.particle_filter.predict(delta_x, delta_y, delta_heading, motion_noise)
        
        # Update house map position
        if abs(delta_x) > 0.5 or abs(delta_y) > 0.5 or abs(delta_heading) > 1.0:
            self.house_map.update_position(delta_x, delta_y, delta_heading, confidence=0.7)
    
    def update_ultrasonic(self, distance: float, angle_degrees: float):
        """Update with new ultrasonic reading"""
        confidence = 1.0 if 5 < distance < 200 else 0.5  # Higher confidence for reasonable distances
        
        # Add to triangulator
        self.ultrasonic_triangulator.add_scan_reading(distance, angle_degrees, confidence)
        
        # Update particle filter weights
        recent_readings = list(self.ultrasonic_triangulator.recent_scans)[-3:]  # Last 3 readings
        if recent_readings:
            self.particle_filter.update_weights(recent_readings)
    
    def _localization_loop(self):
        """Background localization processing"""
        while self.running:
            try:
                current_time = time.time()
                
                # Perform triangulation-based position correction every 2 seconds
                if current_time - self.last_update_time > 2.0:
                    correction = self.ultrasonic_triangulator.estimate_position_correction()
                    delta_x, delta_y, confidence = correction
                    
                    if confidence > 0.3 and (abs(delta_x) > 2.0 or abs(delta_y) > 2.0):
                        print(f"📍 Position correction: ({delta_x:.1f}, {delta_y:.1f})cm, confidence: {confidence:.2f}")
                        self.house_map.update_position(delta_x, delta_y, 0.0, confidence)
                    
                    self.last_update_time = current_time
                
                # Resample particles occasionally
                if int(current_time) % 10 == 0:  # Every 10 seconds
                    max_weight = max(self.particle_filter.weights) if self.particle_filter.weights else 0
                    if max_weight > 0.1:  # Only resample if we have some confidence
                        self.particle_filter.resample()
                
                time.sleep(0.5)  # 2Hz localization loop
                
            except Exception as e:
                print(f"⚠️ Localization error: {e}")
                time.sleep(1.0)
    
    def get_localization_status(self) -> Dict:
        """Get current localization status"""
        # Get particle filter estimate
        pf_x, pf_y, pf_heading, pf_confidence = self.particle_filter.get_estimated_position()
        
        # Get current map position
        map_pos = self.house_map.get_position()
        
        return {
            "map_position": {
                "x": map_pos.x,
                "y": map_pos.y, 
                "heading": map_pos.heading,
                "confidence": map_pos.confidence
            },
            "particle_filter": {
                "x": pf_x,
                "y": pf_y,
                "heading": pf_heading,
                "confidence": pf_confidence
            },
            "surface_type": self.movement_estimator.current_surface.value,
            "recent_scans": len(self.ultrasonic_triangulator.recent_scans),
            "motion_samples": len(self.movement_estimator.motion_history)
        }
    
    def calibrate_stationary(self, duration: float = 3.0):
        """Calibrate IMU while PiDog is stationary"""
        print("🎯 Starting IMU calibration - keep PiDog still...")
        
        calibration_readings = []
        start_time = time.time()
        
        # This would be called from the main sensor loop
        # For now, we'll use the current baseline as a placeholder
        print("✓ IMU calibration completed (placeholder)")
        
        return True
