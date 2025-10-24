#!/usr/bin/env python3
"""
PiDog Surface Calibration Demo
=============================

Demonstrates how the sensor fusion system detects different surface types
and adapts movement calibration accordingly.

Usage: python3 surface_calibration_demo.py

This script shows how PiDog can automatically detect:
- Hardwood floors (low friction, consistent movement)
- Carpet (high friction, variable movement) 
- Tile (very low friction, slippery)
- Rough surfaces (high friction, irregular movement)

Author: 7Lynx
"""

import time
import math
import random
from sensor_fusion_localization import MovementEstimator, MotionReading, SurfaceType


def simulate_surface_movement(surface_type: SurfaceType, duration: float = 5.0) -> list:
    """
    Simulate IMU readings for movement on different surface types
    
    Args:
        surface_type: Surface to simulate
        duration: Duration of simulation in seconds
        
    Returns:
        List of simulated motion readings
    """
    readings = []
    start_time = time.time()
    
    # Surface characteristics
    surface_params = {
        SurfaceType.HARDWOOD: {
            "base_accel": 2000,
            "noise_factor": 0.1,
            "step_consistency": 0.95
        },
        SurfaceType.CARPET: {
            "base_accel": 2500,
            "noise_factor": 0.3, 
            "step_consistency": 0.7
        },
        SurfaceType.TILE: {
            "base_accel": 1800,
            "noise_factor": 0.05,
            "step_consistency": 0.98
        },
        SurfaceType.ROUGH: {
            "base_accel": 3000,
            "noise_factor": 0.4,
            "step_consistency": 0.6
        }
    }
    
    params = surface_params.get(surface_type, surface_params[SurfaceType.HARDWOOD])
    
    # Simulate walking pattern
    step_frequency = 2.0  # Steps per second
    step_duration = 1.0 / step_frequency
    
    current_time = start_time
    step_phase = 0.0
    
    while current_time - start_time < duration:
        # Simulate step cycle
        step_progress = (step_phase % step_duration) / step_duration
        
        # Generate acceleration based on step cycle
        if step_progress < 0.3:  # Lift phase
            accel_magnitude = params["base_accel"] * (1.0 + step_progress * 2.0)
        elif step_progress < 0.7:  # Contact phase  
            accel_magnitude = params["base_accel"] * (2.0 - step_progress)
        else:  # Recovery phase
            accel_magnitude = params["base_accel"] * 0.5
        
        # Add surface-specific noise and consistency
        consistency = params["step_consistency"]
        noise = params["noise_factor"]
        
        accel_x = accel_magnitude * consistency + random.gauss(0, accel_magnitude * noise)
        accel_y = random.gauss(0, accel_magnitude * noise * 0.5)
        accel_z = 9800 + random.gauss(0, 100)  # Gravity + small noise
        
        # Minimal gyroscope (assuming straight walking)
        gyro_x = random.gauss(0, 50)
        gyro_y = random.gauss(0, 50) 
        gyro_z = random.gauss(0, 30)
        
        reading = MotionReading(
            acceleration=(accel_x, accel_y, accel_z),
            gyroscope=(gyro_x, gyro_y, gyro_z),
            timestamp=current_time
        )
        
        readings.append(reading)
        
        # Advance time
        current_time += 0.1  # 10Hz sampling
        step_phase += 0.1
    
    return readings


def demo_surface_detection():
    """Demonstrate surface detection capabilities"""
    print("🏃 PiDog Surface Detection Demo")
    print("=" * 40)
    
    estimator = MovementEstimator()
    
    # Test each surface type
    surfaces_to_test = [
        SurfaceType.HARDWOOD,
        SurfaceType.CARPET, 
        SurfaceType.TILE,
        SurfaceType.ROUGH
    ]
    
    for surface in surfaces_to_test:
        print(f"\n🔍 Testing surface: {surface.value.upper()}")
        print("-" * 30)
        
        # Simulate movement on this surface
        readings = simulate_surface_movement(surface, duration=3.0)
        
        print(f"Generated {len(readings)} motion samples")
        
        # Process readings through estimator
        movement_readings = []
        total_movement_x = 0.0
        total_movement_y = 0.0
        total_heading_change = 0.0
        
        for reading in readings:
            # Estimate movement from this reading
            delta_x, delta_y, delta_heading = estimator.estimate_movement(reading)
            
            total_movement_x += delta_x
            total_movement_y += delta_y
            total_heading_change += delta_heading
            
            if reading.movement_detected:
                movement_readings.append(reading)
        
        # Detect surface type
        detected_surface = estimator.detect_surface_type(movement_readings)
        
        print(f"Detected surface: {detected_surface.value}")
        print(f"Correct detection: {'✓' if detected_surface == surface else '✗'}")
        print(f"Movement detected in {len(movement_readings)}/{len(readings)} samples")
        print(f"Estimated total movement: X={total_movement_x:.1f}cm, Y={total_movement_y:.1f}cm")
        print(f"Estimated heading change: {total_heading_change:.1f}°")
        
        # Show calibration parameters
        calib = estimator.surface_calibration[detected_surface]
        print(f"Calibration - Friction: {calib['friction']:.2f}, Variance: {calib['step_variance']:.2f}")


def demo_movement_adaptation():
    """Demonstrate how movement estimation adapts to different surfaces"""
    print("\n🎯 Movement Adaptation Demo")
    print("=" * 40)
    
    # Simulate same physical movement on different surfaces
    surfaces = [SurfaceType.HARDWOOD, SurfaceType.CARPET, SurfaceType.TILE]
    
    for surface in surfaces:
        print(f"\n📍 Movement on {surface.value}:")
        
        estimator = MovementEstimator()
        estimator.current_surface = surface  # Set known surface
        
        # Simulate 10 forward steps
        readings = simulate_surface_movement(surface, duration=2.0)
        
        total_distance = 0.0
        step_count = 0
        
        for reading in readings:
            delta_x, delta_y, delta_heading = estimator.estimate_movement(reading)
            
            if abs(delta_x) > 0.1:  # Significant forward movement
                total_distance += abs(delta_x)
                step_count += 1
        
        if step_count > 0:
            avg_step_distance = total_distance / step_count
            print(f"  Average step distance: {avg_step_distance:.2f}cm")
            print(f"  Total distance (2s): {total_distance:.1f}cm")
            print(f"  Movement events: {step_count}")
        
        # Show surface parameters
        calib = estimator.surface_calibration[surface]
        print(f"  Surface friction: {calib['friction']:.2f}")
        print(f"  Expected variance: {calib['step_variance']:.2f}")


if __name__ == "__main__":
    print("🤖 PiDog Surface Calibration System Demo")
    print("=" * 50)
    print()
    print("This demo shows how PiDog can detect different floor surfaces")
    print("and adapt its movement estimation accordingly.")
    print()
    
    try:
        # Run surface detection demo
        demo_surface_detection()
        
        # Run movement adaptation demo  
        demo_movement_adaptation()
        
        print("\n" + "=" * 50)
        print("✅ Demo completed successfully!")
        print()
        print("Key Benefits of Sensor Fusion Localization:")
        print("• 🎯 Accurate position tracking on any surface")
        print("• 🏃 Automatic surface type detection") 
        print("• ⚙️ Adaptive movement calibration")
        print("• 📊 Continuous learning and improvement")
        print("• 🔄 Real-time error correction")
        
    except Exception as e:
        print(f"\n❌ Demo error: {e}")
        print("Note: This demo requires numpy for full functionality")