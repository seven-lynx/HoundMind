#!/usr/bin/env python3
"""
Advanced PiDog AI Behavior Demo
==============================

This demonstrates a complete AI-powered PiDog with:
- Sensor fusion and decision making
- State machine behavior
- Emotional responses
- Learning patterns
- Advanced movement coordination

Features demonstrated:
✓ Multi-sensor integration
✓ Behavior state machine  
✓ Emotional LED responses
✓ Sound-reactive head tracking
✓ Obstacle avoidance with memory
✓ Touch interaction learning
✓ Energy management system
✓ Coordinated multi-part movement

Run with: python3 advanced_pidog_ai.py
"""

# ============================================================================
# CONFIGURATION IMPORT
# ============================================================================
# Configuration is now in separate pidog_config.py file for easier editing!

try:
    from pidog_config import load_config, validate_config
    CONFIG_AVAILABLE = True
    print("📋 Configuration system loaded from pidog_config.py")
except ImportError:
    CONFIG_AVAILABLE = False
    print("⚠️ pidog_config.py not found - using basic embedded config")
    
    # Fallback basic configuration if separate file not available
    class PiDogConfig:
        # Basic settings only
        ENABLE_VOICE_COMMANDS = True
        ENABLE_SLAM_MAPPING = False  # Conservative default
        ENABLE_SENSOR_FUSION = False
        ENABLE_INTELLIGENT_SCANNING = True
        ENABLE_EMOTIONAL_SYSTEM = True
        ENABLE_LEARNING_SYSTEM = True
        ENABLE_PATROL_LOGGING = True
        ENABLE_AUTONOMOUS_NAVIGATION = False
        
        OBSTACLE_IMMEDIATE_THREAT = 25.0
        OBSTACLE_APPROACHING_THREAT = 40.0
        OBSTACLE_SAFE_DISTANCE = 45.0
        OBSTACLE_SCAN_INTERVAL = 0.5
        
        SPEED_SLOW = 80
        SPEED_NORMAL = 120
        SPEED_FAST = 200
        SPEED_TURN_SLOW = 100
        SPEED_TURN_NORMAL = 200
        SPEED_TURN_FAST = 220
        
        TURN_STEPS_SMALL = 1
        TURN_STEPS_NORMAL = 2
        TURN_STEPS_LARGE = 4
        TURN_45_DEGREES = 3
        TURN_90_DEGREES = 6
        TURN_180_DEGREES = 12
        
        WALK_STEPS_SHORT = 1
        WALK_STEPS_NORMAL = 2
        WALK_STEPS_LONG = 3
        BACKUP_STEPS = 3
        
        WAKE_WORD = "pidog"
        VOICE_VOLUME_DEFAULT = 70
        LOG_MAX_ENTRIES = 1000
        LOG_STATUS_INTERVAL = 10
        
        ENERGY_DECAY_RATE = 0.001
        ENERGY_INTERACTION_BOOST = 0.05
        ENERGY_REST_RECOVERY = 0.002
        ENERGY_LOW_THRESHOLD = 0.3
        ENERGY_HIGH_THRESHOLD = 0.7

# ============================================================================

from pidog import Pidog
import time
import math
import random
import threading
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

# Dynamic imports based on user configuration
VOICE_AVAILABLE = False
MAPPING_AVAILABLE = False

# Voice recognition imports (install with: pip install speech_recognition pyaudio)
if PiDogConfig.ENABLE_VOICE_COMMANDS:
    try:
        import speech_recognition as sr
        import pyaudio
        VOICE_AVAILABLE = True
        print("🎙️ Voice recognition available")
    except ImportError:
        VOICE_AVAILABLE = False
        print("⚠️ Voice recognition not available. Install: pip install speech_recognition pyaudio")
        print("   Voice commands disabled in configuration")

# SLAM system import
if PiDogConfig.ENABLE_SLAM_MAPPING:
    try:
        from house_mapping import PiDogSLAM, CellType
        from pathfinding import PiDogPathfinder, NavigationController
        if PiDogConfig.ENABLE_SENSOR_FUSION:
            from sensor_fusion_localization import SensorFusionLocalizer, SurfaceType
        MAPPING_AVAILABLE = True
        print("🗺️ House mapping system available")
        print("🧭 Pathfinding system available") 
        if PiDogConfig.ENABLE_SENSOR_FUSION:
            print("📍 Sensor fusion localization available")
    except ImportError as e:
        MAPPING_AVAILABLE = False
        print(f"⚠️ House mapping not available: {e}")
        print("   Install: pip install numpy")

# Create dummy classes for disabled features
if not MAPPING_AVAILABLE or not PiDogConfig.ENABLE_SLAM_MAPPING:
    class PiDogSLAM:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def stop(self): pass
        def update_from_movement(self, *args, **kwargs): pass
        def update_from_scan(self, *args, **kwargs): pass
        def get_navigation_info(self): return {}
    
    class CellType:
        OBSTACLE = "obstacle"
        
    class PiDogPathfinder:
        def __init__(self, *args, **kwargs): pass
        
    class NavigationController:
        def __init__(self, *args, **kwargs): pass
        def get_next_movement_command(self): return None
        def start_exploration_mode(self): return False
        def stop_navigation(self): pass

if not PiDogConfig.ENABLE_SENSOR_FUSION or not MAPPING_AVAILABLE:
    class SensorFusionLocalizer:
        def __init__(self, *args, **kwargs): pass
        def start_localization(self): pass
        def stop_localization(self): pass
        def update_motion(self, *args, **kwargs): pass
        def update_ultrasonic(self, *args, **kwargs): pass
        def get_localization_status(self): return {}
        def calibrate_stationary(self): return True
        
    class SurfaceType:
        UNKNOWN = "unknown"


class EmotionalState(Enum):
    """PiDog emotional states"""
    HAPPY = "happy"
    CALM = "calm"
    ALERT = "alert"
    CONFUSED = "confused"
    TIRED = "tired"
    EXCITED = "excited"


class BehaviorState(Enum):
    """High-level behavior states"""
    IDLE = "idle"
    EXPLORING = "exploring"
    PATROLLING = "patrolling"  # Changed from WANDERING to PATROLLING
    INTERACTING = "interacting"
    AVOIDING = "avoiding"
    RESTING = "resting"
    PLAYING = "playing"


@dataclass
class SensorReading:
    """Consolidated sensor data"""
    distance: float
    touch: str
    sound_detected: bool
    sound_direction: int
    acceleration: Tuple[int, int, int]
    gyroscope: Tuple[int, int, int]
    timestamp: float


@dataclass
class EmotionalProfile:
    """Emotional response configuration"""
    led_color: str
    led_style: str
    sounds: List[str]
    movement_energy: float  # 0.0 to 1.0
    head_responsiveness: float


