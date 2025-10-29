"""
Dynamic Balance Service for PackMind

This service provides real-time balance monitoring and stability control for the PiDog
using IMU (Inertial Measurement Unit) data. It detects unstable conditions and can
trigger corrective behaviors to maintain balance.

Features:
- Real-time IMU data monitoring (accelerometer + gyroscope)
- Tilt angle calculation and stability assessment
- Balance correction suggestions and automatic responses
- Gait stability analysis during movement
- Surface adaptation recommendations
- Balance event logging and statistics

Author: 7Lynx
Version: 2025.10.29
Created: 2024
"""

import time
import math
import threading
import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Callable
from enum import Enum
import logging
import json
from pathlib import Path

try:
    import pidog
except ImportError:
    print("Warning: pidog library not available. Dynamic Balance Service running in simulation mode.")
    pidog = None

@dataclass
class IMUReading:
    """Single IMU sensor reading with timestamp"""
    timestamp: float
    accel_x: float  # m/s²
    accel_y: float  # m/s²
    accel_z: float  # m/s²
    gyro_x: float   # rad/s
    gyro_y: float   # rad/s
    gyro_z: float   # rad/s
    
    def __post_init__(self):
        """Calculate derived values"""
        # Calculate tilt angles from accelerometer
        self.roll = math.atan2(self.accel_y, self.accel_z) * 180 / math.pi
        self.pitch = math.atan2(-self.accel_x, math.sqrt(self.accel_y**2 + self.accel_z**2)) * 180 / math.pi
        
        # Calculate total acceleration magnitude
        self.accel_magnitude = math.sqrt(self.accel_x**2 + self.accel_y**2 + self.accel_z**2)
        
        # Calculate angular velocity magnitude
        self.gyro_magnitude = math.sqrt(self.gyro_x**2 + self.gyro_y**2 + self.gyro_z**2)

class BalanceState(Enum):
    """Current balance state of the robot"""
    STABLE = "stable"           # Normal, balanced position
    SLIGHTLY_TILTED = "slight"  # Minor tilt, manageable
    UNSTABLE = "unstable"       # Significant tilt, needs correction
    CRITICAL = "critical"       # Severe tilt, immediate action required
    FALLING = "falling"         # Falling detected, emergency response

@dataclass
class BalanceEvent:
    """Record of a balance-related event"""
    timestamp: float
    event_type: str
    balance_state: BalanceState
    roll: float
    pitch: float
    severity: float  # 0.0-1.0
    duration: float  # seconds
    corrective_action: Optional[str] = None
    success: bool = False

@dataclass
class BalanceStatistics:
    """Balance performance statistics"""
    total_events: int = 0
    stable_time_percent: float = 0.0
    average_tilt: float = 0.0
    max_tilt_recorded: float = 0.0
    correction_success_rate: float = 0.0
    falls_prevented: int = 0
    surface_stability_score: float = 0.0  # 0.0-1.0