class AdvancedPiDogAI:
    """Advanced AI behavior system for PiDog with configurable features"""
    
    def __init__(self, config_preset="default"):
        self.dog: Optional[Pidog] = None
        self.current_emotion = EmotionalState.CALM
        self.current_behavior = BehaviorState.IDLE
        self.energy_level = 1.0  # 0.0 to 1.0
        self.attention_target: Optional[int] = None  # Sound direction
        self.obstacle_memory: List[Tuple[float, float]] = []  # Time, distance pairs
        self.interaction_count = 0
        self.last_interaction_time = 0.0
        
        # Load configuration from separate file or fallback
        if CONFIG_AVAILABLE:
            self.config = load_config(config_preset)
            # Validate configuration and show warnings
            warnings = validate_config(self.config)
            if warnings:
                print("⚠️ Configuration warnings:")
                for warning in warnings:
                    print(f"   - {warning}")
        else:
            self.config = PiDogConfig()
        
        # Feature availability flags
        self.voice_enabled = VOICE_AVAILABLE and self.config.ENABLE_VOICE_COMMANDS
        self.slam_enabled = MAPPING_AVAILABLE and self.config.ENABLE_SLAM_MAPPING
        self.sensor_fusion_enabled = self.slam_enabled and self.config.ENABLE_SENSOR_FUSION
        self.intelligent_scanning_enabled = self.config.ENABLE_INTELLIGENT_SCANNING
        self.emotional_system_enabled = self.config.ENABLE_EMOTIONAL_SYSTEM
        self.learning_enabled = self.config.ENABLE_LEARNING_SYSTEM
        self.patrol_logging_enabled = self.config.ENABLE_PATROL_LOGGING
        self.autonomous_nav_enabled = self.slam_enabled and self.config.ENABLE_AUTONOMOUS_NAVIGATION
        
        # Behavior timing
        self.behavior_start_time = time.time()
        self.last_sensor_update = 0.0
        self.last_emotion_update = 0.0
        
        # Learning parameters (configurable)
        if self.learning_enabled:
            self.touch_preferences = {"L": 0.5, "R": 0.5, "LS": 0.5, "RS": 0.5}
            self.learned_behaviors = {}
        else:
            self.touch_preferences = {"L": 0.5, "R": 0.5, "LS": 0.5, "RS": 0.5}
            self.learned_behaviors = {}
        
        # Obstacle avoidance system (simplified if advanced features disabled)
        self.obstacle_scan_data = {
            'forward': 100.0,
            'left': 100.0, 
            'right': 100.0,
            'last_scan_time': 0.0
        }
        self.avoidance_history = []  # List of (timestamp, direction_turned, obstacle_distance)
        self.stuck_counter = 0
        self.last_position_check = time.time()
        self.movement_history = []  # Track if actually moving to detect being stuck
        self.avoidance_strategies = ['turn_smart', 'backup_turn', 'zigzag', 'reverse_escape']
        self.current_strategy_index = 0
        
        # Walking state tracking
        self.is_walking = False
        self.last_walk_command_time = 0.0
        self.scan_interval = self.config.OBSTACLE_SCAN_INTERVAL
        
        # Patrol logging system (configurable)
        if self.patrol_logging_enabled:
            self.patrol_log = []
            self.patrol_start_time = time.time()
            self.patrol_session_id = int(time.time())  # Unique session identifier
            self.log_file_path = f"patrol_log_{self.patrol_session_id}.txt"
        else:
            self.patrol_log = []
            self.patrol_start_time = time.time()
            self.patrol_session_id = None
            self.log_file_path = None
        
        # SLAM mapping system (configurable)
        if self.slam_enabled:
            self.slam_system = PiDogSLAM(f"house_map_{self.patrol_session_id}.pkl")
            self.pathfinder = PiDogPathfinder(self.slam_system.house_map)
            if self.autonomous_nav_enabled:
                self.nav_controller = NavigationController(self.pathfinder)
            else:
                self.nav_controller = NavigationController(None)  # Disabled navigation
                
            if self.sensor_fusion_enabled:
                self.sensor_localizer = SensorFusionLocalizer(self.slam_system.house_map)
            else:
                self.sensor_localizer = None
                
            print("🗺️ SLAM system initialized")
            if self.autonomous_nav_enabled:
                print("🧭 Pathfinding system initialized")
            if self.sensor_fusion_enabled:
                print("📍 Sensor fusion localizer initialized")
        else:
            self.slam_system = None
            self.pathfinder = None
            self.nav_controller = None
            self.sensor_localizer = None
            print("🔇 Advanced features disabled - using simple obstacle avoidance")
        
        # Thread control
        self.running = False
        self.sensor_thread = None
        self.voice_thread = None
        self.scanning_thread = None
        
        # Voice command system (configurable)
        self.listening_for_wake_word = True
        self.wake_word = self.config.WAKE_WORD
        self.last_voice_command_time = 0.0
        
        # Voice commands dictionary (configurable)
        self.voice_commands = {
            # Basic movement commands
            "sit": lambda: self._voice_sit(),
            "stand": lambda: self._voice_stand(), 
            "lie down": lambda: self._voice_lie(),
            "walk": lambda: self._voice_walk(),
            "turn left": lambda: self._voice_turn_left(),
            "turn right": lambda: self._voice_turn_right(),
            "stop": lambda: self.dog.body_stop(),
            
            # Action commands  
            "wag tail": lambda: self.dog.do_action("wag_tail", step_count=5, speed=self.config.SPEED_FAST),
            "shake head": lambda: self.dog.do_action("shake_head", step_count=3, speed=self.config.SPEED_NORMAL),
            "nod": lambda: self.dog.do_action("head_up_down", step_count=3, speed=self.config.SPEED_SLOW),
            "stretch": lambda: self.dog.do_action("stretch", speed=self.config.SPEED_SLOW),
            
            # Behavior commands
            "play": lambda: self.set_behavior(BehaviorState.PLAYING),
            "explore": lambda: self.set_behavior(BehaviorState.EXPLORING),
            "patrol": lambda: self.set_behavior(BehaviorState.PATROLLING),
            "rest": lambda: self.set_behavior(BehaviorState.RESTING),
            
            # Response commands
            "good dog": lambda: self._praise_response(),
            "bad dog": lambda: self._scold_response(),
            
            # Status and configuration
            "status": lambda: self.print_status(),
            "show config": lambda: self.print_configuration(),
            "simple mode": lambda: self._toggle_simple_mode(),
            "advanced mode": lambda: self._toggle_advanced_mode(),
            
            # Configuration presets (if available)
            "load simple config": lambda: self._load_config_preset("simple"),
            "load advanced config": lambda: self._load_config_preset("advanced"),
            "load indoor config": lambda: self._load_config_preset("indoor"),
            "load explorer config": lambda: self._load_config_preset("explorer"),
            
            # Speed and calibration tests
            "test walk slow": lambda: self._test_walk_speed("slow"),
            "test walk normal": lambda: self._test_walk_speed("normal"),
            "test walk fast": lambda: self._test_walk_speed("fast"),
            "test turn 45": lambda: self._test_turn_angle(45),
            "test turn 90": lambda: self._test_turn_angle(90),
            "test turn 180": lambda: self._test_turn_angle(180),
        }
        
        # Add advanced commands if features are enabled
        if self.slam_enabled:
            self.voice_commands.update({
                "calibrate": lambda: self.calibrate_position("wall_follow"),
                "find corner": lambda: self.calibrate_position("corner_seek"),
                "show map": lambda: self._show_map_visualization(),
                "calibrate sensors": lambda: self._calibrate_sensors()
            })
            
        if self.autonomous_nav_enabled:
            self.voice_commands.update({
                "start exploring": lambda: self._start_autonomous_exploration(),
                "stop navigation": lambda: self._stop_navigation(),
                "go to room": lambda: self._navigate_to_nearest_room()
            })
        
        # Define emotional profiles
        self.emotion_profiles = {
            EmotionalState.HAPPY: EmotionalProfile(
                led_color="green", led_style="breath", 
                sounds=["pant", "woohoo"], movement_energy=0.8, head_responsiveness=0.9
            ),
            EmotionalState.CALM: EmotionalProfile(
                led_color="blue", led_style="breath",
                sounds=["pant"], movement_energy=0.5, head_responsiveness=0.6
            ),
            EmotionalState.ALERT: EmotionalProfile(
                led_color="orange", led_style="boom",
                sounds=["single_bark_1"], movement_energy=0.9, head_responsiveness=1.0
            ),
            EmotionalState.CONFUSED: EmotionalProfile(
                led_color="purple", led_style="breath",
                sounds=["confused_1", "confused_2"], movement_energy=0.3, head_responsiveness=0.4
            ),
            EmotionalState.TIRED: EmotionalProfile(
                led_color="white", led_style="breath",
                sounds=["snoring"], movement_energy=0.2, head_responsiveness=0.3
            ),
            EmotionalState.EXCITED: EmotionalProfile(
                led_color="yellow", led_style="boom",
                sounds=["woohoo", "single_bark_2"], movement_energy=1.0, head_responsiveness=1.0
            )
        }
    
    def initialize(self) -> bool:
        """Initialize PiDog with error handling"""
        try:
            print("🤖 Initializing Advanced PiDog AI...")
            self.dog = Pidog()
            
            # Startup sequence
            self.dog.do_action("stand", speed=60)
            self.dog.wait_all_done()
            
            # Set initial emotional state
            self.set_emotion(EmotionalState.CALM)
            
            # Initialize patrol log
            self._log_patrol_event("SYSTEM", "PiDog AI system initialized", {
                "energy_level": self.energy_level,
                "emotional_state": self.current_emotion.value,
                "behavior_state": self.current_behavior.value,
                "slam_enabled": self.slam_enabled
            })
            
            # Start SLAM system
            if self.slam_system:
                self.slam_system.start()
                self._log_patrol_event("SLAM", "House mapping system started")
                
            # Start sensor fusion localization
            if self.sensor_localizer:
                self.sensor_localizer.start_localization()
                self._log_patrol_event("LOCALIZATION", "Sensor fusion localization started")
            
            print("✓ PiDog AI initialized successfully")
            return True
            
        except Exception as e:
            print(f"✗ Initialization failed: {e}")
            self._log_patrol_event("ERROR", f"Initialization failed: {e}")
            return False
    
    def start_ai_system(self):
        """Start the AI behavior system"""
        if not self.initialize():
            return False
            
        self.running = True
        
        # Start sensor monitoring thread
        self.sensor_thread = threading.Thread(target=self._sensor_monitor_loop, daemon=True)
        self.sensor_thread.start()
        
        # Start intelligent scanning thread
        print("🔍 Starting intelligent obstacle scanning system...")
        self.scanning_thread = threading.Thread(target=self._intelligent_scanning_loop, daemon=True)
        self.scanning_thread.start()
        
        # Start voice recognition thread if available
        if self.voice_enabled:
            print("🎙️ Starting voice recognition system...")
            print(f"💡 Say '{self.wake_word}' followed by a command")
            self.voice_thread = threading.Thread(target=self._voice_recognition_loop, daemon=True)
            self.voice_thread.start()
        else:
            print("🔇 Voice recognition disabled (missing dependencies)")
        
        try:
            print("🧠 AI system active - Press Ctrl+C to stop")
            print("💡 Try touching, making sounds, or putting objects nearby...")
            
            # Main AI loop
            while self.running:
                self._ai_behavior_loop()
                time.sleep(0.1)  # 10Hz main loop
                
        except KeyboardInterrupt:
            print("\n🛑 AI system stopping...")
        finally:
            self._shutdown()
            
        return True
    
    def _log_patrol_event(self, event_type: str, description: str, data: dict = None):
        """Log patrol events with timestamp and details (if logging enabled)"""
        if not self.patrol_logging_enabled:
            return  # Skip logging if disabled
            
        timestamp = time.time()
        elapsed = timestamp - self.patrol_start_time
        
        log_entry = {
            "session_id": self.patrol_session_id,
            "timestamp": timestamp,
            "elapsed_time": elapsed,
            "event_type": event_type,
            "description": description,
            "behavior_state": self.current_behavior.value,
            "emotional_state": self.current_emotion.value if self.emotional_system_enabled else "disabled",
            "energy_level": round(self.energy_level, 3),
            "scan_data": {
                "forward": round(self.obstacle_scan_data['forward'], 1),
                "left": round(self.obstacle_scan_data['left'], 1), 
                "right": round(self.obstacle_scan_data['right'], 1)
            },
            "additional_data": data or {}
        }
        
        # Add to memory log
        self.patrol_log.append(log_entry)
        
        # Write to file immediately for persistence (if file path exists)
        if self.log_file_path:
            try:
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    log_line = f"[{time.strftime('%H:%M:%S', time.localtime(timestamp))}] "
                    log_line += f"({elapsed:6.1f}s) {event_type:12} | {description}"
                    if data:
                        log_line += f" | Data: {data}"
                    log_line += f" | State: {self.current_behavior.value}/{self.current_emotion.value if self.emotional_system_enabled else 'disabled'}"
                    log_line += f" | Energy: {self.energy_level:.2f}"
                    log_line += f" | Scan: F{self.obstacle_scan_data['forward']:.0f} L{self.obstacle_scan_data['left']:.0f} R{self.obstacle_scan_data['right']:.0f}"
                    f.write(log_line + '\n')
            except Exception as e:
                print(f"⚠️ Patrol log write error: {e}")
        
        # Keep log size manageable (configurable limit)
        if len(self.patrol_log) > self.config.LOG_MAX_ENTRIES:
            self.patrol_log = self.patrol_log[-self.config.LOG_MAX_ENTRIES:]
    
    def _sensor_monitor_loop(self):
        """Background sensor monitoring (runs at 20Hz)"""
        while self.running:
            try:
                # Read all sensors
                reading = SensorReading(
                    distance=self.dog.ultrasonic.read_distance(),
                    touch=self.dog.dual_touch.read(),
                    sound_detected=self.dog.ears.isdetected(),
                    sound_direction=self.dog.ears.read() if self.dog.ears.isdetected() else -1,
                    acceleration=self.dog.accData,
                    gyroscope=self.dog.gyroData,
                    timestamp=time.time()
                )
                
                # Process immediate reactions
                self._process_sensor_data(reading)
                
                time.sleep(0.05)  # 20Hz sensor loop
                
            except Exception as e:
                print(f"⚠️ Sensor error: {e}")
                time.sleep(0.1)
    
    def _intelligent_scanning_loop(self):
        """Advanced obstacle scanning system that runs during movement"""
        while self.running:
            try:
                current_time = time.time()
                
                # Check if we're in a walking behavior and need to scan
                if self._should_perform_scan():
                    scan_data = self._perform_three_way_scan()
                    self.obstacle_scan_data.update(scan_data)
                    self.obstacle_scan_data['last_scan_time'] = current_time
                    
                    # Analyze scan data for immediate threats
                    self._analyze_scan_data(scan_data)
                    
                # Check for stuck condition
                self._check_if_stuck()
                
                time.sleep(0.2)  # 5Hz scanning loop
                
            except Exception as e:
                print(f"⚠️ Scanning error: {e}")
                time.sleep(0.5)
    
    def _should_perform_scan(self):
        """Determine if we should perform a scan based on current activity"""
        current_time = time.time()
        
        # Always scan if we haven't scanned recently and we're moving
        if current_time - self.obstacle_scan_data['last_scan_time'] > self.scan_interval:
            # Check if we're in movement behaviors
            if (self.current_behavior in [BehaviorState.PATROLLING, BehaviorState.EXPLORING] or
                self.is_walking or 
                current_time - self.last_walk_command_time < 3.0):
                return True
                
        return False
    
    def _perform_three_way_scan(self):
        """Perform intelligent 3-directional ultrasonic scan"""
        print("🔍 Performing 3-way obstacle scan...")
        self._log_patrol_event("SCAN_START", "Beginning 3-way ultrasonic scan")
        
        scan_results = {}
        head_positions = [
            (0, "forward"),      # Center
            (-45, "right"),      # Right (negative yaw = right)  
            (45, "left")         # Left (positive yaw = left)
        ]
        
        for yaw_angle, direction in head_positions:
            # Move head to scan position
            self.dog.head_move([[yaw_angle, 0, 0]], speed=90)
            time.sleep(0.3)  # Allow head to reach position
            
            # Take multiple readings for accuracy
            distances = []
            for _ in range(3):
                distance = self.dog.ultrasonic.read_distance()
                if distance > 0:  # Valid reading
                    distances.append(distance)
                time.sleep(0.1)
            
            # Use median distance to avoid outliers
            if distances:
                scan_results[direction] = sorted(distances)[len(distances)//2]
                print(f"  📐 {direction}: {scan_results[direction]:.1f}cm")
            else:
                scan_results[direction] = 200.0  # Assume clear if no valid readings
                print(f"  📐 {direction}: No obstacle (>200cm)")
        
        # Return head to center
        self.dog.head_move([[0, 0, 0]], speed=90)
        
        # Log scan results
        self._log_patrol_event("SCAN_COMPLETE", "3-way scan completed", {
            "scan_results": scan_results,
            "threats_detected": [direction for direction, distance in scan_results.items() if distance < 40]
        })
        
        # Update SLAM system with scan data
        if self.slam_system:
            self.slam_system.update_from_scan(scan_results)
            
            # Update sensor fusion with ultrasonic data
            if self.sensor_localizer:
                for direction, distance in scan_results.items():
                    if distance > 0:
                        angle_mapping = {'forward': 0.0, 'left': 45.0, 'right': -45.0}
                        if direction in angle_mapping:
                            self.sensor_localizer.update_ultrasonic(distance, angle_mapping[direction])
            
            # Get navigation suggestions from SLAM
            nav_info = self.slam_system.get_navigation_info()
            if nav_info:
                self._log_patrol_event("SLAM_NAV", "Navigation info updated", {
                    "current_room": nav_info.get("room_info"),
                    "nearby_landmarks": len(nav_info.get("nearby_landmarks", [])),
                    "suggested_direction": nav_info.get("suggested_direction", {}).get("suggested_direction"),
                    "map_confidence": nav_info.get("suggested_direction", {}).get("confidence", 0.0)
                })
        
        return scan_results
    
    def _analyze_scan_data(self, scan_data):
        """Analyze scan data and trigger avoidance if needed"""
        forward_distance = scan_data.get('forward', 200.0)
        left_distance = scan_data.get('left', 200.0)
        right_distance = scan_data.get('right', 200.0)
        
        # Use configurable obstacle thresholds
        immediate_threat = self.config.OBSTACLE_IMMEDIATE_THREAT
        approaching_threat = self.config.OBSTACLE_APPROACHING_THREAT
        
        if forward_distance < immediate_threat:
            print(f"🚨 IMMEDIATE THREAT: Obstacle at {forward_distance:.1f}cm!")
            self._log_patrol_event("THREAT_IMMEDIATE", f"Immediate threat detected at {forward_distance:.1f}cm", {
                "forward_distance": forward_distance,
                "left_distance": left_distance,
                "right_distance": right_distance,
                "threat_level": "IMMEDIATE"
            })
            self._execute_intelligent_avoidance(scan_data)
            
        elif forward_distance < approaching_threat:
            print(f"⚠️ Approaching obstacle: {forward_distance:.1f}cm - preparing avoidance")
            self._log_patrol_event("THREAT_APPROACHING", f"Approaching obstacle at {forward_distance:.1f}cm", {
                "forward_distance": forward_distance,
                "left_distance": left_distance,
                "right_distance": right_distance,
                "threat_level": "APPROACHING"
            })
            # Slow down current movement but don't stop yet
            if self.is_walking:
                self._adjust_walking_speed(0.7)  # Reduce to 70% speed
    
    def _execute_intelligent_avoidance(self, scan_data):
        """Execute intelligent avoidance based on scan data and history"""
        current_time = time.time()
        forward_dist = scan_data.get('forward', 0)
        left_dist = scan_data.get('left', 0)  
        right_dist = scan_data.get('right', 0)
        
        # Check avoidance history for stuck patterns
        recent_avoidances = [a for a in self.avoidance_history 
                           if current_time - a[0] < 10.0]  # Last 10 seconds
        
        # Determine if we're stuck (too many recent avoidances)
        if len(recent_avoidances) >= 3:
            print(f"🔄 Stuck pattern detected! Trying advanced strategy...")
            self._log_patrol_event("STUCK_PATTERN", f"Stuck pattern detected - {len(recent_avoidances)} recent avoidances", {
                "recent_avoidances": len(recent_avoidances),
                "avoidance_history": [(a[1], a[2]) for a in recent_avoidances]  # direction, distance pairs
            })
            self._execute_advanced_avoidance_strategy()
        else:
            # Normal intelligent avoidance
            self._log_patrol_event("AVOIDANCE_START", "Executing smart turn avoidance", {
                "left_distance": left_dist,
                "right_distance": right_dist,
                "forward_distance": forward_dist
            })
            self._execute_smart_turn_avoidance(left_dist, right_dist)
            
        # Record this avoidance in history
        best_direction = "left" if left_dist > right_dist else "right"
        self.avoidance_history.append((current_time, best_direction, forward_dist))
        
        # Clean old history (keep last 30 seconds)
        self.avoidance_history = [a for a in self.avoidance_history 
                                 if current_time - a[0] < 30.0]
    
    def _execute_smart_turn_avoidance(self, left_dist, right_dist):
        """Turn toward the most open direction"""
        print(f"🎯 Smart avoidance: Left={left_dist:.1f}cm, Right={right_dist:.1f}cm")
        
        # Determine best direction with configurable parameters
        clearance_threshold = 10  # Minimum difference for "significantly more open"
        
        if left_dist > right_dist + clearance_threshold:  # Left is significantly more open
            turn_direction = "turn_left"
            turn_amount = self.config.TURN_STEPS_NORMAL if left_dist > 50 else self.config.TURN_STEPS_SMALL
            print(f"   ↰ Turning LEFT ({turn_amount} steps)")
        elif right_dist > left_dist + clearance_threshold:  # Right is significantly more open  
            turn_direction = "turn_right"
            turn_amount = self.config.TURN_STEPS_NORMAL if right_dist > 50 else self.config.TURN_STEPS_SMALL
            print(f"   ↱ Turning RIGHT ({turn_amount} steps)")
        else:
            # Similar distances - choose randomly but prefer less recent direction
            recent_left_turns = sum(1 for _, direction, _ in self.avoidance_history[-3:] 
                                  if direction == "left")
            recent_right_turns = sum(1 for _, direction, _ in self.avoidance_history[-3:] 
                                   if direction == "right")
            
            if recent_left_turns > recent_right_turns:
                turn_direction = "turn_right"
                turn_amount = self.config.TURN_STEPS_NORMAL
                print(f"   ↱ Avoiding LEFT pattern - turning RIGHT")
            else:
                turn_direction = "turn_left" 
                turn_amount = self.config.TURN_STEPS_NORMAL
                print(f"   ↰ Avoiding RIGHT pattern - turning LEFT")
        
        # Execute the turn with appropriate speed based on energy/activity level
        turn_speed = self._get_appropriate_turn_speed()
        self.dog.body_stop()  # Stop current movement
        self.dog.do_action(turn_direction, step_count=turn_amount, speed=turn_speed)
        self.dog.wait_all_done()
        
        # Note: Movement tracking now handled by sensor fusion localization
    
    def _execute_advanced_avoidance_strategy(self):
        """Execute advanced avoidance strategies when stuck"""
        strategy = self.avoidance_strategies[self.current_strategy_index]
        print(f"🚀 Executing strategy: {strategy}")
        
        if strategy == 'backup_turn':
            # Back up then turn around
            print("   ⏪ Backing up and turning around...")
            self.dog.body_stop()
            self.dog.do_action("backward", step_count=self.config.BACKUP_STEPS, speed=self.config.SPEED_EMERGENCY)
            self.dog.wait_all_done()
            turn_dir = "turn_left" if random.random() > 0.5 else "turn_right"
            self.dog.do_action(turn_dir, step_count=self.config.TURN_STEPS_LARGE, speed=self.config.SPEED_TURN_NORMAL)  # 180 degree turn
            
        elif strategy == 'zigzag':
            # Zigzag pattern to find opening
            print("   〰️ Executing zigzag escape pattern...")
            directions = ["turn_left", "turn_right", "turn_left", "turn_right"]
            for direction in directions:
                self.dog.do_action(direction, step_count=self.config.TURN_STEPS_SMALL, speed=self.config.SPEED_FAST)
                self.dog.wait_all_done()
                self.dog.do_action("forward", step_count=self.config.WALK_STEPS_SHORT, speed=self.config.SPEED_EMERGENCY)
                self.dog.wait_all_done()
                
        elif strategy == 'reverse_escape':
            # Back up significantly and try different approach
            print("   🔄 Full reverse escape maneuver...")
            self.dog.body_stop()
            self.dog.do_action("backward", step_count=self.config.BACKUP_STEPS + 2, speed=self.config.SPEED_NORMAL)
            self.dog.wait_all_done()
            # Random large turn
            turn_amount = random.randint(self.config.TURN_STEPS_NORMAL, self.config.TURN_STEPS_LARGE + 2)
            turn_dir = "turn_left" if random.random() > 0.5 else "turn_right"
            self.dog.do_action(turn_dir, step_count=turn_amount, speed=self.config.SPEED_TURN_FAST)
            
        else:  # 'turn_smart' - default enhanced smart turn
            print("   🎯 Enhanced smart turning...")
            # Perform new scan after backing up slightly
            self.dog.do_action("backward", step_count=1, speed=50)
            self.dog.wait_all_done()
            new_scan = self._perform_three_way_scan()
            self._execute_smart_turn_avoidance(new_scan['left'], new_scan['right'])
        
        # Cycle to next strategy for future use
        self.current_strategy_index = (self.current_strategy_index + 1) % len(self.avoidance_strategies)
        
        # Clear recent history after advanced strategy
        self.avoidance_history = []
    
    def _check_if_stuck(self):
        """Check if PiDog is stuck by monitoring movement progress"""
        current_time = time.time()
        
        # Record current "position" (using IMU data as proxy for movement)
        ax, ay, az = self.dog.accData
        movement_magnitude = abs(ax) + abs(ay) + abs(az)
        
        self.movement_history.append((current_time, movement_magnitude))
        
        # Keep only last 5 seconds of movement data
        self.movement_history = [(t, m) for t, m in self.movement_history 
                               if current_time - t < 5.0]
        
        # Check if we should be moving but aren't
        if (self.current_behavior in [BehaviorState.WANDERING, BehaviorState.EXPLORING] and
            len(self.movement_history) > 10):
            
            recent_movement = [m for t, m in self.movement_history[-10:]]
            avg_movement = sum(recent_movement) / len(recent_movement)
            
            # If very little movement detected during active behaviors
            if avg_movement < 1000:  # Threshold for "stuck" condition
                self.stuck_counter += 1
                if self.stuck_counter > 5:  # Stuck for several checks
                    print("🆘 STUCK CONDITION DETECTED - Executing emergency escape!")
                    self._execute_advanced_avoidance_strategy()
                    self.stuck_counter = 0
            else:
                self.stuck_counter = 0  # Reset if moving normally
    
    def _adjust_walking_speed(self, speed_factor):
        """Adjust current walking speed (placeholder for implementation)"""
        # This would require more complex action queue management
        # For now, just note the speed adjustment
        print(f"🐌 Reducing movement speed to {int(speed_factor*100)}%")
    
    def _get_appropriate_turn_speed(self):
        """Get appropriate turn speed based on current energy and activity level"""
        # Determine current activity level
        if self.energy_level > 0.7:
            return self.config.SPEED_TURN_FAST
        elif self.energy_level > 0.4:
            return self.config.SPEED_TURN_NORMAL
        else:
            return self.config.SPEED_TURN_SLOW
    
    def _get_appropriate_walk_speed(self):
        """Get appropriate walk speed based on current energy level"""
        if self.energy_level > 0.7:
            return self.config.SPEED_FAST
        elif self.energy_level > 0.4:
            return self.config.SPEED_NORMAL
        else:
            return self.config.SPEED_SLOW
    
    def _process_sensor_data(self, reading: SensorReading):
        """Process sensor data and trigger immediate responses"""
        current_time = time.time()
        
        # Handle touch interactions (highest priority)
        if reading.touch != "N":
            self._handle_touch_interaction(reading.touch, current_time)
            
        # Handle immediate obstacle detection (emergency only)
        # The intelligent scanning system handles most obstacle avoidance
        if reading.distance > 0 and reading.distance < 15:  # Only emergency stops
            self._handle_emergency_obstacle(reading.distance, current_time)
            
        # Handle sound direction
        if reading.sound_detected and reading.sound_direction >= 0:
            self._handle_sound_attention(reading.sound_direction, current_time)
            
        # Update energy based on activity
        self._update_energy_level(reading, current_time)
        
        # Update SLAM position tracking with IMU data
        if self.slam_system and current_time - self.last_sensor_update > 0.1:  # 10Hz update
            self._update_slam_with_imu(reading)
            self.last_sensor_update = current_time
    
    def _ai_behavior_loop(self):
        """Main AI decision-making loop"""
        current_time = time.time()
        
        # Update emotional state periodically
        if current_time - self.last_emotion_update > 2.0:
            self._update_emotional_state()
            self.last_emotion_update = current_time
        
        # State machine behavior
        if self.current_behavior == BehaviorState.IDLE:
            self._idle_behavior()
        elif self.current_behavior == BehaviorState.EXPLORING:
            self._exploring_behavior()
        elif self.current_behavior == BehaviorState.PATROLLING:
            self._patrolling_behavior()  # ENHANCED: Intelligent patrol with logging
        elif self.current_behavior == BehaviorState.INTERACTING:
            self._interacting_behavior()
        elif self.current_behavior == BehaviorState.RESTING:
            self._resting_behavior()
        elif self.current_behavior == BehaviorState.PLAYING:
            self._playing_behavior()
            
        # Check for behavior state transitions
        self._evaluate_behavior_transitions(current_time)
    
    def _handle_touch_interaction(self, touch_type: str, timestamp: float):
        """Handle touch with learning and emotional response"""
        print(f"👋 Touch detected: {touch_type}")
        
        # Update interaction statistics
        self.interaction_count += 1
        self.last_interaction_time = timestamp
        
        # Log touch interaction
        self._log_patrol_event("TOUCH_INTERACTION", f"Touch detected: {touch_type}", {
            "touch_type": touch_type,
            "interaction_count": self.interaction_count,
            "touch_preferences": dict(self.touch_preferences)
        })
        
        # Learn touch preferences
        if touch_type in self.touch_preferences:
            self.touch_preferences[touch_type] += 0.1
            
        # Emotional response based on preference
        preference = self.touch_preferences.get(touch_type, 0.5)
        
        if preference > 0.7:
            self.set_emotion(EmotionalState.HAPPY)
            self.dog.speak("pant", volume=70)
        elif preference > 0.3:
            self.set_emotion(EmotionalState.CALM)
        else:
            self.set_emotion(EmotionalState.CONFUSED)
            
        # Movement response with energy consideration
        energy_factor = self.energy_level * preference
        
        if touch_type in ["LS", "RS"]:  # Swipes
            direction = "turn_right" if touch_type == "LS" else "turn_left"
            speed = int(50 + energy_factor * 40)
            self.dog.do_action(direction, step_count=1, speed=speed)
            
        elif energy_factor > 0.5:
            # High energy response
            self.dog.do_action("wag_tail", step_count=int(5 + energy_factor * 10), speed=90)
            
        # Switch to interaction behavior
        self.set_behavior(BehaviorState.INTERACTING)
    
    def _handle_emergency_obstacle(self, distance: float, timestamp: float):
        """Handle emergency obstacle detection (very close obstacles)"""
        print(f"🚨 EMERGENCY: Obstacle at {distance:.1f}cm - immediate stop!")
        
        # Immediate stop
        self.dog.body_stop()
        
        # Store in obstacle memory
        self.obstacle_memory.append((timestamp, distance))
        
        # Clean old memories (keep last 10 minutes)
        self.obstacle_memory = [(t, d) for t, d in self.obstacle_memory 
                               if timestamp - t < 600]
        
        # Emotional response based on obstacle frequency
        recent_obstacles = len([d for t, d in self.obstacle_memory 
                              if timestamp - t < 30])  # Last 30 seconds
        
        if recent_obstacles > 5:  # More tolerant since we now have smart avoidance
            self.set_emotion(EmotionalState.CONFUSED)
            self.dog.speak("confused_2", volume=60)
            # Trigger advanced avoidance if too many emergencies
            self._execute_advanced_avoidance_strategy()
        else:
            self.set_emotion(EmotionalState.ALERT)
            self.dog.speak("single_bark_1", volume=70)
            
        # Let the intelligent scanning system handle the avoidance
        # Just switch to avoiding state temporarily
        self.set_behavior(BehaviorState.AVOIDING)
    
    def _handle_sound_attention(self, direction: int, timestamp: float):
        """ENHANCED: Advanced sound tracking with head movement and body turning"""
        print(f"👂 Sound from {direction}° - investigating!")
        
        self.attention_target = direction
        self.set_emotion(EmotionalState.ALERT)
        
        # Log sound detection
        self._log_patrol_event("SOUND_DETECTED", f"Sound detected from {direction}°", {
            "sound_direction": direction,
            "previous_attention": self.attention_target,
            "response_planned": "head_and_body_turn" if abs(direction) > 45 else "head_turn_only"
        })
        
        # Calculate head movement
        profile = self.emotion_profiles[self.current_emotion]
        responsiveness = profile.head_responsiveness * self.energy_level
        
        # Convert sound direction to head yaw (more responsive)
        if direction > 180:
            yaw = max(-80, (direction - 360) / 2.5)  # Increased range and sensitivity
        else:
            yaw = min(80, direction / 2.5)
            
        yaw *= responsiveness
        
        # ENHANCED: Turn head first, then body if sound is far to the side
        self.dog.head_move([[int(yaw), 0, 0]], speed=int(70 + responsiveness * 30))
        
        # If sound is significantly to the side, turn body to face it
        if abs(yaw) > 45 and self.energy_level > 0.4:
            print(f"🔄 Turning body to face sound source")
            if yaw > 0:  # Sound to the left
                self.dog.do_action("turn_left", step_count=1, speed=70)
            else:  # Sound to the right  
                self.dog.do_action("turn_right", step_count=1, speed=70)
            
            # Reset head to center after body turn
            time.sleep(1)  # Wait for body turn
            self.dog.head_move([[0, 0, 0]], speed=60)
        
        # ENHANCED: More varied vocal responses
        if self.current_emotion == EmotionalState.EXCITED:
            sounds = ["woohoo", "single_bark_2"]
            self.dog.speak(random.choice(sounds), volume=80)
        elif self.current_emotion == EmotionalState.ALERT:
            sounds = ["single_bark_1", "pant"]
            self.dog.speak(random.choice(sounds), volume=70)
        elif self.current_emotion == EmotionalState.CONFUSED:
            self.dog.speak("confused_1", volume=60)
            
        # Switch to investigating behavior
        if self.current_behavior in [BehaviorState.IDLE, BehaviorState.PATROLLING]:
            self.set_behavior(BehaviorState.EXPLORING)
    
    def _update_energy_level(self, reading: SensorReading, timestamp: float):
        """Update energy level based on activity and time"""
        # Energy decreases over time
        time_factor = 0.001  # Slow decay
        self.energy_level = max(0.0, self.energy_level - time_factor)
        
        # Energy increases with interaction
        if reading.touch != "N" or reading.sound_detected:
            self.energy_level = min(1.0, self.energy_level + 0.05)
            
        # Energy affected by movement (gyroscope activity)
        gx, gy, gz = reading.gyroscope
        movement_activity = (abs(gx) + abs(gy) + abs(gz)) / 3000.0
        if movement_activity > 0.1:
            self.energy_level = max(0.1, self.energy_level - 0.02)
    
    def _update_emotional_state(self):
        """Update emotional state based on current conditions"""
        current_time = time.time()
        
        # Base emotion on energy level
        if self.energy_level > 0.8:
            base_emotion = EmotionalState.EXCITED
        elif self.energy_level > 0.6:
            base_emotion = EmotionalState.HAPPY
        elif self.energy_level > 0.4:
            base_emotion = EmotionalState.CALM
        elif self.energy_level > 0.2:
            base_emotion = EmotionalState.CONFUSED
        else:
            base_emotion = EmotionalState.TIRED
            
        # Modify based on recent interactions
        recent_interactions = current_time - self.last_interaction_time < 30
        if recent_interactions and base_emotion != EmotionalState.TIRED:
            if self.interaction_count > 10:
                base_emotion = EmotionalState.EXCITED
            elif self.interaction_count > 5:
                base_emotion = EmotionalState.HAPPY
                
        # Apply emotional state if changed
        if base_emotion != self.current_emotion:
            self.set_emotion(base_emotion)
    
    def _evaluate_behavior_transitions(self, current_time: float):
        """Evaluate and handle behavior state transitions"""
        time_in_state = current_time - self.behavior_start_time
        
        # ENHANCED: Transition logic with patrol behavior
        if self.current_behavior == BehaviorState.IDLE:
            if self.energy_level > 0.7 and time_in_state > 3:
                # Choose between exploring and patrolling based on energy
                if self.energy_level > 0.8 and random.random() < 0.6:
                    self.set_behavior(BehaviorState.PATROLLING)  # High energy = patrol
                else:
                    self.set_behavior(BehaviorState.EXPLORING)
            elif self.energy_level < 0.3:
                self.set_behavior(BehaviorState.RESTING)
                
        elif self.current_behavior == BehaviorState.EXPLORING:
            if self.interaction_count > 0 and time_in_state > 3:
                self.set_behavior(BehaviorState.INTERACTING)
            elif self.energy_level > 0.7 and time_in_state > 10:
                self.set_behavior(BehaviorState.PATROLLING)  # Transition to patrol
            elif self.energy_level < 0.4:
                self.set_behavior(BehaviorState.IDLE)
            elif time_in_state > 15:
                self.set_behavior(BehaviorState.IDLE)
                
        elif self.current_behavior == BehaviorState.PATROLLING:
            if self.interaction_count > 0 and time_in_state > 5:
                self.set_behavior(BehaviorState.INTERACTING)
            elif self.energy_level < 0.4:
                self.set_behavior(BehaviorState.IDLE)
            elif time_in_state > 60:  # Patrol for max 60 seconds before rest
                self.set_behavior(BehaviorState.IDLE)
                
        elif self.current_behavior == BehaviorState.INTERACTING:
            if current_time - self.last_interaction_time > 10:
                if self.energy_level > 0.6:
                    self.set_behavior(BehaviorState.PLAYING)
                else:
                    self.set_behavior(BehaviorState.IDLE)
                    
        elif self.current_behavior == BehaviorState.AVOIDING:
            if time_in_state > 3:  # Avoid for 3 seconds then return
                self.set_behavior(BehaviorState.IDLE)
                
        elif self.current_behavior == BehaviorState.RESTING:
            if self.energy_level > 0.5 or time_in_state > 20:
                self.set_behavior(BehaviorState.IDLE)
                
        elif self.current_behavior == BehaviorState.PLAYING:
            if self.energy_level < 0.4 or time_in_state > 30:
                self.set_behavior(BehaviorState.IDLE)
    
    def _idle_behavior(self):
        """Idle behavior - occasional random movements"""
        if random.random() < 0.01:  # 1% chance per cycle
            actions = ["tilting_head", "head_up_down"]
            action = random.choice(actions)
            speed = int(30 + self.energy_level * 40)
            self.dog.do_action(action, step_count=1, speed=speed)
    
    def _exploring_behavior(self):
        """Exploring behavior - active movement and head scanning"""
        if random.random() < 0.05:  # 5% chance per cycle
            # Random head scanning
            yaw = random.randint(-45, 45)
            self.dog.head_move([[yaw, 0, 0]], speed=70)
            
        if random.random() < 0.02:  # 2% chance per cycle
            # Random short movements
            actions = ["forward", "turn_left", "turn_right"]
            action = random.choice(actions)
            speed = int(50 + self.energy_level * 30)
            self.dog.do_action(action, step_count=1, speed=speed)
    
    def _interacting_behavior(self):
        """Interactive behavior - responsive and engaging"""
        if random.random() < 0.03:  # 3% chance per cycle
            # Engaging movements
            self.dog.do_action("wag_tail", step_count=3, speed=90)
            
        # Look at attention target if available
        if self.attention_target is not None:
            if random.random() < 0.1:  # 10% chance to look at target
                yaw = max(-45, min(45, (self.attention_target - 180) / 4))
                self.dog.head_move([[yaw, 0, 0]], speed=80)
    
    def _resting_behavior(self):
        """Resting behavior - minimal movement, sleepy actions"""
        if random.random() < 0.005:  # 0.5% chance per cycle
            self.dog.do_action("doze_off", speed=20)
            
        # Gradually recover energy while resting
        self.energy_level = min(1.0, self.energy_level + 0.002)
    
    def _patrolling_behavior(self):
        """ENHANCED: Intelligent patrol with predictive obstacle avoidance and comprehensive logging"""
        current_time = time.time()
        
        # Mark that we're walking for the scanning system
        self.is_walking = True
        self.last_walk_command_time = current_time
        
        # Log patrol status every 10 seconds
        time_in_patrol = current_time - self.behavior_start_time
        if int(time_in_patrol) % 10 == 0 and int(time_in_patrol * 10) % 10 == 0:  # Every 10 seconds
            self._log_patrol_event("PATROL_STATUS", f"Patrol ongoing for {time_in_patrol:.0f}s", {
                "patrol_duration": time_in_patrol,
                "distance_covered_estimate": int(time_in_patrol * 2),  # Rough estimate
                "interactions_during_patrol": self.interaction_count
            })
        
        # Check for autonomous navigation commands
        nav_command = None
        if self.nav_controller:
            nav_command = self.nav_controller.get_next_movement_command()
            
        if nav_command:
            # Execute navigation command
            action = nav_command["action"]
            step_count = nav_command.get("step_count", 1)
            
            print(f"🧭 Navigation command: {action} ({step_count} steps)")
            self._log_patrol_event("NAV_COMMAND", f"Executing navigation: {action}", {
                "action": action,
                "step_count": step_count,
                "nav_status": self.nav_controller.get_navigation_status()
            })
            
            speed = int(60 + self.energy_level * 20)
            self.dog.do_action(action, step_count=step_count, speed=speed)
            
            # Update SLAM system
            if self.slam_system:
                self.slam_system.update_from_movement(action, step_count)
            
            return  # Skip manual movement logic when following navigation
        
        # Choose behavior mode based on enabled features
        if not self.intelligent_scanning_enabled or not self.slam_enabled:
            # Simple patrol mode - basic obstacle avoidance
            self._simple_patrol_behavior(current_time)
            return
        
        # Advanced patrol mode - use scan data for intelligent navigation
        forward_clear = self.obstacle_scan_data['forward'] > self.config.OBSTACLE_SAFE_DISTANCE
        left_clear = self.obstacle_scan_data['left'] > 30
        right_clear = self.obstacle_scan_data['right'] > 30
        
        # Check if path ahead is clear based on recent scan
        scan_age = current_time - self.obstacle_scan_data['last_scan_time']
        
        if scan_age < 2.0 and not forward_clear:
            # Recent scan shows obstacle - use intelligent avoidance
            print(f"🧠 Using scan data for navigation - obstacle at {self.obstacle_scan_data['forward']:.1f}cm")
            self._log_patrol_event("PATROL_AVOIDANCE", "Using scan data for obstacle avoidance", {
                "obstacle_distance": self.obstacle_scan_data['forward'],
                "avoidance_reason": "predictive_scan_data"
            })
            self._execute_intelligent_avoidance(self.obstacle_scan_data)
        else:
            # Path seems clear - continue wandering intelligently
            if random.random() < 0.75:  # 75% chance to move forward when clear
                # Intelligent forward movement
                step_count = random.randint(2, 4)
                
                # Adjust speed based on clearest path
                base_speed = 60 + int(self.energy_level * 30)
                
                # Bonus speed if path is very clear
                if self.obstacle_scan_data['forward'] > 100:
                    base_speed += 10
                
                print(f"🚶 Walking forward {step_count} steps (path clear: {self.obstacle_scan_data['forward']:.1f}cm)")
                self._log_patrol_event("PATROL_FORWARD", f"Moving forward {step_count} steps", {
                    "step_count": step_count,
                    "speed": min(base_speed, 90),
                    "path_clearance": self.obstacle_scan_data['forward'],
                    "patrol_confidence": "high" if self.obstacle_scan_data['forward'] > 100 else "medium"
                })
                self.dog.do_action("forward", step_count=step_count, speed=min(base_speed, 90))
                
                # Note: Movement tracking now handled by sensor fusion localization
                
                # Strategic head positioning while walking
                if random.random() < 0.4:
                    # Look toward the more open side occasionally
                    if left_clear and right_clear:
                        # Both sides clear - random look
                        scan_angle = random.randint(-25, 25)
                    elif left_clear and not right_clear:
                        # Look left (more open)
                        scan_angle = random.randint(15, 35)
                    elif right_clear and not left_clear:
                        # Look right (more open) 
                        scan_angle = random.randint(-35, -15)
                    else:
                        # Both sides blocked - look straight
                        scan_angle = 0
                    
                    self.dog.head_move([[scan_angle, 0, 0]], speed=60)
                    
            else:
                # Strategic turning based on available space
                print("🔄 Strategic direction change...")
                self._log_patrol_event("PATROL_DIRECTION_CHANGE", "Executing strategic turn", {
                    "left_clear": left_clear,
                    "right_clear": right_clear,
                    "decision_reason": "strategic_patrol_pattern"
                })
                
                if left_clear and right_clear:
                    # Both sides open - random choice but prefer less recent
                    recent_lefts = sum(1 for _, dir, _ in self.avoidance_history[-2:] if dir == "left")
                    recent_rights = sum(1 for _, dir, _ in self.avoidance_history[-2:] if dir == "right")
                    
                    if recent_lefts > recent_rights:
                        action = "turn_right"
                    elif recent_rights > recent_lefts:
                        action = "turn_left"
                    else:
                        action = random.choice(["turn_left", "turn_right"])
                        
                elif left_clear:
                    action = "turn_left"
                elif right_clear:
                    action = "turn_right"
                else:
                    # Both sides blocked - back up and reassess
                    print("⚠️ Both sides blocked - backing up")
                    self.dog.do_action("backward", step_count=2, speed=60)
                    action = random.choice(["turn_left", "turn_right"])  # Try anyway
                
                # Add energetic trotting option when space is available
                if self.energy_level > 0.7 and (left_clear or right_clear):
                    if random.random() < 0.3:
                        action = "trot"
                        step_count = 1
                    else:
                        step_count = random.randint(1, 2)
                else:
                    step_count = random.randint(1, 2)
                
                speed = int(50 + self.energy_level * 35)
                self.dog.do_action(action, step_count=step_count, speed=speed)
                
                # Note: Movement tracking now handled by sensor fusion localization
    
    def _simple_patrol_behavior(self, current_time):
        """Simple patrol behavior with basic obstacle avoidance (fallback mode)"""
        # Basic movement pattern when advanced features are disabled
        if random.random() < 0.02:  # 2% chance per cycle
            # Simple obstacle check using basic distance sensor
            distance = self.dog.distance
            
            if distance < self.config.OBSTACLE_IMMEDIATE_THREAT:
                # Simple avoidance - just turn and try again
                turn_direction = "turn_left" if random.random() > 0.5 else "turn_right"
                turn_speed = self._get_appropriate_turn_speed()
                self.dog.do_action(turn_direction, step_count=self.config.TURN_STEPS_NORMAL, speed=turn_speed)
                print(f"🚧 Simple obstacle avoidance - {turn_direction}")
                
                if self.patrol_logging_enabled:
                    self._log_patrol_event("SIMPLE_AVOIDANCE", f"Basic obstacle avoidance: {turn_direction}", {
                        "obstacle_distance": distance,
                        "avoidance_type": "simple_turn"
                    })
            else:
                # Continue forward movement
                actions = ["forward", "forward", "forward", "turn_left", "turn_right"]  # Bias toward forward
                action = random.choice(actions)
                
                if action == "forward":
                    step_count = self.config.WALK_STEPS_NORMAL
                    speed = self._get_appropriate_walk_speed()
                else:
                    step_count = self.config.TURN_STEPS_SMALL
                    speed = self._get_appropriate_turn_speed()
                
                self.dog.do_action(action, step_count=step_count, speed=speed)
                
                if self.patrol_logging_enabled:
                    self._log_patrol_event("SIMPLE_MOVEMENT", f"Basic patrol movement: {action}", {
                        "action": action,
                        "step_count": step_count,
                        "speed": speed
                    })

    def _playing_behavior(self):
        """Playing behavior - energetic and fun movements"""
        if random.random() < 0.05:  # 5% chance per cycle
            actions = ["wag_tail", "head_up_down", "tilting_head", "shake_head"]
            action = random.choice(actions)
            speed = int(70 + self.energy_level * 30)
            steps = random.randint(2, 5)
            self.dog.do_action(action, step_count=steps, speed=speed)
            
        if random.random() < 0.02:  # 2% chance per cycle
            # Playful movements
            moves = ["push_up", "stretch", "trot"]
            move = random.choice(moves)
            self.dog.do_action(move, step_count=2, speed=80)
    
    def set_emotion(self, emotion: EmotionalState):
        """Set emotional state and update LED accordingly"""
        if emotion != self.current_emotion:
            old_emotion = self.current_emotion
            self.current_emotion = emotion
            profile = self.emotion_profiles[emotion]
            
            print(f"😊 Emotion: {emotion.value} (Energy: {self.energy_level:.2f})")
            
            # Log emotion change
            self._log_patrol_event("EMOTION_CHANGE", f"Emotion changed: {old_emotion.value} → {emotion.value}", {
                "old_emotion": old_emotion.value,
                "new_emotion": emotion.value,
                "energy_level": self.energy_level,
                "trigger_cause": "automatic_update"  # Could be enhanced to track specific triggers
            })
            
            # Update LED display
            if profile.led_style == "boom":
                self.dog.rgb_strip.set_mode(
                    profile.led_style, profile.led_color, 
                    bps=2.0, brightness=0.8
                )
            else:
                self.dog.rgb_strip.set_mode(
                    profile.led_style, profile.led_color, 
                    brightness=0.7
                )
                
            # Occasional emotional sound
            if random.random() < 0.3:  # 30% chance
                sound = random.choice(profile.sounds)
                volume = int(50 + profile.movement_energy * 50)
                self.dog.speak(sound, volume=volume)
    
    def set_behavior(self, behavior: BehaviorState):
        """Set behavior state"""
        if behavior != self.current_behavior:
            old_behavior = self.current_behavior
            time_in_previous = time.time() - self.behavior_start_time
            
            print(f"🎯 Behavior: {behavior.value}")
            
            # Log behavior change
            self._log_patrol_event("BEHAVIOR_CHANGE", f"Behavior changed: {old_behavior.value} → {behavior.value}", {
                "old_behavior": old_behavior.value,
                "new_behavior": behavior.value,
                "time_in_previous_behavior": round(time_in_previous, 1),
                "transition_reason": "automatic_state_machine"
            })
            
            self.current_behavior = behavior
            self.behavior_start_time = time.time()
    
    def _voice_recognition_loop(self):
        """Voice recognition loop with wake word detection"""
        if not VOICE_AVAILABLE:
            return
            
        recognizer = sr.Recognizer()
        microphone = sr.Microphone()
        
        # Adjust for ambient noise
        with microphone as source:
            print("🎙️ Calibrating microphone for ambient noise...")
            recognizer.adjust_for_ambient_noise(source)
            
        print(f"🎧 Listening for wake word: '{self.wake_word}'...")
        
        while self.running:
            try:
                # Listen for audio
                with microphone as source:
                    # Short timeout to check self.running frequently
                    audio = recognizer.listen(source, timeout=1, phrase_time_limit=3)
                
                # Recognize speech
                try:
                    text = recognizer.recognize_google(audio).lower()
                    
                    if self.wake_word in text:
                        print(f"🎯 Wake word detected: '{text}'")
                        self._process_voice_command(text)
                        
                except sr.UnknownValueError:
                    # Could not understand audio - normal, ignore
                    pass
                except sr.RequestError as e:
                    print(f"⚠️ Voice recognition service error: {e}")
                    time.sleep(1)
                    
            except sr.WaitTimeoutError:
                # Normal timeout - continue listening
                pass
            except Exception as e:
                print(f"⚠️ Voice recognition error: {e}")
                time.sleep(1)
    
    def _process_voice_command(self, full_text: str):
        """Process voice command after wake word detection"""
        self.last_voice_command_time = time.time()
        
        # Remove wake word and clean up text
        command_text = full_text.replace(self.wake_word, "").strip()
        
        if not command_text:
            # Just wake word, acknowledge
            print("👋 Hello! I'm listening...")
            self.dog.speak("pant", volume=60)
            self.set_emotion(EmotionalState.HAPPY)
            return
            
        print(f"🎙️ Voice command: '{command_text}'")
        
        # Visual feedback for voice command
        self.dog.rgb_strip.set_mode("boom", "cyan", bps=3.0, brightness=1.0)
        
        # Find matching command
        command_executed = False
        for cmd_key, cmd_action in self.voice_commands.items():
            if cmd_key in command_text:
                print(f"✅ Executing command: {cmd_key}")
                try:
                    self._log_patrol_event("VOICE_COMMAND", f"Executing voice command: {cmd_key}", {
                        "command": cmd_key,
                        "full_text": command_text,
                        "execution_status": "starting"
                    })
                    
                    cmd_action()
                    command_executed = True
                    
                    # Positive feedback
                    self.dog.speak("woohoo", volume=70)
                    self.set_emotion(EmotionalState.HAPPY)
                    
                    self._log_patrol_event("VOICE_SUCCESS", f"Voice command executed successfully: {cmd_key}")
                    
                except Exception as e:
                    print(f"❌ Command execution error: {e}")
                    self._log_patrol_event("VOICE_ERROR", f"Voice command failed: {cmd_key}", {
                        "error": str(e)
                    })
                    self.dog.speak("confused_2", volume=60)
                break
        
        if not command_executed:
            print(f"❓ Unknown command: '{command_text}'")
            self.dog.speak("confused_1", volume=60)
            self.set_emotion(EmotionalState.CONFUSED)
            
        # Return LED to normal after 2 seconds
        threading.Timer(2.0, lambda: self.set_emotion(self.current_emotion)).start()
    
    def _praise_response(self):
        """Response to 'good dog' command"""
        self.dog.do_action("wag_tail", step_count=8, speed=95)
        self.dog.speak("woohoo", volume=80)
        self.set_emotion(EmotionalState.EXCITED)
        self.energy_level = min(1.0, self.energy_level + 0.2)  # Boost energy
        print("😊 PiDog is very happy!")
    
    def _scold_response(self):
        """Response to 'bad dog' command"""  
        self.dog.do_action("doze_off", speed=30)
        self.dog.speak("snoring", volume=40)
        self.set_emotion(EmotionalState.TIRED)
        self.energy_level = max(0.1, self.energy_level - 0.3)  # Reduce energy
        print("😔 PiDog feels sad...")
    
    def _voice_sit(self):
        """Voice command: sit"""
        self.is_walking = False
        self.dog.do_action("sit", speed=60)
        
    def _voice_stand(self):
        """Voice command: stand"""  
        self.is_walking = False
        self.dog.do_action("stand", speed=60)
        
    def _voice_lie(self):
        """Voice command: lie down"""
        self.is_walking = False
        self.dog.do_action("lie", speed=50)
        
    def _voice_walk(self):
        """Voice command: walk"""
        self.is_walking = True
        self.last_walk_command_time = time.time()
        walk_speed = self._get_appropriate_walk_speed()
        self.dog.do_action("forward", step_count=self.config.WALK_STEPS_NORMAL, speed=walk_speed)
        
    def _voice_turn_left(self):
        """Voice command: turn left"""
        self.is_walking = True
        self.last_walk_command_time = time.time()
        turn_speed = self._get_appropriate_turn_speed()
        self.dog.do_action("turn_left", step_count=self.config.TURN_45_DEGREES, speed=turn_speed)
        
    def _voice_turn_right(self):
        """Voice command: turn right"""
        self.is_walking = True  
        self.last_walk_command_time = time.time()
        turn_speed = self._get_appropriate_turn_speed()
        self.dog.do_action("turn_right", step_count=self.config.TURN_45_DEGREES, speed=turn_speed)
    
    def generate_patrol_report(self) -> dict:
        """Generate comprehensive patrol report"""
        current_time = time.time()
        total_patrol_time = current_time - self.patrol_start_time
        
        # Analyze patrol log
        event_counts = {}
        behavior_times = {}
        emotion_changes = 0
        obstacles_detected = 0
        interactions = 0
        voice_commands = 0
        
        for entry in self.patrol_log:
            event_type = entry['event_type']
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
            
            if event_type == 'EMOTION_CHANGE':
                emotion_changes += 1
            elif event_type in ['THREAT_IMMEDIATE', 'THREAT_APPROACHING']:
                obstacles_detected += 1
            elif event_type == 'TOUCH_INTERACTION':
                interactions += 1
            elif event_type == 'VOICE_COMMAND':
                voice_commands += 1
        
        report = {
            "session_info": {
                "session_id": self.patrol_session_id,
                "start_time": self.patrol_start_time,
                "end_time": current_time,
                "total_duration": total_patrol_time,
                "log_file": self.log_file_path
            },
            "activity_summary": {
                "total_events": len(self.patrol_log),
                "event_breakdown": event_counts,
                "obstacles_encountered": obstacles_detected,
                "interactions": interactions,
                "voice_commands": voice_commands,
                "emotion_changes": emotion_changes
            },
            "final_state": {
                "behavior": self.current_behavior.value,
                "emotion": self.current_emotion.value,
                "energy_level": self.energy_level,
                "scan_data": dict(self.obstacle_scan_data)
            }
        }
        
        return report

    def _shutdown(self):
        """Safely shutdown the AI system"""
        print("🛑 Initiating patrol system shutdown...")
        
        # Log shutdown initiation
        self._log_patrol_event("SYSTEM_SHUTDOWN", "Patrol system shutdown initiated")
        
        # Stop and save SLAM system
        if self.slam_system:
            self._log_patrol_event("SLAM_SHUTDOWN", "Saving house map and stopping SLAM")
            self.slam_system.stop()
            print("✓ House map saved")
            
        # Stop sensor fusion localization
        if self.sensor_localizer:
            self._log_patrol_event("LOCALIZATION_SHUTDOWN", "Stopping sensor fusion localization")
            self.sensor_localizer.stop_localization()
            print("✓ Sensor fusion localization stopped")
        
        # Generate final patrol report
        try:
            report = self.generate_patrol_report()
            report_file = f"patrol_report_{self.patrol_session_id}.json"
            
            import json
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            
            print(f"📊 Patrol report saved: {report_file}")
            print(f"📋 Total events logged: {len(self.patrol_log)}")
            print(f"⏱️ Total patrol time: {report['session_info']['total_duration']:.1f}s")
            
            self._log_patrol_event("REPORT_GENERATED", f"Final patrol report saved to {report_file}", {
                "total_events": len(self.patrol_log),
                "report_file": report_file
            })
            
        except Exception as e:
            print(f"⚠️ Error generating patrol report: {e}")
        
        self.running = False
        
        if self.sensor_thread:
            self.sensor_thread.join(timeout=2.0)
            
        if self.scanning_thread:
            self.scanning_thread.join(timeout=2.0)
            
        if self.voice_thread:
            self.voice_thread.join(timeout=2.0)
        
        if self.dog:
            try:
                print("🛌 Returning to rest position...")
                self._log_patrol_event("PHYSICAL_SHUTDOWN", "Returning PiDog to rest position")
                
                self.dog.rgb_strip.set_mode("breath", "black")  # Turn off LEDs
                self.dog.stop_and_lie()
                self.dog.close()
                print("✓ AI system shutdown complete")
                
                # Final log entry
                with open(self.log_file_path, 'a', encoding='utf-8') as f:
                    f.write(f"\n[{time.strftime('%H:%M:%S')}] ========== PATROL SESSION ENDED ==========\n")
                    
            except Exception as e:
                print(f"⚠️ Shutdown error: {e}")
    
    def _update_slam_with_imu(self, reading: SensorReading):
        """Update SLAM position using sensor fusion localization"""
        if not self.sensor_localizer:
            return
        
        # Extract IMU data
        ax, ay, az = reading.acceleration
        gx, gy, gz = reading.gyroscope
        
        # Update sensor fusion localizer with IMU data
        self.sensor_localizer.update_motion(
            acceleration=(ax, ay, az),
            gyroscope=(gx, gy, gz)
        )
        
        # Log surface detection changes
        status = self.sensor_localizer.get_localization_status()
        surface_type = status.get("surface_type", "unknown")
        
        # Log surface changes
        if hasattr(self, '_last_surface_type'):
            if self._last_surface_type != surface_type:
                self._log_patrol_event("SURFACE_DETECTED", f"Surface change: {self._last_surface_type} → {surface_type}", {
                    "old_surface": self._last_surface_type,
                    "new_surface": surface_type,
                    "localization_confidence": status.get("particle_filter", {}).get("confidence", 0.0)
                })
        
        self._last_surface_type = surface_type
    
    def calibrate_position(self, method: str = "wall_follow") -> bool:
        """
        Calibrate PiDog's position using various methods
        
        Args:
            method: Calibration method ("wall_follow", "corner_seek", "landmark_align")
        """
        if not self.slam_system:
            print("❌ SLAM system not available for calibration")
            return False
        
        print(f"🎯 Starting position calibration using {method}...")
        self._log_patrol_event("CALIBRATION_START", f"Position calibration started: {method}")
        
        if method == "wall_follow":
            return self._calibrate_wall_follow()
        elif method == "corner_seek":
            return self._calibrate_corner_seek()
        elif method == "landmark_align":
            return self._calibrate_landmark_align()
        else:
            print(f"❌ Unknown calibration method: {method}")
            return False
    
    def _calibrate_wall_follow(self) -> bool:
        """Calibrate position by following a wall to establish reference"""
        print("🧱 Wall following calibration...")
        
        # Perform 360-degree scan to find walls
        wall_distances = {}
        for angle in range(0, 360, 45):  # Every 45 degrees
            head_angle = max(-80, min(80, angle - 180))  # Convert to head range
            self.dog.head_move([[head_angle, 0, 0]], speed=90)
            time.sleep(0.3)
            
            distance = self.dog.ultrasonic.read_distance()
            if 10 < distance < 200:  # Valid wall distance
                wall_distances[angle] = distance
        
        # Return head to center
        self.dog.head_move([[0, 0, 0]], speed=90)
        
        if not wall_distances:
            print("❌ No walls found for calibration")
            return False
        
        # Find closest wall
        closest_angle, wall_distance = min(wall_distances.items(), key=lambda x: x[1])
        
        print(f"🎯 Closest wall at {closest_angle}°, distance {wall_distance:.1f}cm")
        
        # Move toward wall for reference alignment
        if wall_distance > 30:
            # Calculate turn needed
            turn_direction = "turn_left" if closest_angle > 180 else "turn_right"
            turn_steps = min(3, abs(closest_angle - 180) // 45)
            
            if turn_steps > 0:
                self.dog.do_action(turn_direction, step_count=turn_steps, speed=60)
                if self.slam_system:
                    self.slam_system.update_from_movement(turn_direction, turn_steps)
            
            # Move closer to wall
            steps_needed = max(1, int((wall_distance - 25) / 15))  # Get to ~25cm from wall
            self.dog.do_action("forward", step_count=min(steps_needed, 3), speed=50)
            if self.slam_system:
                self.slam_system.update_from_movement("forward", min(steps_needed, 3))
        
        # Update SLAM position with high confidence (we know we're near a wall)
        if self.slam_system:
            current_pos = self.slam_system.house_map.get_position()
            current_pos.confidence = 0.95  # High confidence after calibration
            
            self._log_patrol_event("CALIBRATION_SUCCESS", f"Wall calibration completed", {
                "wall_angle": closest_angle,
                "wall_distance": wall_distance,
                "new_confidence": current_pos.confidence
            })
        
        print("✓ Wall calibration completed")
        return True
    
    def _calibrate_corner_seek(self) -> bool:
        """Calibrate by finding and aligning with room corners"""
        print("📐 Corner seeking calibration...")
        
        # Look for corner patterns in current scan data
        corners_found = 0
        scan_data = self._perform_three_way_scan()
        
        # Simple corner detection: look for perpendicular walls
        if (scan_data['forward'] < 50 and scan_data['left'] < 50 and scan_data['right'] > 100):
            # Possible left corner
            self.dog.do_action("turn_left", step_count=2, speed=60)
            if self.slam_system:
                self.slam_system.update_from_movement("turn_left", 2)
            corners_found += 1
        elif (scan_data['forward'] < 50 and scan_data['right'] < 50 and scan_data['left'] > 100):
            # Possible right corner  
            self.dog.do_action("turn_right", step_count=2, speed=60)
            if self.slam_system:
                self.slam_system.update_from_movement("turn_right", 2)
            corners_found += 1
        
        if corners_found > 0:
            # Update position confidence
            if self.slam_system:
                current_pos = self.slam_system.house_map.get_position()
                current_pos.confidence = 0.9
                
                self._log_patrol_event("CALIBRATION_SUCCESS", f"Corner calibration completed", {
                    "corners_found": corners_found,
                    "scan_data": scan_data
                })
            
            print(f"✓ Corner calibration completed ({corners_found} corners)")
            return True
        else:
            print("❌ No clear corners found")
            return False
    
    def _calibrate_landmark_align(self) -> bool:
        """Calibrate using known landmarks from the map"""
        if not self.slam_system or not self.slam_system.house_map.landmarks:
            print("❌ No landmarks available for calibration")
            return False
        
        print("🎯 Landmark alignment calibration...")
        
        # Get nearby landmarks
        nav_info = self.slam_system.get_navigation_info()
        nearby_landmarks = nav_info.get("nearby_landmarks", [])
        
        if not nearby_landmarks:
            print("❌ No nearby landmarks for calibration")
            return False
        
        # Use closest landmark for alignment
        closest_landmark = nearby_landmarks[0]
        print(f"🎯 Aligning with landmark: {closest_landmark['type']} at {closest_landmark['distance']:.1f}cm")
        
        # This would involve more complex landmark recognition and alignment
        # For now, just increase position confidence based on landmark proximity
        if self.slam_system:
            current_pos = self.slam_system.house_map.get_position()
            current_pos.confidence = min(0.95, current_pos.confidence + 0.2)
            
            self._log_patrol_event("CALIBRATION_SUCCESS", f"Landmark calibration completed", {
                "landmark_type": closest_landmark['type'],
                "landmark_distance": closest_landmark['distance'],
                "new_confidence": current_pos.confidence
            })
        
        print("✓ Landmark calibration completed")
        return True
    
    def _start_autonomous_exploration(self):
        """Start autonomous exploration mode"""
        if not self.nav_controller:
            print("❌ Navigation system not available")
            self.dog.speak("confused_1", volume=60)
            return
        
        success = self.nav_controller.start_exploration_mode()
        if success:
            print("🔍 Autonomous exploration started")
            self.dog.speak("woohoo", volume=70)
            self.set_emotion(EmotionalState.EXCITED)
            self.set_behavior(BehaviorState.EXPLORING)
            
            self._log_patrol_event("NAV_START", "Autonomous exploration mode started", {
                "nav_status": self.nav_controller.get_navigation_status()
            })
        else:
            print("❌ Could not start exploration")
            self.dog.speak("confused_2", volume=60)
    
    def _stop_navigation(self):
        """Stop current navigation"""
        if not self.nav_controller:
            return
        
        self.nav_controller.stop_navigation()
        print("🛑 Navigation stopped")
        self.dog.speak("single_bark_1", volume=60)
        
        self._log_patrol_event("NAV_STOP", "Navigation manually stopped")
    
    def _navigate_to_nearest_room(self):
        """Navigate to the nearest identified room"""
        if not self.nav_controller or not self.slam_system:
            print("❌ Navigation system not available")
            return
        
        # Find nearest room
        current_pos = self.slam_system.house_map.get_position()
        nearest_room = None
        min_distance = float('inf')
        
        for room_id, room in self.slam_system.house_map.rooms.items():
            distance = math.sqrt(
                (room.center.x - current_pos.x) ** 2 +
                (room.center.y - current_pos.y) ** 2
            )
            if distance < min_distance:
                min_distance = distance
                nearest_room = room_id
        
        if nearest_room:
            success = self.nav_controller.navigate_to_room(nearest_room)
            if success:
                room_info = self.slam_system.house_map.rooms[nearest_room]
                print(f"🏠 Navigating to {room_info.room_type} (Room {nearest_room})")
                self.dog.speak("single_bark_2", volume=70)
                self.set_behavior(BehaviorState.EXPLORING)
                
                self._log_patrol_event("NAV_ROOM", f"Navigation to room {nearest_room} started", {
                    "room_type": room_info.room_type,
                    "distance": min_distance * self.slam_system.house_map.cell_size_cm
                })
            else:
                print("❌ Could not navigate to room")
                self.dog.speak("confused_1", volume=60)
        else:
            print("❌ No rooms identified yet")
            self.dog.speak("confused_2", volume=60)
    
    def _show_map_visualization(self):
        """Show visual representation of the current map"""
        if not self.slam_system:
            print("❌ SLAM system not available for map visualization")
            return
        
        try:
            # Import visualization here to avoid dependency issues
            from map_visualization import MapVisualizer
            
            visualizer = MapVisualizer(self.slam_system.house_map)
            
            print("\n🗺️ Current House Map:")
            visualizer.print_map(show_colors=True)
            visualizer.print_room_summary()
            visualizer.print_landmark_summary()
            
            # Export current map
            timestamp = int(time.time())
            visualizer.export_to_json(f"current_map_{timestamp}.json")
            visualizer.save_report(f"map_report_{timestamp}.txt")
            
            self.dog.speak("single_bark_1", volume=60)
            self._log_patrol_event("MAP_DISPLAY", "Map visualization shown", {
                "rooms_detected": len(self.slam_system.house_map.rooms),
                "landmarks_detected": len(self.slam_system.house_map.landmarks),
                "export_files": [f"current_map_{timestamp}.json", f"map_report_{timestamp}.txt"]
            })
            
        except ImportError:
            print("❌ Map visualization not available")
            self.dog.speak("confused_1", volume=60)
        except Exception as e:
            print(f"❌ Map visualization error: {e}")
            self.dog.speak("confused_2", volume=60)
    
    def _calibrate_sensors(self):
        """Calibrate sensor fusion system"""
        if not self.sensor_localizer:
            print("❌ Sensor fusion not available")
            self.dog.speak("confused_1", volume=60)
            return
        
        print("🎯 Starting sensor calibration - keep PiDog stationary for 5 seconds...")
        self.dog.speak("single_bark_1", volume=60)
        
        # Set behavior to calibrating
        old_behavior = self.current_behavior
        self.set_behavior(BehaviorState.IDLE)
        
        self._log_patrol_event("SENSOR_CALIBRATION", "Starting sensor calibration", {
            "instruction": "keep_stationary_5_seconds"
        })
        
        try:
            # Perform calibration
            success = self.sensor_localizer.calibrate_stationary(duration=5.0)
            
            if success:
                print("✓ Sensor calibration completed")
                self.dog.speak("woohoo", volume=70)
                self.set_emotion(EmotionalState.HAPPY)
                
                self._log_patrol_event("CALIBRATION_SUCCESS", "Sensor calibration completed successfully")
            else:
                print("❌ Sensor calibration failed")
                self.dog.speak("confused_2", volume=60)
                
                self._log_patrol_event("CALIBRATION_FAILED", "Sensor calibration failed")
                
        except Exception as e:
            print(f"❌ Calibration error: {e}")
            self.dog.speak("confused_1", volume=60)
            
            self._log_patrol_event("CALIBRATION_ERROR", f"Sensor calibration error: {e}")
        
        # Restore behavior
        self.set_behavior(old_behavior)
    
    def print_status(self):
        """Print current AI status"""
        print(f"\n=== PiDog AI Status ===")
        print(f"Emotion: {self.current_emotion.value}")
        print(f"Behavior: {self.current_behavior.value}")
        print(f"Energy: {self.energy_level:.2f}")
        print(f"Interactions: {self.interaction_count}")
        print(f"Touch preferences: {self.touch_preferences}")
        print(f"Attention target: {self.attention_target}°" if self.attention_target else "None")
        print(f"Recent obstacles: {len(self.obstacle_memory)}")
        print(f"Voice enabled: {self.voice_enabled}")
        print(f"Last voice command: {time.time() - self.last_voice_command_time:.1f}s ago")
        print(f"Walking state: {self.is_walking}")
        print(f"Scan data: F:{self.obstacle_scan_data['forward']:.1f} L:{self.obstacle_scan_data['left']:.1f} R:{self.obstacle_scan_data['right']:.1f}")
        print(f"Avoidance history: {len(self.avoidance_history)} recent")
        print(f"Stuck counter: {self.stuck_counter}")
        print(f"Patrol log entries: {len(self.patrol_log)}")
        print(f"Patrol log file: {self.log_file_path}")
        
        # SLAM system status
        if self.slam_system:
            try:
                map_summary = self.slam_system.get_navigation_info()
                current_pos = self.slam_system.house_map.get_position()
                print(f"SLAM enabled: {self.slam_enabled}")
                print(f"Map position: ({current_pos.x:.1f}, {current_pos.y:.1f}) @ {current_pos.heading:.1f}°")
                print(f"Position confidence: {current_pos.confidence:.3f}")
                if map_summary.get("room_info"):
                    room_info = map_summary["room_info"]
                    print(f"Current room: {room_info['room_type']} ({room_info['size_m2']:.1f}m²)")
                print(f"Landmarks nearby: {len(map_summary.get('nearby_landmarks', []))}")
                nav_suggestion = map_summary.get("suggested_direction", {})
                if nav_suggestion:
                    print(f"Suggested direction: {nav_suggestion.get('suggested_direction', 'none')} (confidence: {nav_suggestion.get('confidence', 0.0):.2f})")
                
                # Sensor fusion status
                if self.sensor_localizer:
                    loc_status = self.sensor_localizer.get_localization_status()
                    pf_data = loc_status.get("particle_filter", {})
                    print(f"Sensor fusion: Active")
                    print(f"  Surface type: {loc_status.get('surface_type', 'unknown')}")
                    print(f"  Particle filter confidence: {pf_data.get('confidence', 0.0):.3f}")
                    print(f"  Recent ultrasonic scans: {loc_status.get('recent_scans', 0)}")
                    print(f"  Motion samples: {loc_status.get('motion_samples', 0)}")
                
            except Exception as e:
                print(f"SLAM status error: {e}")
        else:
            print(f"SLAM enabled: {self.slam_enabled}")
            
        print(f"======================")

    def print_configuration(self):
        """Print current configuration settings"""
        print(f"\n=== PiDog Configuration ===")
        print(f"Mode: {'Advanced' if self.slam_enabled else 'Simple'}")
        
        print(f"\n--- Feature Toggles ---")
        print(f"Voice Commands: {self.config.ENABLE_VOICE_COMMANDS}")
        print(f"SLAM Mapping: {self.config.ENABLE_SLAM_MAPPING}")
        print(f"Sensor Fusion: {self.config.ENABLE_SENSOR_FUSION}")
        print(f"Intelligent Scanning: {self.config.ENABLE_INTELLIGENT_SCANNING}")
        print(f"Emotional System: {self.config.ENABLE_EMOTIONAL_SYSTEM}")
        print(f"Learning System: {self.config.ENABLE_LEARNING_SYSTEM}")
        print(f"Patrol Logging: {self.config.ENABLE_PATROL_LOGGING}")
        print(f"Autonomous Navigation: {self.config.ENABLE_AUTONOMOUS_NAVIGATION}")
        
        print(f"\n--- Obstacle Avoidance ---")
        print(f"Immediate Threat: {self.config.OBSTACLE_IMMEDIATE_THREAT}cm")
        print(f"Approaching Threat: {self.config.OBSTACLE_APPROACHING_THREAT}cm") 
        print(f"Emergency Stop: {self.config.OBSTACLE_EMERGENCY_STOP}cm")
        print(f"Safe Distance: {self.config.OBSTACLE_SAFE_DISTANCE}cm")
        print(f"Scan Interval: {self.config.OBSTACLE_SCAN_INTERVAL}s")
        
        print(f"\n--- Movement Parameters ---")
        print(f"Turn Steps - Small: {self.config.TURN_STEPS_SMALL}, Normal: {self.config.TURN_STEPS_NORMAL}, Large: {self.config.TURN_STEPS_LARGE}")
        print(f"Walk Steps - Short: {self.config.WALK_STEPS_SHORT}, Normal: {self.config.WALK_STEPS_NORMAL}, Long: {self.config.WALK_STEPS_LONG}")
        print(f"Backup Steps: {self.config.BACKUP_STEPS}")
        print(f"Walk Speeds - Slow: {self.config.SPEED_SLOW}, Normal: {self.config.SPEED_NORMAL}, Fast: {self.config.SPEED_FAST}")
        print(f"Turn Speeds - Slow: {self.config.SPEED_TURN_SLOW}, Normal: {self.config.SPEED_TURN_NORMAL}, Fast: {self.config.SPEED_TURN_FAST}")
        print(f"Emergency Speed: {self.config.SPEED_EMERGENCY}")
        
        print(f"\n--- Turn Calibration ---")
        print(f"Degrees per step: {self.config.TURN_DEGREES_PER_STEP}° (at speed {self.config.SPEED_TURN_NORMAL})")
        print(f"Turn angles - 45°: {self.config.TURN_45_DEGREES} steps, 90°: {self.config.TURN_90_DEGREES} steps, 180°: {self.config.TURN_180_DEGREES} steps")
        
        print(f"\n--- Behavior Timing ---")
        print(f"Patrol Duration: {self.config.PATROL_DURATION_MIN}-{self.config.PATROL_DURATION_MAX}s")
        print(f"Rest Duration: {self.config.REST_DURATION}s")
        print(f"Interaction Timeout: {self.config.INTERACTION_TIMEOUT}s")
        
        print(f"\n--- Voice Settings ---")
        print(f"Wake Word: '{self.config.WAKE_WORD}'")
        print(f"Default Volume: {self.config.VOICE_VOLUME_DEFAULT}")
        print(f"Voice Timeout: {self.config.VOICE_COMMAND_TIMEOUT}s")
        
        print(f"===========================")

    def _toggle_simple_mode(self):
        """Switch to simple mode - disable advanced features"""
        print("🔄 Switching to Simple Mode...")
        
        # Disable advanced features
        self.slam_enabled = False
        self.sensor_fusion_enabled = False
        self.intelligent_scanning_enabled = False
        self.autonomous_nav_enabled = False
        
        # Stop advanced systems
        if self.slam_system:
            self.slam_system.stop()
        if self.sensor_localizer:
            self.sensor_localizer.stop_localization()
            
        self._log_patrol_event("MODE_CHANGE", "Switched to Simple Mode", {
            "slam_enabled": False,
            "sensor_fusion_enabled": False,
            "intelligent_scanning": False,
            "autonomous_navigation": False
        })
        
        self.dog.speak("single_bark_1", volume=self.config.VOICE_VOLUME_DEFAULT)
        print("✓ Simple Mode activated - using basic obstacle avoidance")

    def _toggle_advanced_mode(self):
        """Switch to advanced mode - enable available features"""
        print("🔄 Switching to Advanced Mode...")
        
        # Check if dependencies are available
        if not MAPPING_AVAILABLE:
            print("⚠️ Cannot enable Advanced Mode - missing dependencies (numpy)")
            self.dog.speak("confused_1", volume=self.config.VOICE_VOLUME_DEFAULT)
            return
            
        # Enable advanced features
        self.slam_enabled = True
        self.sensor_fusion_enabled = True
        self.intelligent_scanning_enabled = True
        self.autonomous_nav_enabled = True
        
        # Restart systems if needed
        if not self.slam_system:
            self.slam_system = PiDogSLAM(f"house_map_{self.patrol_session_id}.pkl")
            self.slam_system.start()
            
        if not self.sensor_localizer:
            self.sensor_localizer = SensorFusionLocalizer(self.slam_system.house_map)
            self.sensor_localizer.start_localization()
            
        if not self.nav_controller:
            if not self.pathfinder:
                self.pathfinder = PiDogPathfinder(self.slam_system.house_map)
            self.nav_controller = NavigationController(self.pathfinder)
        
        self._log_patrol_event("MODE_CHANGE", "Switched to Advanced Mode", {
            "slam_enabled": True,
            "sensor_fusion_enabled": True,
            "intelligent_scanning": True,
            "autonomous_navigation": True
        })
        
        self.dog.speak("woohoo", volume=self.config.VOICE_VOLUME_DEFAULT)
        print("✓ Advanced Mode activated - full AI capabilities enabled")
    
    def _load_config_preset(self, preset_name):
        """Load a configuration preset"""
        if not CONFIG_AVAILABLE:
            print("⚠️ Cannot load presets - pidog_config.py not available")
            self.dog.speak("confused_1", volume=self.config.VOICE_VOLUME_DEFAULT)
            return
            
        try:
            print(f"🔄 Loading {preset_name} configuration preset...")
            
            # Load new configuration
            new_config = load_config(preset_name)
            
            # Validate new configuration
            warnings = validate_config(new_config)
            if warnings:
                print("⚠️ Configuration warnings:")
                for warning in warnings:
                    print(f"   - {warning}")
            
            # Apply new configuration
            old_config_name = getattr(self.config, '__class__', 'Unknown').__name__
            self.config = new_config
            
            # Update feature flags based on new config
            self.slam_enabled = MAPPING_AVAILABLE and self.config.ENABLE_SLAM_MAPPING
            self.sensor_fusion_enabled = self.slam_enabled and self.config.ENABLE_SENSOR_FUSION
            self.intelligent_scanning_enabled = self.config.ENABLE_INTELLIGENT_SCANNING
            self.autonomous_nav_enabled = self.slam_enabled and self.config.ENABLE_AUTONOMOUS_NAVIGATION
            self.emotional_system_enabled = self.config.ENABLE_EMOTIONAL_SYSTEM
            self.learning_enabled = self.config.ENABLE_LEARNING_SYSTEM
            self.patrol_logging_enabled = self.config.ENABLE_PATROL_LOGGING
            self.voice_enabled = VOICE_AVAILABLE and self.config.ENABLE_VOICE_COMMANDS
            
            # Update wake word
            self.wake_word = self.config.WAKE_WORD
            
            # Log the configuration change
            self._log_patrol_event("CONFIG_PRESET", f"Loaded configuration preset: {preset_name}", {
                "preset_name": preset_name,
                "old_config": old_config_name,
                "slam_enabled": self.slam_enabled,
                "voice_enabled": self.voice_enabled,
                "speed_normal": self.config.SPEED_NORMAL
            })
            
            self.dog.speak("single_bark_1", volume=self.config.VOICE_VOLUME_DEFAULT)
            print(f"✓ {preset_name.title()} configuration loaded successfully")
            print(f"   SLAM: {'✓' if self.slam_enabled else '✗'}")
            print(f"   Speed Normal: {self.config.SPEED_NORMAL}")
            print(f"   Obstacle Threshold: {self.config.OBSTACLE_IMMEDIATE_THREAT}cm")
            
        except Exception as e:
            print(f"✗ Failed to load {preset_name} preset: {e}")
            self.dog.speak("confused_2", volume=self.config.VOICE_VOLUME_DEFAULT)
    
    def _test_walk_speed(self, speed_mode):
        """Test walk speed calibration"""
        print(f"🧪 Testing {speed_mode} walk speed...")
        
        if speed_mode == "slow":
            speed = self.config.SPEED_SLOW
        elif speed_mode == "normal":
            speed = self.config.SPEED_NORMAL
        elif speed_mode == "fast":
            speed = self.config.SPEED_FAST
        else:
            return
            
        print(f"   Walking {self.config.WALK_STEPS_NORMAL} steps at speed {speed}")
        self.dog.do_action("forward", step_count=self.config.WALK_STEPS_NORMAL, speed=speed)
        
        self._log_patrol_event("SPEED_TEST", f"Walk speed test: {speed_mode}", {
            "speed_mode": speed_mode,
            "speed_value": speed,
            "step_count": self.config.WALK_STEPS_NORMAL
        })
    
    def _test_turn_angle(self, degrees):
        """Test turn angle calibration"""
        print(f"🧪 Testing {degrees}° turn...")
        
        if degrees == 45:
            steps = self.config.TURN_45_DEGREES
        elif degrees == 90:
            steps = self.config.TURN_90_DEGREES
        elif degrees == 180:
            steps = self.config.TURN_180_DEGREES
        else:
            return
            
        speed = self.config.SPEED_TURN_NORMAL
        direction = "turn_left" if random.random() > 0.5 else "turn_right"
        
        print(f"   Turning {direction} {steps} steps at speed {speed} (should be {degrees}°)")
        self.dog.do_action(direction, step_count=steps, speed=speed)
        
        self._log_patrol_event("TURN_TEST", f"Turn angle test: {degrees}°", {
            "target_degrees": degrees,
            "step_count": steps,
            "speed": speed,
            "direction": direction,
            "expected_degrees_per_step": self.config.TURN_DEGREES_PER_STEP
        })


def main():
    """Main function with configuration display"""
    # Load default configuration  
    if CONFIG_AVAILABLE:
        config = load_config("default")
        config_source = "pidog_config.py"
        warnings = validate_config(config)
    else:
        config = PiDogConfig()
        config_source = "embedded fallback"
        warnings = []
    
    print("🤖 Advanced PiDog AI Behavior System")
    print("====================================")
    print(f"📋 Configuration: {config_source}")
    if warnings:
        print("⚠️ Configuration warnings detected")
    print()
    print("Features:")
    print("• 🧠 Emotional state system with LED feedback")
    print("• 📚 Learning touch preferences") 
    print("• ⚡ Energy management and fatigue")
    print("• 🚧 Smart obstacle avoidance with memory")
    print("• 👂 Enhanced sound direction tracking & body turning")
    print("• 🚶 Intelligent patrol behavior with predictive obstacle avoidance")
    print("• 🔍 3-way ultrasonic scanning (forward/left/right) during movement")
    print("• 🧠 Smart pathfinding - turns toward most open direction")
    print("• 🔄 Anti-stuck system with multiple escape strategies")
    print("• 🎙️ Voice commands with 'PiDog' wake word")
    print("• 🎯 Advanced behavior state machine")
    print("• 📊 Comprehensive patrol logging with timestamped events")
    print("• 📝 Automatic patrol report generation")
    if MAPPING_AVAILABLE:
        print("• 🗺️ SLAM house mapping with persistent map storage")
        print("• 📍 Sensor fusion localization (IMU + ultrasonic + particle filter)")
        print("• 🏃 Surface type detection and adaptive movement calibration")
        print("• 🎯 Multiple calibration methods (wall-follow, corner-seek, sensor-cal)")
        print("• 🧠 Landmark detection and room identification")
        print("• 🔍 Ultrasonic triangulation for position correction")
    print("• � Multi-sensor fusion with movement analysis")
    print()
    if VOICE_AVAILABLE:
        print("🎙️ Voice Commands Available:")
        print("   Say 'PiDog' + command:")
        print("   • 'sit', 'stand', 'lie down', 'walk'")
        print("   • 'turn left', 'turn right', 'wag tail'")  
        print("   • 'shake head', 'nod', 'stretch'")
        print("   • 'play', 'explore', 'patrol', 'rest'")
        print("   • 'good dog' (praise), 'bad dog' (scold)")
        print("   • 'stop' (emergency)")
        if MAPPING_AVAILABLE:
            print("   • 'calibrate' (wall follow), 'find corner' (corner seek)")
            print("   • 'calibrate sensors' (IMU baseline calibration)")
            print("   • 'explore' (autonomous exploration), 'go to room'")
            print("   • 'show map' (display current map), 'stop navigation'")
            print("   • 'status' (detailed info including localization data)")
    else:
        print("🔇 Voice commands disabled (install: pip install speech_recognition pyaudio)")
    
    print()
    print("💡 Configuration Tips:")
    if CONFIG_AVAILABLE:
        print("   • Edit pidog_config.py file to customize behavior")
        print("   • Use preset configurations: simple, advanced, indoor, explorer") 
        print("   • Voice commands: 'load simple config', 'load advanced config'")
        print("   • Test settings with voice commands before saving changes")
    else:
        print("   • Create pidog_config.py file for full configuration options")
        print("   • Copy from provided pidog_config.py template")
    print("   • Toggle features on/off with ENABLE_* settings")
    print("   • Adjust obstacle thresholds, speeds, and timing")
    print("   • Use voice commands to switch modes during operation")
    print()
    
    ai = AdvancedPiDogAI()
    
    try:
        success = ai.start_ai_system()
        if not success:
            print("Failed to start AI system")
            return 1
            
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())