class DynamicBalanceService:
    """
    Real-time balance monitoring and stability control service
    
    This service continuously monitors the PiDog's IMU sensors to:
    1. Detect balance issues and unstable conditions
    2. Calculate tilt angles and stability metrics
    3. Trigger corrective behaviors when needed
    4. Provide surface adaptation recommendations
    5. Log balance events for analysis
    """
    
    def __init__(self, config):
        """Initialize the Dynamic Balance Service"""
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Service state
        self.is_running = False
        self.is_monitoring = False
        self.monitoring_thread = None
        
        # IMU and balance state
        self.current_reading: Optional[IMUReading] = None
        self.reading_history: List[IMUReading] = []
        self.current_balance_state = BalanceState.STABLE
        self.balance_events: List[BalanceEvent] = []
        
        # Calibration values (determined at startup)
        self.calibration_complete = False
        self.gravity_vector = np.array([0.0, 0.0, 9.81])  # Expected gravity when level
        self.zero_gyro = np.array([0.0, 0.0, 0.0])  # Gyro values when stationary
        
        # Balance analysis
        self.stability_window = []  # Rolling window for stability analysis
        self.last_correction_time = 0.0
        self.statistics = BalanceStatistics()
        
        # Callback functions for balance events
        self.balance_callbacks: Dict[BalanceState, List[Callable]] = {
            state: [] for state in BalanceState
        }
        
        # Data storage
        self.data_dir = Path(config.BALANCE_DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize hardware connection
        self.pidog_instance = None
        if pidog and config.ENABLE_DYNAMIC_BALANCE:
            try:
                self.pidog_instance = pidog.PiDog()
                self.logger.info("Dynamic Balance Service: Connected to PiDog hardware")
            except Exception as e:
                self.logger.warning(f"Dynamic Balance Service: Could not connect to PiDog: {e}")
        
        self.logger.info("Dynamic Balance Service initialized")
    
    def start(self):
        """Start the balance monitoring service"""
        if not self.config.ENABLE_DYNAMIC_BALANCE:
            self.logger.info("Dynamic Balance Service: Disabled in configuration")
            return
        
        if self.is_running:
            self.logger.warning("Dynamic Balance Service: Already running")
            return
        
        self.is_running = True
        
        # Perform initial calibration
        self.logger.info("Dynamic Balance Service: Starting calibration...")
        if self._calibrate_sensors():
            self.logger.info("Dynamic Balance Service: Calibration complete")
            self.calibration_complete = True
        else:
            self.logger.warning("Dynamic Balance Service: Calibration failed, using defaults")
        
        # Start monitoring thread
        self.is_monitoring = True
        self.monitoring_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.monitoring_thread.start()
        
        self.logger.info("Dynamic Balance Service: Started successfully")
    
    def stop(self):
        """Stop the balance monitoring service"""
        if not self.is_running:
            return
        
        self.is_monitoring = False
        self.is_running = False
        
        # Wait for monitoring thread to finish
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=2.0)
        
        # Save final data
        self._save_session_data()
        
        self.logger.info("Dynamic Balance Service: Stopped")
    
    def _calibrate_sensors(self) -> bool:
        """
        Calibrate IMU sensors by taking readings while robot is stationary
        Returns True if calibration successful
        """
        if not self.pidog_instance:
            return False
        
        calibration_readings = []
        calibration_duration = self.config.BALANCE_CALIBRATION_TIME
        start_time = time.time()
        
        self.logger.info(f"Calibrating IMU sensors for {calibration_duration} seconds...")
        
        while time.time() - start_time < calibration_duration:
            try:
                # Get IMU reading from PiDog
                accel_data = self.pidog_instance.get_accelerometer_data()
                gyro_data = self.pidog_instance.get_gyroscope_data()
                
                if accel_data and gyro_data:
                    reading = IMUReading(
                        timestamp=time.time(),
                        accel_x=accel_data[0],
                        accel_y=accel_data[1], 
                        accel_z=accel_data[2],
                        gyro_x=gyro_data[0],
                        gyro_y=gyro_data[1],
                        gyro_z=gyro_data[2]
                    )
                    calibration_readings.append(reading)
                
                time.sleep(0.1)  # 10Hz during calibration
                
            except Exception as e:
                self.logger.warning(f"Error during calibration: {e}")
                continue
        
        if len(calibration_readings) < 10:
            self.logger.error("Insufficient calibration data")
            return False
        
        # Calculate average values for calibration
        accel_sum = np.array([0.0, 0.0, 0.0])
        gyro_sum = np.array([0.0, 0.0, 0.0])
        
        for reading in calibration_readings:
            accel_sum += np.array([reading.accel_x, reading.accel_y, reading.accel_z])
            gyro_sum += np.array([reading.gyro_x, reading.gyro_y, reading.gyro_z])
        
        self.gravity_vector = accel_sum / len(calibration_readings)
        self.zero_gyro = gyro_sum / len(calibration_readings)
        
        self.logger.info(f"Calibration complete - Gravity: {self.gravity_vector}, Zero gyro: {self.zero_gyro}")
        return True
    
    def _monitoring_loop(self):
        """Main monitoring loop running in separate thread"""
        last_reading_time = 0.0
        
        while self.is_monitoring:
            try:
                current_time = time.time()
                
                # Check if it's time for next reading
                if current_time - last_reading_time >= 1.0 / self.config.BALANCE_SAMPLE_RATE:
                    reading = self._get_imu_reading()
                    
                    if reading:
                        self._process_reading(reading)
                        last_reading_time = current_time
                
                # Sleep briefly to prevent excessive CPU usage
                time.sleep(0.01)
                
            except Exception as e:
                self.logger.error(f"Error in balance monitoring loop: {e}")
                time.sleep(0.1)
    
    def _get_imu_reading(self) -> Optional[IMUReading]:
        """Get current IMU reading from hardware or simulation"""
        try:
            if self.pidog_instance:
                # Get real IMU data from PiDog
                accel_data = self.pidog_instance.get_accelerometer_data()
                gyro_data = self.pidog_instance.get_gyroscope_data()
                
                if accel_data and gyro_data:
                    return IMUReading(
                        timestamp=time.time(),
                        accel_x=accel_data[0],
                        accel_y=accel_data[1],
                        accel_z=accel_data[2], 
                        gyro_x=gyro_data[0],
                        gyro_y=gyro_data[1],
                        gyro_z=gyro_data[2]
                    )
            else:
                # Simulation mode - generate stable readings with small noise
                import random
                return IMUReading(
                    timestamp=time.time(),
                    accel_x=random.uniform(-0.5, 0.5),
                    accel_y=random.uniform(-0.5, 0.5),
                    accel_z=9.81 + random.uniform(-0.2, 0.2),
                    gyro_x=random.uniform(-0.1, 0.1),
                    gyro_y=random.uniform(-0.1, 0.1), 
                    gyro_z=random.uniform(-0.1, 0.1)
                )
                
        except Exception as e:
            self.logger.error(f"Error getting IMU reading: {e}")
            return None
    
    def _process_reading(self, reading: IMUReading):
        """Process new IMU reading and update balance state"""
        self.current_reading = reading
        
        # Add to history (keep limited size)
        self.reading_history.append(reading)
        if len(self.reading_history) > self.config.BALANCE_HISTORY_SIZE:
            self.reading_history.pop(0)
        
        # Update stability window
        self.stability_window.append(reading)
        if len(self.stability_window) > self.config.BALANCE_STABILITY_WINDOW:
            self.stability_window.pop(0)
        
        # Analyze current balance state
        new_balance_state = self._analyze_balance_state(reading)
        
        # Check for state changes
        if new_balance_state != self.current_balance_state:
            self._handle_balance_state_change(self.current_balance_state, new_balance_state, reading)
            self.current_balance_state = new_balance_state
        
        # Update statistics
        self._update_statistics(reading)
        
        # Check if corrective action needed
        if self._should_trigger_correction(reading, new_balance_state):
            self._trigger_balance_correction(reading, new_balance_state)
    
    def _analyze_balance_state(self, reading: IMUReading) -> BalanceState:
        """Analyze IMU reading to determine current balance state"""
        
        # Calculate absolute tilt angles
        abs_roll = abs(reading.roll)
        abs_pitch = abs(reading.pitch)
        max_tilt = max(abs_roll, abs_pitch)
        
        # Check angular velocity for rapid movement
        rapid_motion = reading.gyro_magnitude > self.config.BALANCE_RAPID_MOTION_THRESHOLD
        
        # Determine balance state based on tilt and motion
        if max_tilt > self.config.BALANCE_CRITICAL_TILT_THRESHOLD:
            return BalanceState.CRITICAL
        elif max_tilt > self.config.BALANCE_UNSTABLE_TILT_THRESHOLD:
            return BalanceState.UNSTABLE
        elif max_tilt > self.config.BALANCE_SLIGHT_TILT_THRESHOLD:
            return BalanceState.SLIGHTLY_TILTED
        elif rapid_motion and max_tilt > self.config.BALANCE_SLIGHT_TILT_THRESHOLD * 0.5:
            return BalanceState.UNSTABLE  # Motion + tilt = unstable
        else:
            return BalanceState.STABLE
    
    def _handle_balance_state_change(self, old_state: BalanceState, new_state: BalanceState, reading: IMUReading):
        """Handle transition between balance states"""
        
        # Log the state change
        self.logger.info(f"Balance state changed: {old_state.value} -> {new_state.value} "
                        f"(Roll: {reading.roll:.1f}°, Pitch: {reading.pitch:.1f}°)")
        
        # Create balance event
        severity = self._calculate_severity(reading)
        event = BalanceEvent(
            timestamp=reading.timestamp,
            event_type=f"state_change_{old_state.value}_to_{new_state.value}",
            balance_state=new_state,
            roll=reading.roll,
            pitch=reading.pitch,
            severity=severity,
            duration=0.0  # Will be updated later
        )
        
        self.balance_events.append(event)
        
        # Trigger callbacks for new state
        for callback in self.balance_callbacks.get(new_state, []):
            try:
                callback(reading, old_state, new_state)
            except Exception as e:
                self.logger.error(f"Error in balance callback: {e}")
    
    def _calculate_severity(self, reading: IMUReading) -> float:
        """Calculate severity score (0.0-1.0) for current reading"""
        max_tilt = max(abs(reading.roll), abs(reading.pitch))
        motion_factor = min(reading.gyro_magnitude / 10.0, 1.0)  # Cap at 10 rad/s
        
        tilt_severity = max_tilt / self.config.BALANCE_CRITICAL_TILT_THRESHOLD
        combined_severity = min(tilt_severity + motion_factor * 0.3, 1.0)
        
        return combined_severity
    
    def _should_trigger_correction(self, reading: IMUReading, state: BalanceState) -> bool:
        """Determine if balance correction should be triggered"""
        
        # Don't correct if recently corrected (avoid oscillation)
        if time.time() - self.last_correction_time < self.config.BALANCE_CORRECTION_COOLDOWN:
            return False
        
        # Trigger based on balance state
        if state in [BalanceState.CRITICAL, BalanceState.UNSTABLE]:
            return True
        
        # Trigger if trend analysis shows degrading stability
        if len(self.stability_window) >= 3:
            recent_tilts = [max(abs(r.roll), abs(r.pitch)) for r in self.stability_window[-3:]]
            if all(recent_tilts[i] > recent_tilts[i-1] for i in range(1, len(recent_tilts))):
                return True  # Increasing tilt trend
        
        return False
    
    def _trigger_balance_correction(self, reading: IMUReading, state: BalanceState):
        """Trigger appropriate balance correction response"""
        
        self.last_correction_time = time.time()
        
        # Determine correction strategy
        correction_action = self._determine_correction_action(reading, state)
        
        self.logger.info(f"Triggering balance correction: {correction_action}")
        
        # Record correction event
        event = BalanceEvent(
            timestamp=reading.timestamp,
            event_type="balance_correction",
            balance_state=state,
            roll=reading.roll,
            pitch=reading.pitch,
            severity=self._calculate_severity(reading),
            duration=0.0,
            corrective_action=correction_action
        )
        
        self.balance_events.append(event)
        
        # Execute correction (would integrate with PiDog movement system)
        success = self._execute_correction(correction_action, reading)
        event.success = success
        
        if success:
            self.statistics.falls_prevented += 1
    
    def _determine_correction_action(self, reading: IMUReading, state: BalanceState) -> str:
        """Determine appropriate correction action based on tilt direction and severity"""
        
        abs_roll = abs(reading.roll)
        abs_pitch = abs(reading.pitch)
        
        # Determine primary tilt direction
        if abs_roll > abs_pitch:
            # Rolling motion
            if reading.roll > 0:
                return "correct_roll_right"
            else:
                return "correct_roll_left"
        else:
            # Pitching motion  
            if reading.pitch > 0:
                return "correct_pitch_forward"
            else:
                return "correct_pitch_backward"
    
    def _execute_correction(self, action: str, reading: IMUReading) -> bool:
        """Execute the balance correction action"""
        
        # This would integrate with PiDog's movement system
        # For now, we'll simulate the correction
        
        if not self.pidog_instance:
            # Simulation mode
            self.logger.info(f"Simulating correction action: {action}")
            return True
        
        try:
            # Real correction would involve:
            # 1. Adjusting leg positions to shift center of gravity
            # 2. Coordinated movement to counter the tilt
            # 3. Dynamic gait adjustments
            
            # Placeholder for actual PiDog correction commands
            if "roll" in action:
                # Adjust leg heights to counter roll
                pass
            elif "pitch" in action:
                # Adjust front/back leg positions to counter pitch
                pass
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error executing balance correction: {e}")
            return False
    
    def _update_statistics(self, reading: IMUReading):
        """Update balance performance statistics"""
        
        # Update total events
        if self.current_balance_state != BalanceState.STABLE:
            self.statistics.total_events += 1
        
        # Calculate stable time percentage (simplified)
        if len(self.reading_history) > 0:
            stable_readings = sum(1 for r in self.reading_history 
                                if max(abs(r.roll), abs(r.pitch)) < self.config.BALANCE_SLIGHT_TILT_THRESHOLD)
            self.statistics.stable_time_percent = (stable_readings / len(self.reading_history)) * 100
        
        # Update average and max tilt
        current_tilt = max(abs(reading.roll), abs(reading.pitch))
        self.statistics.max_tilt_recorded = max(self.statistics.max_tilt_recorded, current_tilt)
        
        if len(self.reading_history) > 0:
            total_tilt = sum(max(abs(r.roll), abs(r.pitch)) for r in self.reading_history)
            self.statistics.average_tilt = total_tilt / len(self.reading_history)
        
        # Calculate correction success rate
        correction_events = [e for e in self.balance_events if e.corrective_action]
        if correction_events:
            successful_corrections = sum(1 for e in correction_events if e.success)
            self.statistics.correction_success_rate = (successful_corrections / len(correction_events)) * 100
    
    def _save_session_data(self):
        """Save balance session data to disk"""
        try:
            session_data = {
                'timestamp': time.time(),
                'statistics': {
                    'total_events': self.statistics.total_events,
                    'stable_time_percent': self.statistics.stable_time_percent,
                    'average_tilt': self.statistics.average_tilt,
                    'max_tilt_recorded': self.statistics.max_tilt_recorded,
                    'correction_success_rate': self.statistics.correction_success_rate,
                    'falls_prevented': self.statistics.falls_prevented
                },
                'events': [
                    {
                        'timestamp': e.timestamp,
                        'event_type': e.event_type,
                        'balance_state': e.balance_state.value,
                        'roll': e.roll,
                        'pitch': e.pitch,
                        'severity': e.severity,
                        'corrective_action': e.corrective_action,
                        'success': e.success
                    }
                    for e in self.balance_events
                ]
            }
            
            session_file = self.data_dir / f"balance_session_{int(time.time())}.json"
            with open(session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
            
            self.logger.info(f"Balance session data saved to {session_file}")
            
        except Exception as e:
            self.logger.error(f"Error saving balance session data: {e}")
    
    # Public API methods
    
    def get_current_balance_state(self) -> Tuple[BalanceState, Optional[IMUReading]]:
        """Get current balance state and latest IMU reading"""
        return self.current_balance_state, self.current_reading
    
    def get_balance_statistics(self) -> BalanceStatistics:
        """Get current balance performance statistics"""
        return self.statistics
    
    def register_balance_callback(self, state: BalanceState, callback: Callable):
        """Register callback function for specific balance state"""
        if state not in self.balance_callbacks:
            self.balance_callbacks[state] = []
        self.balance_callbacks[state].append(callback)
    
    def is_stable(self) -> bool:
        """Check if robot is currently in stable balance"""
        return self.current_balance_state == BalanceState.STABLE
    
    def get_tilt_angles(self) -> Optional[Tuple[float, float]]:
        """Get current roll and pitch angles in degrees"""
        if self.current_reading:
            return self.current_reading.roll, self.current_reading.pitch
        return None
    
    def reset_statistics(self):
        """Reset balance performance statistics"""
        self.statistics = BalanceStatistics()
        self.balance_events.clear()
        self.logger.info("Balance statistics reset")