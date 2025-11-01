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

Author: 7Lynx  
Version: 2025.10.29

Run with: python packmind/orchestrator.py
"""

# ============================================================================
# CONFIGURATION IMPORT
# ============================================================================
from packmind.packmind_config import load_config, validate_config
import logging
logging.getLogger("packmind").info("Configuration system loaded from packmind/packmind_config.py")

# ============================================================================

from pidog import Pidog  # Official hardware library (runs on actual PiDog)
import time
import math
import random
import threading
from enum import Enum
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any
import os
import logging

# Optional feature imports (actual enabling is controlled by loaded config)
VOICE_AVAILABLE = False
MAPPING_AVAILABLE = False

# Voice recognition imports (install with: pip install speech_recognition pyaudio)
try:
    import speech_recognition as sr
    import pyaudio
    VOICE_AVAILABLE = True
    logging.getLogger("packmind").info("Voice recognition modules available")
except ImportError:
    VOICE_AVAILABLE = False
    logging.getLogger("packmind").warning("Voice recognition modules not available. Install: pip install speech_recognition pyaudio")

# SLAM and navigation imports
try:
    try:
        from packmind.mapping.home_mapping import HomeMap, CellType
    except Exception:
        try:
            from mapping.home_mapping import HomeMap, CellType
        except Exception:
            from home_mapping import HomeMap, CellType

    try:
        from packmind.nav.pathfinding import PiDogPathfinder, NavigationController
    except Exception:
        try:
            from nav.pathfinding import PiDogPathfinder, NavigationController
        except Exception:
            from pathfinding import PiDogPathfinder, NavigationController

    try:
        from packmind.localization.sensor_fusion_localization import SensorFusionLocalizer, SurfaceType
    except Exception:
        try:
            from localization.sensor_fusion_localization import SensorFusionLocalizer, SurfaceType
        except Exception:
            from sensor_fusion_localization import SensorFusionLocalizer, SurfaceType

    MAPPING_AVAILABLE = True
    logging.getLogger("packmind").info("Mapping/navigation modules available")
except ImportError as e:
    MAPPING_AVAILABLE = False
    logging.getLogger("packmind").warning(f"Mapping/navigation modules not available: {e}")
    logging.getLogger("packmind").info("Install: pip install numpy")

from packmind.core.context import AIContext
from packmind.behaviors.base_behavior import BaseBehavior
from packmind.core.types import EmotionalState, BehaviorState, SensorReading, EmotionalProfile
from packmind.services.energy_service import EnergyService
from packmind.services.emotion_service import EmotionService
from packmind.services.log_service import LogService
from packmind.services.logging_setup import setup_logging as setup_packmind_logging
from packmind.services.obstacle_service import ObstacleService
from packmind.services.voice_service import VoiceService
from packmind.runtime.voice_runtime import VoiceRuntime
from packmind.services.scanning_service import ScanningService
from packmind.runtime.sensor_monitor import SensorMonitor
from packmind.runtime.scanning_coordinator import ScanningCoordinator
from packmind.behaviors.exploring_behavior import ExploringBehavior
from packmind.behaviors.interacting_behavior import InteractingBehavior
from packmind.behaviors.resting_behavior import RestingBehavior
from packmind.behaviors.playing_behavior import PlayingBehavior
from packmind.core.registry import BehaviorRegistry
from packmind.core.container import ServiceContainer
from packmind.behaviors.idle_behavior import IdleBehavior
from packmind.behaviors.patrolling_behavior import PatrollingBehavior
from packmind.services.safety_watchdog import SafetyWatchdog
from packmind.services.health_monitor import HealthMonitor
from packmind.services.face_recognition_service import FaceRecognitionService
try:
    from packmind.services.face_recognition_lite_service import FaceRecognitionLiteService
except Exception:
    FaceRecognitionLiteService = None
from packmind.services.dynamic_balance_service import DynamicBalanceService
from packmind.services.enhanced_audio_processing_service import EnhancedAudioProcessingService
from packmind.services.calibration_service import CalibrationService

# Note: No local dummy classes are defined for disabled features.
"""
When SLAM, pathfinding, or sensor fusion are disabled or unavailable on this
machine, we simply keep related attributes set to None and gate usage behind
feature flags. This avoids in-file stub classes that confused type checkers
and keeps the code hardware-first.
"""


class Orchestrator:
    """Advanced AI behavior system for PiDog with configurable features"""
    
    def __init__(self, config_preset="default"):
        # Load configuration first so logging can use its settings
        self.config = load_config(config_preset)
        _warnings = validate_config(self.config)

        # Ensure PackMind logging is initialized (idempotent) using config values
        setup_packmind_logging(
            level=getattr(self.config, "LOG_LEVEL", None),
            max_mb=getattr(self.config, "LOG_FILE_MAX_MB", None),
            backups=getattr(self.config, "LOG_FILE_BACKUPS", None),
        )
        self._logger = logging.getLogger("packmind.orchestrator")
        # Emit any configuration warnings once logging is ready
        if _warnings:
            for w in _warnings:
                self._logger.warning(f"Config warning: {w}")

        # Core context object for state management
        self.context = AIContext()

        # Hardware handle (set in initialize on the Pi)
        self.context.dog = None
        
        self.attention_target: Optional[int] = None  # Sound direction
        self.obstacle_memory: List[Tuple[float, float]] = []  # Time, distance pairs
        self.interaction_count = 0
        self.last_interaction_time = 0.0
        
        
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
        self.last_movement_check = time.time()
        self.movement_history = []  # Track if actually moving to detect being stuck
        self.avoidance_strategies = ['turn_smart', 'backup_turn', 'zigzag', 'reverse_escape']
        self.current_strategy_index = 0
        # Watchdog housekeeping
        self._last_watchdog_beat = 0.0
        
        # Walking state tracking
        self.is_walking = False
        self.last_walk_command_time = 0.0
        self.scan_interval = self.config.OBSTACLE_SCAN_INTERVAL
        try:
            min_iv = float(getattr(self.config, "SCAN_INTERVAL_MIN", 0.2))
            max_iv = float(getattr(self.config, "SCAN_INTERVAL_MAX", 2.0))
            self.scan_interval = max(min_iv, min(max_iv, float(self.scan_interval)))
        except Exception:
            pass
        
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
        
        # Mapping system (configurable)
        if self.slam_enabled:
            self.home_map = HomeMap()
            self.pathfinder = PiDogPathfinder(self.home_map)
            if self.autonomous_nav_enabled:
                self.nav_controller = NavigationController(self.pathfinder)
            else:
                self.nav_controller = None
            if self.sensor_fusion_enabled:
                self.sensor_localizer = SensorFusionLocalizer(self.home_map)
            else:
                self.sensor_localizer = None
            self._logger.info("🗺️ HomeMap mapping system initialized")
            if self.autonomous_nav_enabled:
                self._logger.info("🧭 Pathfinding system initialized")
            if self.sensor_fusion_enabled:
                self._logger.info("📍 Sensor fusion localizer initialized")
        else:
            self.home_map = None
            self.pathfinder = None
            self.nav_controller = None
            self.sensor_localizer = None
            self._logger.info("🔇 Advanced features disabled - using simple obstacle avoidance")
        # Localization recovery state
        self._last_localization_recovery_time = 0.0
        
        # Thread/control
        self.running = False
        self.voice_thread = None
        self._voice_runtime: Optional[VoiceRuntime] = None
        self._sensor_monitor: Optional[SensorMonitor] = None
        self._scan_coordinator: Optional[ScanningCoordinator] = None
        self._health_monitor: Optional[HealthMonitor] = None
        
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
            "stop": lambda: self.context.dog.body_stop(),
            
            # Action commands  
            "wag tail": lambda: self.context.dog.do_action("wag_tail", step_count=5, speed=self.config.SPEED_FAST),
            "shake head": lambda: self.context.dog.do_action("shake_head", step_count=3, speed=self.config.SPEED_NORMAL),
            "nod": lambda: self.context.dog.do_action("head_up_down", step_count=3, speed=self.config.SPEED_SLOW),
            "stretch": lambda: self.context.dog.do_action("stretch", speed=self.config.SPEED_SLOW),
            
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

        # Initialize services and behaviors
        self.energy_service = EnergyService()
        self.emotion_service = EmotionService(self.emotion_profiles)
        self.log_service = LogService(
            enabled=self.patrol_logging_enabled,
            file_path=self.log_file_path,
            session_id=self.patrol_session_id,
        )
        try:
            self.log_service.max_entries = int(getattr(self.config, "LOG_MAX_ENTRIES", self.log_service.max_entries))
        except Exception:
            pass
        # Safety watchdog (heartbeat-based)
        self.watchdog = SafetyWatchdog(timeout_s=float(getattr(self.config, "WATCHDOG_TIMEOUT_S", 3.0)), logger=None)
        # Initialize DI container for selected services
        self._container = ServiceContainer(self.context, self.config)
        self._container.build_defaults()
        self.obstacle_service = self._container.obstacle()
        # Orientation service (if enabled in config)
        try:
            self.orientation_service = self._container.orientation()
        except Exception:
            self.orientation_service = None
        self.voice_service = VoiceService()
        self.voice_service.set_wake_word(self.wake_word)
        # Register current voice commands with the voice service
        for k, v in self.voice_commands.items():
            try:
                self.voice_service.register(k, v)
            except Exception:
                pass

        # Behavior registry and default behavior
        _registry = BehaviorRegistry()
        _registry.register(BehaviorState.IDLE, IdleBehavior())
        _registry.register(BehaviorState.EXPLORING, ExploringBehavior())
        _registry.register(BehaviorState.INTERACTING, InteractingBehavior())
        _registry.register(BehaviorState.RESTING, RestingBehavior())
        _registry.register(BehaviorState.PLAYING, PlayingBehavior())
        _registry.register(BehaviorState.PATROLLING, PatrollingBehavior())
        self.behaviors = _registry.all()
        self.context.current_behavior = self.behaviors[BehaviorState.IDLE]
        self.context.behavior_state = BehaviorState.IDLE
        # Scanning service from container
        self.scanning_service = self._container.scanning()
        # Calibration service (unified path) – dog may be None until initialize()
        try:
            self.calibration_service = CalibrationService(
                slam_system=self.home_map,
                scanning_service=self.scanning_service,
                dog=self.context.dog,
                logger=self._logger,
            )
        except Exception:
            self.calibration_service = None

        # Initialize new AI services
        # Face recognition backend selection
        try:
            backend = str(getattr(self.config, "FACE_BACKEND", "default")).lower()
        except Exception:
            backend = "default"
        if backend == "lite" and FaceRecognitionLiteService is not None:
            self.face_recognition_service = FaceRecognitionLiteService(self.config)
            self._logger.info("Using lite face recognition backend (OpenCV Haar + optional LBPH)")
        else:
            self.face_recognition_service = FaceRecognitionService(self.config)
            if backend == "lite" and FaceRecognitionLiteService is None:
                self._logger.warning("FACE_BACKEND=lite requested but lite service unavailable; falling back to default backend")
        self.dynamic_balance_service = DynamicBalanceService(self.config)
        self.enhanced_audio_service = EnhancedAudioProcessingService(self.config)

        # Set up service callbacks and integration
        self._setup_service_callbacks()

    # Compatibility properties mapping legacy attributes to context
    @property
    def dog(self):
        return self.context.dog

    @dog.setter
    def dog(self, value):
        self.context.dog = value

    @property
    def energy_level(self) -> float:
        return self.context.energy_level

    @energy_level.setter
    def energy_level(self, value: float) -> None:
        self.context.energy_level = value

    @property
    def current_emotion(self) -> EmotionalState:
        return self.context.current_emotion

    @current_emotion.setter
    def current_emotion(self, value: EmotionalState) -> None:
        self.context.current_emotion = value

    @property
    def previous_emotion(self) -> EmotionalState:
        return self.context.previous_emotion

    @previous_emotion.setter
    def previous_emotion(self, value: EmotionalState) -> None:
        self.context.previous_emotion = value

    @property
    def current_behavior(self) -> BehaviorState:
        return self.context.behavior_state

    @current_behavior.setter
    def current_behavior(self, value: BehaviorState) -> None:
        self.context.behavior_state = value
    
    def _setup_service_callbacks(self):
        """Set up integration between services"""
        try:
            # Store references to services for integration
            self._last_face_detection_time = 0
            self._last_balance_state = None
            self._last_audio_check_time = 0
            
            # Integration will be handled through periodic checks in the main loop
            self._logger.info("Service integration initialized - will check services periodically")
                
        except Exception as e:
            self._logger.error(f"Error setting up service integration: {e}")
    
    def _check_service_integration(self):
        """Check services for updates and integrate with behaviors"""
        try:
            current_time = time.time()
            
            # Check face recognition service
            if (hasattr(self, 'face_recognition_service') and 
                self.face_recognition_service and 
                self.config.ENABLE_FACE_RECOGNITION and
                current_time - self._last_face_detection_time > 2.0):  # Check every 2 seconds
                
                try:
                    results = self.face_recognition_service.detect_and_recognize()
                    # Support both default (dlib) and lite (OpenCV) result schemas
                    if not results:
                        pass
                    elif 'faces_detected' in results:
                        # Default backend schema
                        if results.get('faces_detected', 0) > 0:
                            recognized_faces = results.get('recognized_faces', [])
                            if recognized_faces:
                                person_name = recognized_faces[0].get('name', 'Unknown')
                                confidence = recognized_faces[0].get('confidence', 0.0)
                                self._logger.info(f"Face recognized: {person_name} (confidence: {confidence:.2f})")
                                self.set_emotion(EmotionalState.HAPPY)
                                self._log_patrol_event("FACE_RECOGNITION", f"Recognized {person_name}", {
                                    "confidence": confidence
                                })
                            else:
                                self._logger.info("Unknown face detected")
                                self.set_emotion(EmotionalState.EXCITED)
                                self._log_patrol_event("FACE_RECOGNITION", "Unknown face detected")
                    elif 'faces' in results:
                        faces = results.get('faces') or []
                        if faces:
                            known_faces = [f for f in faces if f.get('known')]
                            if known_faces:
                                f0 = known_faces[0]
                                person_name = f0.get('name', 'Unknown')
                                confidence = float(f0.get('confidence', 0.0) or 0.0)
                                self._logger.info(f"Face recognized (lite): {person_name} (confidence: {confidence:.2f})")
                                self.set_emotion(EmotionalState.HAPPY)
                                self._log_patrol_event("FACE_RECOGNITION", f"Recognized {person_name}", {
                                    "confidence": confidence
                                })
                            else:
                                self._logger.info("Unknown face detected (lite)")
                                self.set_emotion(EmotionalState.EXCITED)
                                self._log_patrol_event("FACE_RECOGNITION", "Unknown face detected")
                    
                    self._last_face_detection_time = current_time
                except Exception as e:
                    self._logger.error(f"Error checking face recognition service: {e}")
            
            # Check dynamic balance service
            if (hasattr(self, 'dynamic_balance_service') and 
                self.dynamic_balance_service and
                self.config.ENABLE_DYNAMIC_BALANCE):
                
                try:
                    balance_state, reading = self.dynamic_balance_service.get_current_balance_state()
                    
                    # Check for state changes
                    if balance_state != self._last_balance_state:
                        from packmind.services.dynamic_balance_service import BalanceState
                        
                        if balance_state == BalanceState.CRITICAL:
                            self._logger.warning("Critical balance detected")
                            self.set_emotion(EmotionalState.ALERT)
                            self._log_patrol_event("BALANCE", "Critical balance state", {
                                "state": balance_state.value,
                                "roll": reading.roll if reading else None,
                                "pitch": reading.pitch if reading else None
                            })
                        elif balance_state == BalanceState.STABLE and self._last_balance_state in [BalanceState.CRITICAL, BalanceState.UNSTABLE]:
                            self._logger.info("Balance recovered")
                            self.set_emotion(EmotionalState.CALM)
                            self._log_patrol_event("BALANCE", "Balance recovered")
                        
                        self._last_balance_state = balance_state
                        
                except Exception as e:
                    self._logger.error(f"Error checking balance service: {e}")
            
            # Check enhanced audio service
            if (hasattr(self, 'enhanced_audio_service') and 
                self.enhanced_audio_service and
                self.config.ENABLE_ENHANCED_AUDIO and
                current_time - self._last_audio_check_time > 1.0):  # Check every second
                
                try:
                    # Check if voice is currently detected
                    if self.enhanced_audio_service.is_voice_detected():
                        audio_level = self.enhanced_audio_service.get_current_audio_level()
                        self._logger.info(f"Voice activity detected: level={audio_level:.3f}")
                        self.set_emotion(EmotionalState.EXCITED)
                        self._log_patrol_event("AUDIO", "Voice activity detected", {
                            "audio_level": audio_level
                        })
                    
                    # Check for loud noises
                    audio_level = self.enhanced_audio_service.get_current_audio_level()
                    if audio_level > self.config.AUDIO_LOUD_NOISE_THRESHOLD:
                        self._logger.warning(f"Loud noise detected: level={audio_level:.3f}")
                        self.set_emotion(EmotionalState.ALERT)
                        self._log_patrol_event("AUDIO", "Loud noise detected", {
                            "audio_level": audio_level
                        })
                    
                    # Check active sound sources
                    active_sources = self.enhanced_audio_service.get_active_sources()
                    if active_sources:
                        for source_id, source in active_sources.items():
                            if hasattr(self, '_logged_sources'):
                                if source_id not in self._logged_sources:
                                    self._logger.info(f"New sound source tracked: {source.source_type.value} at {source.direction_degrees:.0f}°")
                                    self._log_patrol_event("AUDIO", "New sound source", {
                                        "source_type": source.source_type.value,
                                        "direction": source.direction_degrees,
                                        "intensity": source.intensity
                                    })
                                    self._logged_sources.add(source_id)
                            else:
                                self._logged_sources = {source_id}
                    
                    self._last_audio_check_time = current_time
                    
                except Exception as e:
                    self._logger.error(f"Error checking audio service: {e}")
                    
        except Exception as e:
            self._logger.error(f"Error in service integration check: {e}")
    
    def initialize(self) -> bool:
        """Initialize PiDog with error handling"""
        try:
            self._logger.info("Initializing Advanced PiDog AI...")
            try:
                self.context.dog = Pidog()
            except Exception as hw_err:
                self._logger.error(f"Pidog hardware init failed: {hw_err}")
                self._log_patrol_event("ERROR", f"Hardware init failed: {hw_err}")
                return False
            
            # Startup sequence
            self.context.dog.do_action("stand", speed=60)
            self.context.dog.wait_all_done()

            # Update calibration service with live dog handle (if created earlier)
            try:
                if getattr(self, "calibration_service", None) is not None:
                    self.calibration_service.dog = self.context.dog
                    self.calibration_service.slam_system = self.home_map
                    self.calibration_service.scanning_service = self.scanning_service
            except Exception:
                pass
            
            # Set initial emotional state
            self.set_emotion(EmotionalState.CALM)
            
            # Initialize patrol log
            self._log_patrol_event("SYSTEM", "PiDog AI system initialized", {
                "energy_level": self.context.energy_level,
                "emotional_state": self.context.current_emotion.value,
                "behavior_state": self.context.behavior_state.value,
                "slam_enabled": self.slam_enabled
            })
            
            # Start mapping system (no legacy SLAM system)
            self._log_patrol_event("SLAM", "Home mapping system started")
                
            # Start sensor fusion localization
            if self.sensor_localizer:
                self.sensor_localizer.start_localization()
                self._log_patrol_event("LOCALIZATION", "Sensor fusion localization started")
            
            # Start new AI services
            if hasattr(self, 'face_recognition_service') and self.config.ENABLE_FACE_RECOGNITION:
                try:
                    self.face_recognition_service.start()
                    self._log_patrol_event("FACE_RECOGNITION", "Face recognition service started")
                    self._logger.info("Face recognition service started")
                except Exception as e:
                    self._logger.error(f"Failed to start face recognition service: {e}")
            
            if hasattr(self, 'dynamic_balance_service') and self.config.ENABLE_DYNAMIC_BALANCE:
                try:
                    self.dynamic_balance_service.start()
                    self._log_patrol_event("BALANCE", "Dynamic balance service started")
                    self._logger.info("Dynamic balance service started")
                except Exception as e:
                    self._logger.error(f"Failed to start dynamic balance service: {e}")
            
            if hasattr(self, 'enhanced_audio_service') and self.config.ENABLE_ENHANCED_AUDIO:
                try:
                    self.enhanced_audio_service.start()
                    self._log_patrol_event("AUDIO", "Enhanced audio processing service started")
                    self._logger.info("Enhanced audio processing service started")
                except Exception as e:
                    self._logger.error(f"Failed to start enhanced audio service: {e}")
            
            self._logger.info("PiDog AI initialized successfully")
            return True
            
        except Exception as e:
            self._logger.error(f"Initialization failed: {e}")
            self._log_patrol_event("ERROR", f"Initialization failed: {e}")
            return False
    
    def start_ai_system(self):
        """Start the AI behavior system"""
        if not self.initialize():
            return False
            
        self.running = True
        
        # Start sensor monitor (configurable rate)
        try:
            self._sensor_monitor = SensorMonitor(
                read_once=self._read_sensors_once,
                on_reading=self._on_sensor_reading,
                rate_hz=float(getattr(self.config, "SENSOR_MONITOR_RATE_HZ", 20.0)),
                backoff_on_error_s=float(getattr(self.config, "SENSOR_MONITOR_BACKOFF_ON_ERROR_S", 0.0)),
                logger=self._logger,
            )
            self._sensor_monitor.start()
        except Exception as e:
            self._logger.warning(f"Sensor monitor unavailable: {e}")
        
        # Start intelligent scanning thread (if enabled)
        if self.intelligent_scanning_enabled:
            self._logger.info("Starting intelligent obstacle scanning system...")
            try:
                # Map config to scanning parameters
                try:
                    _range = int(getattr(self.config, "HEAD_SCAN_RANGE", 50))
                except Exception:
                    _range = 50
                try:
                    _samples = int(getattr(self.config, "SCAN_SAMPLES", 3))
                except Exception:
                    _samples = 3
                try:
                    _settle = float(getattr(self.config, "SCAN_DEBOUNCE_S", 0.3))
                except Exception:
                    _settle = 0.3

                self._scan_coordinator = ScanningCoordinator(
                    scanning_service=self.scanning_service,
                    should_scan=self._should_perform_scan,
                    on_scan=self._on_scan_results,
                    interval_s=0.2,  # 5Hz polling of scan predicate
                    logger=self._logger,
                    left_deg=_range,
                    right_deg=_range,
                    settle_s=_settle,
                    samples=_samples,
                )
                self._scan_coordinator.start()
            except Exception as e:
                self._logger.warning(f"Scanning coordinator unavailable: {e}")
        else:
            self._logger.info("Intelligent scanning disabled by configuration")

        # Start health monitor (configurable interval)
        try:
            self._health_monitor = HealthMonitor(interval_s=float(getattr(self.config, "HEALTH_MONITOR_INTERVAL_S", 5.0)), on_sample=self._on_health_sample)
            self._health_monitor.start()
        except Exception as e:
            self._logger.warning(f"Health monitor unavailable: {e}")
        
        # Start voice recognition runtime if available
        if self.voice_enabled:
            self._logger.info("Starting voice recognition system...")
            self._logger.info(f"Say '{self.wake_word}' followed by a command")
            try:
                self._voice_runtime = VoiceRuntime(
                    voice_service=self.voice_service,
                    wake_word=self.wake_word,
                    on_command=self._process_voice_command,
                    mic_index=int(getattr(self.config, "VOICE_MIC_INDEX", 0)),
                    wake_timeout_s=float(getattr(self.config, "VOICE_WAKE_TIMEOUT_S", 5.0)),
                    vad_sensitivity=float(getattr(self.config, "VOICE_VAD_SENSITIVITY", 0.5)),
                    language=str(getattr(self.config, "VOICE_LANGUAGE", "en-US")),
                    noise_suppression=bool(getattr(self.config, "VOICE_NOISE_SUPPRESSION", True)),
                    command_timeout_s=float(getattr(self.config, "VOICE_COMMAND_TIMEOUT", 5.0)),
                    logger=self._logger,
                )
                self._voice_runtime.start()
            except Exception as e:
                self._logger.warning(f"Voice recognition unavailable: {e}")
        else:
            self._logger.info("Voice recognition disabled (missing dependencies)")
        
        try:
            self._logger.info("AI system active - Press Ctrl+C to stop")
            self._logger.info("Try touching, making sounds, or putting objects nearby...")
            
            # Main AI loop
            while self.running:
                self._ai_behavior_loop()
                # Periodic localization health check and active recovery (fast no-op if disabled)
                try:
                    self._check_localization_health()
                except Exception:
                    pass
                time.sleep(0.1)  # 10Hz main loop
                
        except KeyboardInterrupt:
            self._logger.info("AI system stopping...")
        finally:
            self._shutdown()
            
        return True
    
    def _log_patrol_event(self, event_type: str, description: str, data: Optional[dict] = None):
        """Log patrol events with timestamp and details (if logging enabled)"""
        if not self.patrol_logging_enabled:
            return  # Skip logging if disabled
            
        # Centralized logging via LogService
        try:
            self.log_service.event(
                event_type,
                description,
                behavior_state=self.context.behavior_state.value,
                emotional_state=(self.context.current_emotion.value if self.emotional_system_enabled else "disabled"),
                energy_level=self.context.energy_level,
                scan_data={
                    "forward": self.obstacle_scan_data['forward'],
                    "left": self.obstacle_scan_data['left'],
                    "right": self.obstacle_scan_data['right'],
                },
                data=data,
            )
        except Exception:
            pass

        # Maintain legacy in-memory list for now (to be removed later)
        try:
            timestamp = time.time()
            elapsed = timestamp - self.patrol_start_time
            self.patrol_log.append({
                "session_id": self.patrol_session_id,
                "timestamp": timestamp,
                "elapsed_time": elapsed,
                "event_type": event_type,
                "description": description,
                "behavior_state": self.context.behavior_state.value,
                "emotional_state": self.context.current_emotion.value if self.emotional_system_enabled else "disabled",
                "energy_level": round(self.context.energy_level, 3),
                "scan_data": {
                    "forward": round(self.obstacle_scan_data['forward'], 1),
                    "left": round(self.obstacle_scan_data['left'], 1),
                    "right": round(self.obstacle_scan_data['right'], 1),
                },
                "additional_data": data or {},
            })
            if len(self.patrol_log) > self.config.LOG_MAX_ENTRIES:
                self.patrol_log = self.patrol_log[-self.config.LOG_MAX_ENTRIES:]
        except Exception:
            pass
    
    # Sensor/scan loops are managed by SensorMonitor and ScanningCoordinator
    
    def _should_perform_scan(self):
        """Determine if we should perform a scan based on current activity"""
        current_time = time.time()
        
        # Always scan if we haven't scanned recently and we're moving
        if current_time - self.obstacle_scan_data['last_scan_time'] > self.scan_interval:
            # Check if we're in movement behaviors
            if (self.context.behavior_state in [BehaviorState.PATROLLING, BehaviorState.EXPLORING] or
                self.is_walking or 
                current_time - self.last_walk_command_time < 3.0):
                return True
                
        return False
    
    def _perform_three_way_scan(self):
        """Use ScanningService and update mapping/localization/logging."""
        self._logger.debug("Performing 3-way obstacle scan...")
        self._log_patrol_event("SCAN_START", "Beginning 3-way ultrasonic scan")
        # Use configured scan parameters
        try:
            _range = int(getattr(self.config, "HEAD_SCAN_RANGE", 50))
        except Exception:
            _range = 50
        try:
            _samples = int(getattr(self.config, "SCAN_SAMPLES", 3))
        except Exception:
            _samples = 3
        try:
            _settle = float(getattr(self.config, "SCAN_DEBOUNCE_S", 0.3))
        except Exception:
            _settle = 0.3
        scan_results = self.scanning_service.scan_three_way(left_deg=_range, right_deg=_range, settle_s=_settle, samples=_samples)
        self._log_patrol_event("SCAN_COMPLETE", "3-way scan completed", {
            "scan_results": scan_results,
            "threats_detected": [d for d, dist in scan_results.items() if dist < 40],
        })
        # SLAM system removed; update sensor_localizer if present
        if self.sensor_localizer:
            angle_mapping = {'forward': 0.0, 'left': 45.0, 'right': -45.0}
            for direction, distance in scan_results.items():
                if distance > 0 and direction in angle_mapping:
                    self.sensor_localizer.update_ultrasonic(distance, angle_mapping[direction])
        return scan_results

    def _check_localization_health(self) -> None:
        """Monitor localization confidence and trigger an active recovery sweep when low.

        Fast no-op when fusion disabled or recovery disabled.
        """
        # Preconditions
        if not self.sensor_localizer:
            return
        try:
            if not bool(getattr(self.config, "LOCALIZATION_ACTIVE_RECOVERY", True)):
                return
        except Exception:
            # If config missing, default to enabled
            pass
        # Sample localization status
        status = {}
        try:
            status = self.sensor_localizer.get_localization_status()
        except Exception:
            return
        pf = status.get("particle_filter", {}) if isinstance(status, dict) else {}
        conf = float(pf.get("confidence", 0.0)) if isinstance(pf, dict) else 0.0
        # Thresholds and pacing
        try:
            low_thr = float(getattr(self.config, "LOCALIZATION_CONFIDENCE_LOW", 0.35))
        except Exception:
            low_thr = 0.35
        try:
            min_iv = float(getattr(self.config, "LOCALIZATION_RECOVERY_MIN_INTERVAL_S", 8.0))
        except Exception:
            min_iv = 8.0
        now = time.time()
        if conf < low_thr and (now - self._last_localization_recovery_time) >= min_iv:
            self._perform_localization_recovery(status_before=status)
            self._last_localization_recovery_time = now

    def _perform_localization_recovery(self, *, status_before: Optional[dict] = None) -> None:
        """Perform a short ultrasonic sweep and update the particle filter to recover confidence."""
        if not self.sensor_localizer:
            return
        if not hasattr(self, "scanning_service") or self.scanning_service is None:
            # Cannot sweep without scanning service
            return
        # Parameters
        try:
            left = int(getattr(self.config, "LOCALIZATION_RECOVERY_SWEEP_LEFT", getattr(self.config, "HEAD_SCAN_RANGE", 50)))
        except Exception:
            left = 50
        try:
            right = int(getattr(self.config, "LOCALIZATION_RECOVERY_SWEEP_RIGHT", getattr(self.config, "HEAD_SCAN_RANGE", 50)))
        except Exception:
            right = 50
        try:
            step = int(getattr(self.config, "LOCALIZATION_RECOVERY_STEP_DEG", 10))
        except Exception:
            step = 10
        try:
            sweeps = int(getattr(self.config, "LOCALIZATION_RECOVERY_SWEEPS", 1))
        except Exception:
            sweeps = 1

        # Build angle list from -right .. +left inclusive
        angles = []
        a = -int(right)
        end = int(left)
        step = max(1, int(step))
        while a <= end:
            angles.append(int(a))
            a += step
        if angles and angles[-1] != end:
            angles.append(end)

        self._log_patrol_event("LOCALIZATION_RECOVERY", "Starting active relocalization sweep", {
            "angles": angles,
            "sweeps": sweeps,
            "status_before": status_before or {},
        })
        # Perform sweeps and feed readings
        for _ in range(max(1, sweeps)):
            try:
                samples = self.scanning_service.sweep_scan(angles)
            except Exception:
                samples = {}
            # samples: Dict[int, float] as angle->distance
            for k, dist in samples.items():
                try:
                    ang = float(k)
                except Exception:
                    # keys may already be ints
                    ang = float(k) if isinstance(k, (int, float)) else 0.0
                try:
                    d = float(dist)
                except Exception:
                    continue
                if d <= 0:
                    continue
                try:
                    self.sensor_localizer.update_ultrasonic(d, ang)
                except Exception:
                    pass
            # Small pause between sweeps
            time.sleep(0.2)

        # Report after status
        try:
            after = self.sensor_localizer.get_localization_status()
        except Exception:
            after = None
        self._log_patrol_event("LOCALIZATION_RECOVERY_DONE", "Active relocalization completed", {
            "status_after": after or {},
        })
    
    # Deprecated: legacy scan/avoid/stuck helpers removed in favor of ObstacleService
    
    def _adjust_walking_speed(self, speed_factor):
        """Adjust current walking speed (placeholder for implementation)"""
        # This would require more complex action queue management
        # For now, just note the speed adjustment
        self._logger.info(f"Reducing movement speed to {int(speed_factor*100)}%")
    
    def _get_appropriate_turn_speed(self):
        """Get appropriate turn speed based on current energy and activity level"""
        # Determine current activity level
        if self.context.energy_level > 0.7:
            return self.config.SPEED_TURN_FAST
        elif self.context.energy_level > 0.4:
            return self.config.SPEED_TURN_NORMAL
        else:
            return self.config.SPEED_TURN_SLOW
    
    def _get_appropriate_walk_speed(self):
        """Get appropriate walk speed based on current energy level"""
        if self.context.energy_level > 0.7:
            return self.config.SPEED_FAST
        elif self.context.energy_level > 0.4:
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
        
    
    def _ai_behavior_loop(self):
        """Main AI decision-making loop"""
        current_time = time.time()
        # Update emotional state periodically
        if current_time - self.last_emotion_update > 2.0:
            self._update_emotional_state()
            self.last_emotion_update = current_time
        # State machine behavior
        if self.context.behavior_state == BehaviorState.PATROLLING:
            self._patrolling_behavior()  # ENHANCED: Intelligent patrol with logging
        else:
            try:
                behavior = self.behaviors.get(self.context.behavior_state)
                if behavior:
                    behavior.execute(self.context)
            except Exception:
                pass
        # Integrate dynamic obstacle fading into the main loop
        if self.slam_enabled and self.home_map is not None:
            try:
                self.home_map.fade_dynamic_obstacles()
            except Exception as e:
                self._logger.warning(f"Dynamic obstacle fading error: {e}")
        # Check for behavior state transitions
        self._evaluate_behavior_transitions(current_time)
        # Check service integration
        self._check_service_integration()
        # Watchdog heartbeat and timeout action (config-driven)
        try:
            hb_interval = float(getattr(self.config, "WATCHDOG_HEARTBEAT_INTERVAL_S", 0.5))
        except Exception:
            hb_interval = 0.5
        try:
            action = str(getattr(self.config, "WATCHDOG_ACTION", "stop_and_crouch"))
        except Exception:
            action = "stop_and_crouch"
        try:
            if (current_time - self._last_watchdog_beat) >= hb_interval:
                self.watchdog.heartbeat()
                self._last_watchdog_beat = current_time
            # Check timeout and take configured safety action
            if self.watchdog.is_timed_out():
                self._logger.warning("⚠️ Watchdog timeout detected - executing safety action")
                try:
                    self.watchdog.arm_emergency()
                except Exception:
                    pass
                try:
                    self.watchdog.emergency_stop(self.context.dog)
                except Exception:
                    pass
                if action == "power_down":
                    try:
                        # Attempt a graceful power down if supported
                        if hasattr(self.context.dog, "power_down"):
                            self.context.dog.power_down()
                    except Exception:
                        pass
        except Exception:
            pass

    # --- Sensor monitor integration ---
    def _read_sensors_once(self) -> SensorReading:
        return SensorReading(
            distance=self.context.dog.ultrasonic.read_distance(),
            touch=self.context.dog.dual_touch.read(),
            sound_detected=self.context.dog.ears.isdetected(),
            sound_direction=self.context.dog.ears.read() if self.context.dog.ears.isdetected() else -1,
            acceleration=self.context.dog.accData,
            gyroscope=self.context.dog.gyroData,
            timestamp=time.time(),
        )

    def _on_sensor_reading(self, reading: SensorReading) -> None:
        try:
            # Update heading estimate first (if available)
            try:
                if self.orientation_service is not None:
                    self.orientation_service.update_from_reading(reading)
            except Exception:
                pass
            self._process_sensor_data(reading)
            # Movement tracking and stuck detection at ~5Hz
            if reading.timestamp - self.last_movement_check > 0.2:
                try:
                    self.obstacle_service.track_movement(self.context, self.config)
                    self.obstacle_service.check_if_stuck(self.context, self.config)
                except Exception:
                    pass
                self.last_movement_check = reading.timestamp
        except Exception as e:
            self._logger.warning(f"⚠️ Sensor processing error: {e}")

    # --- Scanning coordinator integration ---
    def _on_scan_results(self, scan_results: Dict[str, float]) -> None:
        try:
            current_time = time.time()
            self._log_patrol_event(
                "SCAN_COMPLETE",
                "3-way scan completed",
                {
                    "scan_results": scan_results,
                    "threats_detected": [d for d, dist in scan_results.items() if dist < 40],
                },
            )
            # Update obstacle cache
            self.obstacle_scan_data.update({
                'forward': float(scan_results.get('forward', self.obstacle_scan_data['forward'])),
                'left': float(scan_results.get('left', self.obstacle_scan_data['left'])),
                'right': float(scan_results.get('right', self.obstacle_scan_data['right'])),
                'last_scan_time': current_time,
            })
            # Threat analysis and immediate reactions
            threat = None
            try:
                threat = self.obstacle_service.analyze_scan(scan_results, self.config)
            except Exception:
                pass
            if threat == "IMMEDIATE":
                self._log_patrol_event(
                    "THREAT_IMMEDIATE",
                    f"Immediate threat detected at {scan_results.get('forward', 0):.1f}cm",
                    scan_results,
                )
                turn_speed = self._get_appropriate_turn_speed()
                try:
                    self.obstacle_service.maybe_avoid(self.context, scan_results, self.config, turn_speed)
                except Exception:
                    pass
            elif threat == "APPROACHING":
                self._log_patrol_event(
                    "THREAT_APPROACHING",
                    f"Approaching obstacle at {scan_results.get('forward', 0):.1f}cm",
                    scan_results,
                )
                if self.is_walking:
                    self._adjust_walking_speed(0.7)
            # Movement tracking handled by sensor monitor cadence
        except Exception as e:
            self._logger.warning(f"⚠️ Scan processing error: {e}")
    
    def _on_health_sample(self, sample: Dict[str, Any]) -> None:
        """Receive periodic system health samples and adjust behavior conservatively.

        - Emits a HEALTH event with load, temperature, memory, and current scan interval
        - Applies a simple degrade policy to increase scan interval under high load/temperature
        """
        try:
            load = float(sample.get("load_1m") or 0.0)
            cores = max(1, int(sample.get("cpu_cores") or (os.cpu_count() or 1)))
            temp = sample.get("cpu_temp_c")
            mem_used = sample.get("mem_used_pct")
            degrade = False
            # Load per core threshold
            if load > cores * float(getattr(self.config, "HEALTH_LOAD_PER_CORE_WARN_MULTIPLIER", 1.5)):
                degrade = True
            # Temperature threshold
            if isinstance(temp, (int, float)) and temp > float(getattr(self.config, "HEALTH_TEMP_WARN_C", 70.0)):
                degrade = True
            # Memory threshold
            if isinstance(mem_used, (int, float)) and mem_used > float(getattr(self.config, "HEALTH_MEM_USED_WARN_PCT", 85.0)):
                degrade = True

            baseline = self.config.OBSTACLE_SCAN_INTERVAL
            if degrade:
                mult = float(getattr(self.config, "HEALTH_SCAN_INTERVAL_MULTIPLIER", 2.0))
                delta = float(getattr(self.config, "HEALTH_SCAN_INTERVAL_ABS_DELTA", 1.0))
                self.scan_interval = min(baseline * mult, baseline + delta)
            else:
                self.scan_interval = baseline

            # Clamp to configured bounds
            try:
                min_iv = float(getattr(self.config, "SCAN_INTERVAL_MIN", 0.2))
                max_iv = float(getattr(self.config, "SCAN_INTERVAL_MAX", 2.0))
                self.scan_interval = max(min_iv, min(max_iv, float(self.scan_interval)))
            except Exception:
                pass

            self._log_patrol_event(
                "HEALTH",
                "System health sample",
                {
                    "load_1m": sample.get("load_1m"),
                    "cpu_temp_c": temp,
                    "mem_used_pct": mem_used,
                    "cpu_cores": cores,
                    "scan_interval": self.scan_interval,
                    "degraded": degrade,
                },
            )
        except Exception:
            # Avoid cascading failures from health sampling
            pass
    
    def _handle_touch_interaction(self, touch_type: str, timestamp: float):
        """Handle touch with learning and emotional response"""
        self._logger.info(f"👋 Touch detected: {touch_type}")
        
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
            self.context.dog.speak("pant", volume=70)
        elif preference > 0.3:
            self.set_emotion(EmotionalState.CALM)
        else:
            self.set_emotion(EmotionalState.CONFUSED)
            
        # Movement response with energy consideration
        energy_factor = self.context.energy_level * preference
        
        if touch_type in ["LS", "RS"]:  # Swipes
            direction = "turn_right" if touch_type == "LS" else "turn_left"
            speed = int(50 + energy_factor * 40)
            self.context.dog.do_action(direction, step_count=1, speed=speed)
            
        elif energy_factor > 0.5:
            # High energy response
            self.context.dog.do_action("wag_tail", step_count=int(5 + energy_factor * 10), speed=90)
            
        # Switch to interaction behavior
        self.set_behavior(BehaviorState.INTERACTING)
    
    def _handle_emergency_obstacle(self, distance: float, timestamp: float):
        """Handle emergency obstacle detection (very close obstacles)"""
        self._logger.warning(f"🚨 EMERGENCY: Obstacle at {distance:.1f}cm - immediate stop!")
        
        # Immediate stop
        self.context.dog.body_stop()
        
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
            self.context.dog.speak("confused_2", volume=60)
            # Trigger advanced avoidance if too many emergencies
            try:
                self.obstacle_service._execute_advanced_avoidance_strategy(self.context, self.config)
            except Exception:
                pass
        else:
            self.set_emotion(EmotionalState.ALERT)
            self.context.dog.speak("single_bark_1", volume=70)
            
        # Let the intelligent scanning system handle the avoidance
        # Just switch to avoiding state temporarily
        self.set_behavior(BehaviorState.AVOIDING)
    
    def _handle_sound_attention(self, direction: int, timestamp: float):
        """ENHANCED: Advanced sound tracking with head movement and body turning (config-driven)."""
        self._logger.info(f"👂 Sound from {direction}° - investigating!")

        self.attention_target = direction
        self.set_emotion(EmotionalState.ALERT)

        # Configurable parameters
        try:
            sensitivity = float(getattr(self.config, "SOUND_HEAD_SENSITIVITY", 2.5))
        except Exception:
            sensitivity = 2.5
        try:
            body_turn_threshold = float(getattr(self.config, "SOUND_BODY_TURN_THRESHOLD", 45.0))
        except Exception:
            body_turn_threshold = 45.0
        try:
            energy_min = float(getattr(self.config, "SOUND_RESPONSE_ENERGY_MIN", 0.4))
        except Exception:
            energy_min = 0.4

        # Log sound detection
        self._log_patrol_event(
            "SOUND_DETECTED",
            f"Sound detected from {direction}°",
            {
                "sound_direction": direction,
                "previous_attention": self.attention_target,
                "response_planned": "head_and_body_turn" if abs(direction) > body_turn_threshold else "head_turn_only",
                "sensitivity": sensitivity,
                "threshold": body_turn_threshold,
            },
        )

        # Calculate head movement
        profile = self.emotion_profiles[self.context.current_emotion]
        responsiveness = profile.head_responsiveness * self.context.energy_level

        # Convert sound direction to head yaw using configured sensitivity
        if direction > 180:
            yaw = (direction - 360) / max(0.1, sensitivity)
        else:
            yaw = direction / max(0.1, sensitivity)
        yaw = max(-80, min(80, yaw))
        yaw *= responsiveness

        # Turn head first, then body if sound is far to the side and enough energy
        self.context.dog.head_move([[int(yaw), 0, 0]], speed=int(70 + responsiveness * 30))

        if abs(yaw) > body_turn_threshold and self.context.energy_level > energy_min:
            self._logger.debug("🔄 Turning body to face sound source")
            # Use IMU-based small turn when available; fallback to one step
            try:
                dps = float(getattr(self.config, "TURN_DEGREES_PER_STEP", 15.0))
            except Exception:
                dps = 15.0
            deg = float(dps if yaw > 0 else -dps)
            tol = float(getattr(self.config, "ORIENTATION_TURN_TOLERANCE_DEG", 5.0))
            tout = float(getattr(self.config, "ORIENTATION_MAX_TURN_TIME_S", 3.0))
            if getattr(self, "orientation_service", None) is not None:
                self._turn_by_angle(deg, 70, tolerance_deg=tol, timeout_s=tout)
            else:
                if yaw > 0:
                    self.context.dog.do_action("turn_left", step_count=1, speed=70)
                else:
                    self.context.dog.do_action("turn_right", step_count=1, speed=70)

            # Reset head to center after turn
            time.sleep(1)
            self.context.dog.head_move([[0, 0, 0]], speed=60)

        # Vocal responses with configurable volumes
        try:
            vol_default = int(getattr(self.config, "VOICE_VOLUME_DEFAULT", 70))
        except Exception:
            vol_default = 70
        try:
            vol_excited = int(getattr(self.config, "VOICE_VOLUME_EXCITED", 80))
        except Exception:
            vol_excited = 80
        try:
            vol_quiet = int(getattr(self.config, "VOICE_VOLUME_QUIET", 40))
        except Exception:
            vol_quiet = 40

        if self.context.current_emotion == EmotionalState.EXCITED:
            sounds = ["woohoo", "single_bark_2"]
            self.context.dog.speak(random.choice(sounds), volume=vol_excited)
        elif self.context.current_emotion == EmotionalState.ALERT:
            sounds = ["single_bark_1", "pant"]
            self.context.dog.speak(random.choice(sounds), volume=vol_default)
        elif self.context.current_emotion == EmotionalState.CONFUSED:
            self.context.dog.speak("confused_1", volume=vol_quiet)

        # Switch to investigating behavior
        if self.context.behavior_state in [BehaviorState.IDLE, BehaviorState.PATROLLING]:
            self.set_behavior(BehaviorState.EXPLORING)
    
    def _update_energy_level(self, reading: SensorReading, timestamp: float):
        """Delegate to EnergyService for energy accounting."""
        try:
            self.energy_service.update(self.context, reading, timestamp, self.config)
        except Exception:
            # Preserve previous behavior on hosts without full services
            time_factor = 0.001
            self.context.energy_level = max(0.0, self.context.energy_level - time_factor)
            if reading.touch != "N" or reading.sound_detected:
                self.context.energy_level = min(1.0, self.context.energy_level + 0.05)
            gx, gy, gz = reading.gyroscope
            movement_activity = (abs(gx) + abs(gy) + abs(gz)) / 3000.0
            if movement_activity > 0.1:
                self.context.energy_level = max(0.1, self.context.energy_level - 0.02)
    
    def _update_emotional_state(self):
        """Compute and apply emotional state using EmotionService."""
        current_time = time.time()
        try:
            base = self.emotion_service.compute_base_emotion(
                self.context, self.interaction_count, self.last_interaction_time, current_time
            )
        except Exception:
            # Fallback to a simple heuristic
            if self.context.energy_level > 0.8:
                base = EmotionalState.EXCITED
            elif self.context.energy_level > 0.6:
                base = EmotionalState.HAPPY
            elif self.context.energy_level > 0.4:
                base = EmotionalState.CALM
            elif self.context.energy_level > 0.2:
                base = EmotionalState.CONFUSED
            else:
                base = EmotionalState.TIRED
        if base != self.context.current_emotion:
            self.set_emotion(base)
    
    def _evaluate_behavior_transitions(self, current_time: float):
        """Evaluate and handle behavior state transitions"""
        time_in_state = current_time - self.behavior_start_time
        
        # ENHANCED: Transition logic with patrol behavior
        if self.context.behavior_state == BehaviorState.IDLE:
            if self.context.energy_level > 0.7 and time_in_state > 3:
                # Choose between exploring and patrolling based on energy
                if self.context.energy_level > 0.8 and random.random() < 0.6:
                    self.set_behavior(BehaviorState.PATROLLING)  # High energy = patrol
                else:
                    self.set_behavior(BehaviorState.EXPLORING)
            elif self.context.energy_level < 0.3:
                self.set_behavior(BehaviorState.RESTING)
                
        elif self.context.behavior_state == BehaviorState.EXPLORING:
            if self.interaction_count > 0 and time_in_state > 3:
                self.set_behavior(BehaviorState.INTERACTING)
            elif self.context.energy_level > 0.7 and time_in_state > 10:
                self.set_behavior(BehaviorState.PATROLLING)  # Transition to patrol
            elif self.context.energy_level < 0.4:
                self.set_behavior(BehaviorState.IDLE)
            elif time_in_state > 15:
                self.set_behavior(BehaviorState.IDLE)
                
        elif self.context.behavior_state == BehaviorState.PATROLLING:
            if self.interaction_count > 0 and time_in_state > 5:
                self.set_behavior(BehaviorState.INTERACTING)
            elif self.context.energy_level < 0.4:
                self.set_behavior(BehaviorState.IDLE)
            elif time_in_state > 60:  # Patrol for max 60 seconds before rest
                self.set_behavior(BehaviorState.IDLE)
                
        elif self.context.behavior_state == BehaviorState.INTERACTING:
            if current_time - self.last_interaction_time > 10:
                if self.context.energy_level > 0.6:
                    self.set_behavior(BehaviorState.PLAYING)
                else:
                    self.set_behavior(BehaviorState.IDLE)
                    
        elif self.context.behavior_state == BehaviorState.AVOIDING:
            if time_in_state > 3:  # Avoid for 3 seconds then return
                self.set_behavior(BehaviorState.IDLE)
                
        elif self.context.behavior_state == BehaviorState.RESTING:
            if self.context.energy_level > 0.5 or time_in_state > 20:
                self.set_behavior(BehaviorState.IDLE)
                
        elif self.context.behavior_state == BehaviorState.PLAYING:
            if self.context.energy_level < 0.4 or time_in_state > 30:
                self.set_behavior(BehaviorState.IDLE)
    
    # Behavior-specific logic for non-patrol states lives in behavior classes
    
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
            
            self._logger.info(f"🧭 Navigation command: {action} ({step_count} steps)")
            self._log_patrol_event("NAV_COMMAND", f"Executing navigation: {action}", {
                "action": action,
                "step_count": step_count,
                "nav_status": self.nav_controller.get_navigation_status() if self.nav_controller else None
            })
            
            speed = int(60 + self.context.energy_level * 20)
            self.context.dog.do_action(action, step_count=step_count, speed=speed)
            
            
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
            self._logger.info(f"🧠 Using scan data for navigation - obstacle at {self.obstacle_scan_data['forward']:.1f}cm")
            self._log_patrol_event("PATROL_AVOIDANCE", "Using scan data for obstacle avoidance", {
                "obstacle_distance": self.obstacle_scan_data['forward'],
                "avoidance_reason": "predictive_scan_data"
            })
            try:
                turn_speed = self._get_appropriate_turn_speed()
                self.obstacle_service.maybe_avoid(self.context, self.obstacle_scan_data, self.config, turn_speed)
            except Exception:
                pass
        else:
            # Path seems clear - continue wandering intelligently
            if random.random() < 0.75:  # 75% chance to move forward when clear
                # Intelligent forward movement
                step_count = random.randint(2, 4)
                
                # Adjust speed based on clearest path
                base_speed = 60 + int(self.context.energy_level * 30)
                
                # Bonus speed if path is very clear
                if self.obstacle_scan_data['forward'] > 100:
                    base_speed += 10
                
                self._logger.info(f"🚶 Walking forward {step_count} steps (path clear: {self.obstacle_scan_data['forward']:.1f}cm)")
                self._log_patrol_event("PATROL_FORWARD", f"Moving forward {step_count} steps", {
                    "step_count": step_count,
                    "speed": min(base_speed, 90),
                    "path_clearance": self.obstacle_scan_data['forward'],
                    "patrol_confidence": "high" if self.obstacle_scan_data['forward'] > 100 else "medium"
                })
                self.context.dog.do_action("forward", step_count=step_count, speed=min(base_speed, 90))
                
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
                    
                    self.context.dog.head_move([[scan_angle, 0, 0]], speed=60)
                    
            else:
                # Strategic turning based on available space
                self._logger.info("🔄 Strategic direction change...")
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
                    self._logger.warning("⚠️ Both sides blocked - backing up")
                    self.context.dog.do_action("backward", step_count=2, speed=60)
                    action = random.choice(["turn_left", "turn_right"])  # Try anyway
                
                # Add energetic trotting option when space is available
                if self.context.energy_level > 0.7 and (left_clear or right_clear):
                    if random.random() < 0.3:
                        action = "trot"
                        step_count = 1
                    else:
                        step_count = random.randint(1, 2)
                else:
                    step_count = random.randint(1, 2)
                
                speed = int(50 + self.context.energy_level * 35)
                # If turning and IMU orientation is available, prefer angle-based turning
                if action in ("turn_left", "turn_right") and getattr(self, "orientation_service", None) is not None:
                    try:
                        dps = float(getattr(self.config, "TURN_DEGREES_PER_STEP", 15.0))
                    except Exception:
                        dps = 15.0
                    deg = float(step_count) * dps * (1.0 if action == "turn_left" else -1.0)
                    tol = float(getattr(self.config, "ORIENTATION_TURN_TOLERANCE_DEG", 5.0))
                    tout = float(getattr(self.config, "ORIENTATION_MAX_TURN_TIME_S", 3.0))
                    self._turn_by_angle(deg, speed, tolerance_deg=tol, timeout_s=tout)
                else:
                    self.context.dog.do_action(action, step_count=step_count, speed=speed)
                
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
                if getattr(self, "orientation_service", None) is not None:
                    try:
                        dps = float(getattr(self.config, "TURN_DEGREES_PER_STEP", 15.0))
                    except Exception:
                        dps = 15.0
                    deg = float(getattr(self.config, "TURN_STEPS_NORMAL", 2)) * dps * (1.0 if turn_direction == "turn_left" else -1.0)
                    tol = float(getattr(self.config, "ORIENTATION_TURN_TOLERANCE_DEG", 5.0))
                    tout = float(getattr(self.config, "ORIENTATION_MAX_TURN_TIME_S", 3.0))
                    self._turn_by_angle(deg, turn_speed, tolerance_deg=tol, timeout_s=tout)
                else:
                    self.dog.do_action(turn_direction, step_count=self.config.TURN_STEPS_NORMAL, speed=turn_speed)
                self._logger.info(f"🚧 Simple obstacle avoidance - {turn_direction}")
                
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

    # Playing behavior is implemented in PlayingBehavior.execute()
    
    def set_emotion(self, emotion: EmotionalState):
        """Set emotional state via the EmotionService and log the change."""
        if emotion != self.current_emotion:
            old_emotion = self.current_emotion
            self._logger.info(f"😊 Emotion: {emotion.value} (Energy: {self.energy_level:.2f})")
            # Log emotion change
            self._log_patrol_event(
                "EMOTION_CHANGE",
                f"Emotion changed: {old_emotion.value} → {emotion.value}",
                {
                    "old_emotion": old_emotion.value,
                    "new_emotion": emotion.value,
                    "energy_level": self.energy_level,
                    "trigger_cause": "automatic_update",
                },
            )
            # Delegate to emotion service for state update and optional feedback
            try:
                if self.emotional_system_enabled:
                    self.emotion_service.set_emotion(self.context, emotion, self.context.dog)
                else:
                    # Update context only; skip LED/sound effects
                    self.context.current_emotion = emotion
            except Exception:
                # Best effort on host machines without hardware
                self.context.current_emotion = emotion
    
    def set_behavior(self, behavior: BehaviorState):
        """Set behavior state and transition current behavior handler."""
        if behavior != self.current_behavior:
            old_behavior = self.current_behavior
            time_in_previous = time.time() - self.behavior_start_time

            self._logger.info(f"🎯 Behavior: {behavior.value}")

            # Log behavior change
            self._log_patrol_event(
                "BEHAVIOR_CHANGE",
                f"Behavior changed: {old_behavior.value} → {behavior.value}",
                {
                    "old_behavior": old_behavior.value,
                    "new_behavior": behavior.value,
                    "time_in_previous_behavior": round(time_in_previous, 1),
                    "transition_reason": "automatic_state_machine",
                },
            )

            # Exit old behavior object if present
            try:
                if self.context.current_behavior:
                    self.context.current_behavior.on_exit(self.context)
            except Exception:
                pass

            # Switch behavior state for legacy compatibility
            self.current_behavior = behavior
            # Enter new behavior object if registered
            self.context.current_behavior = self.behaviors.get(behavior, self.behaviors[BehaviorState.IDLE])
            try:
                self.context.current_behavior.on_enter(self.context)
            except Exception:
                pass
            self.behavior_start_time = time.time()
    
    def _voice_recognition_loop(self):
        """Voice recognition loop with wake word detection"""
        if not VOICE_AVAILABLE:
            return
            
        recognizer = sr.Recognizer()
        microphone = sr.Microphone()
        
        # Adjust for ambient noise
        with microphone as source:
            self._logger.info("🎙️ Calibrating microphone for ambient noise...")
            recognizer.adjust_for_ambient_noise(source)
        
        self._logger.info(f"🎧 Listening for wake word: '{self.wake_word}'...")
        
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
                        self._logger.info(f"🎯 Wake word detected: '{text}'")
                        self._process_voice_command(text)
                        
                except sr.UnknownValueError:
                    # Could not understand audio - normal, ignore
                    pass
                except sr.RequestError as e:
                    self._logger.warning(f"⚠️ Voice recognition service error: {e}")
                    time.sleep(1)
                    
            except sr.WaitTimeoutError:
                # Normal timeout - continue listening
                pass
            except Exception as e:
                self._logger.warning(f"⚠️ Voice recognition error: {e}")
                time.sleep(1)
    
    def _process_voice_command(self, full_text: str):
        """Process voice command after wake word detection"""
        self.last_voice_command_time = time.time()
        
        # Remove wake word and clean up text
        command_text = full_text.replace(self.wake_word, "").strip()
        
        if not command_text:
            # Just wake word, acknowledge
            self._logger.info("👋 Hello! I'm listening...")
            self.dog.speak("pant", volume=60)
            self.set_emotion(EmotionalState.HAPPY)
            return
            
        self._logger.info(f"🎙️ Voice command: '{command_text}'")
        
        # Visual feedback for voice command
        self.dog.rgb_strip.set_mode("boom", "cyan", bps=3.0, brightness=1.0)
        
        # Find matching command
        command_executed = False
        for cmd_key, cmd_action in self.voice_commands.items():
            if cmd_key in command_text:
                self._logger.info(f"✅ Executing command: {cmd_key}")
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
                    self._logger.error(f"❌ Command execution error: {e}")
                    self._log_patrol_event("VOICE_ERROR", f"Voice command failed: {cmd_key}", {
                        "error": str(e)
                    })
                    self.dog.speak("confused_2", volume=60)
                break
        
        if not command_executed:
            self._logger.warning(f"❓ Unknown command: '{command_text}'")
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
        self._logger.info("😊 PiDog is very happy!")
    
    def _scold_response(self):
        """Response to 'bad dog' command"""  
        self.dog.do_action("doze_off", speed=30)
        self.dog.speak("snoring", volume=40)
        self.set_emotion(EmotionalState.TIRED)
        self.energy_level = max(0.1, self.energy_level - 0.3)  # Reduce energy
        self._logger.info("😔 PiDog feels sad...")
    
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
        # Prefer IMU-based angle turn when available; fallback to steps
        try:
            dps = float(getattr(self.config, "TURN_DEGREES_PER_STEP", 15.0))
        except Exception:
            dps = 15.0
        try:
            steps_45 = int(getattr(self.config, "TURN_45_DEGREES", 3))
        except Exception:
            steps_45 = 3
        deg = float(steps_45) * dps
        tol = float(getattr(self.config, "ORIENTATION_TURN_TOLERANCE_DEG", 5.0))
        tout = float(getattr(self.config, "ORIENTATION_MAX_TURN_TIME_S", 3.0))
        if getattr(self, "orientation_service", None) is not None:
            self._turn_by_angle(deg, turn_speed, tolerance_deg=tol, timeout_s=tout)
        else:
            self.dog.do_action("turn_left", step_count=steps_45, speed=turn_speed)
        
    def _voice_turn_right(self):
        """Voice command: turn right"""
        self.is_walking = True  
        self.last_walk_command_time = time.time()
        turn_speed = self._get_appropriate_turn_speed()
        try:
            dps = float(getattr(self.config, "TURN_DEGREES_PER_STEP", 15.0))
        except Exception:
            dps = 15.0
        try:
            steps_45 = int(getattr(self.config, "TURN_45_DEGREES", 3))
        except Exception:
            steps_45 = 3
        deg = -float(steps_45) * dps
        tol = float(getattr(self.config, "ORIENTATION_TURN_TOLERANCE_DEG", 5.0))
        tout = float(getattr(self.config, "ORIENTATION_MAX_TURN_TIME_S", 3.0))
        if getattr(self, "orientation_service", None) is not None:
            self._turn_by_angle(deg, turn_speed, tolerance_deg=tol, timeout_s=tout)
        else:
            self.dog.do_action("turn_right", step_count=steps_45, speed=turn_speed)
    
    def generate_patrol_report(self) -> dict:
        """Generate comprehensive patrol report via LogService."""
        try:
            return self.log_service.generate_report(
                final_behavior=self.current_behavior.value,
                final_emotion=self.current_emotion.value,
                final_energy_level=self.energy_level,
                final_scan_data=dict(self.obstacle_scan_data),
            )
        except Exception:
            # Fallback minimal report
            return {
                "session_info": {
                    "session_id": self.patrol_session_id,
                    "start_time": self.patrol_start_time,
                    "end_time": time.time(),
                    "total_duration": time.time() - self.patrol_start_time,
                    "log_file": self.log_file_path,
                },
                "activity_summary": {
                    "total_events": len(self.patrol_log),
                    "event_breakdown": {},
                    "obstacles_encountered": 0,
                    "interactions": 0,
                    "voice_commands": 0,
                    "emotion_changes": 0,
                },
                "final_state": {
                    "behavior": self.current_behavior.value,
                    "emotion": self.current_emotion.value,
                    "energy_level": self.energy_level,
                    "scan_data": dict(self.obstacle_scan_data),
                },
            }

    def _shutdown(self):
        """Safely shutdown the AI system"""
        self._logger.info("🛑 Initiating patrol system shutdown...")
        
        # Log shutdown initiation
        self._log_patrol_event("SYSTEM_SHUTDOWN", "Patrol system shutdown initiated")
        
        # Stop and save mapping system (no legacy SLAM system)
        # If needed, save map here using self.home_map
            
        # Stop sensor fusion localization
        if self.sensor_localizer:
            self._log_patrol_event("LOCALIZATION_SHUTDOWN", "Stopping sensor fusion localization")
            self.sensor_localizer.stop_localization()
            self._logger.info("✓ Sensor fusion localization stopped")
        
        # Stop new AI services
        if hasattr(self, 'face_recognition_service') and self.face_recognition_service:
            try:
                self.face_recognition_service.stop()
                self._log_patrol_event("FACE_RECOGNITION_SHUTDOWN", "Face recognition service stopped")
                self._logger.info("✓ Face recognition service stopped")
            except Exception as e:
                self._logger.error(f"Error stopping face recognition service: {e}")
        
        if hasattr(self, 'dynamic_balance_service') and self.dynamic_balance_service:
            try:
                self.dynamic_balance_service.stop()
                self._log_patrol_event("BALANCE_SHUTDOWN", "Dynamic balance service stopped")
                self._logger.info("✓ Dynamic balance service stopped")
            except Exception as e:
                self._logger.error(f"Error stopping dynamic balance service: {e}")
        
        if hasattr(self, 'enhanced_audio_service') and self.enhanced_audio_service:
            try:
                self.enhanced_audio_service.stop()
                self._log_patrol_event("AUDIO_SHUTDOWN", "Enhanced audio processing service stopped")
                self._logger.info("✓ Enhanced audio processing service stopped")
            except Exception as e:
                self._logger.error(f"Error stopping enhanced audio service: {e}")
        
        # Generate final patrol report
        try:
            report = self.generate_patrol_report()
            report_file = f"patrol_report_{self.patrol_session_id}.json"
            
            import json
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            
            self._logger.info(f"📊 Patrol report saved: {report_file}")
            try:
                from typing import cast
                total_events = len(self.log_service.dump())
            except Exception:
                total_events = len(self.patrol_log)
            self._logger.info(f"📋 Total events logged: {total_events}")
            self._logger.info(f"⏱️ Total patrol time: {report['session_info']['total_duration']:.1f}s")
            
            self._log_patrol_event("REPORT_GENERATED", f"Final patrol report saved to {report_file}", {
                "total_events": len(self.patrol_log),
                "report_file": report_file
            })
            
        except Exception as e:
            self._logger.warning(f"⚠️ Error generating patrol report: {e}")
        
        self.running = False
        
        # Stop runtime coordinators if running
        try:
            if self._sensor_monitor:
                self._sensor_monitor.stop(timeout=2.0)
        except Exception:
            pass
        try:
            if self._scan_coordinator:
                self._scan_coordinator.stop(timeout=2.0)
        except Exception:
            pass
        try:
            if self._health_monitor:
                self._health_monitor.stop(timeout=2.0)
        except Exception:
            pass
        
        # Legacy thread joins removed; runtimes are stopped above
            
        # Stop voice runtime if running (or legacy thread if present)
        try:
            if self._voice_runtime:
                self._voice_runtime.stop(timeout=2.0)
        except Exception:
            pass
        if self.voice_thread:
            self.voice_thread.join(timeout=2.0)
        
        if self.dog:
            try:
                self._logger.info("🛌 Returning to rest position...")
                self._log_patrol_event("PHYSICAL_SHUTDOWN", "Returning PiDog to rest position")
                
                self.dog.rgb_strip.set_mode("breath", "black")  # Turn off LEDs
                self.dog.stop_and_lie()
                self.dog.close()
                self._logger.info("✓ AI system shutdown complete")
                
                # Final log entry
                if self.log_file_path:
                    from typing import cast
                    final_log = cast(str, self.log_file_path)
                    with open(final_log, 'a', encoding='utf-8') as f:
                        f.write(f"\n[{time.strftime('%H:%M:%S')}] ========== PATROL SESSION ENDED ==========\n")
                    
            except Exception as e:
                self._logger.warning(f"⚠️ Shutdown error: {e}")
    
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
        if not self.slam_enabled or not self.home_map:
            self._logger.warning("❌ Mapping system not available for calibration")
            return False

        self._logger.info(f"🎯 Starting position calibration using {method}...")
        self._log_patrol_event("CALIBRATION_START", f"Position calibration started: {method}")

        # Unified service path only
        try:
            if getattr(self, "calibration_service", None) is None:
                self._logger.warning("CalibrationService not available")
                self._log_patrol_event("CALIBRATION_FAILED", f"Service unavailable: {method}")
                return False
            ok = bool(self.calibration_service.calibrate(method))
            if ok:
                self._log_patrol_event("CALIBRATION_SUCCESS", f"Calibration completed via service: {method}")
                return True
            self._log_patrol_event("CALIBRATION_FAILED", f"Calibration failed via service: {method}")
            return False
        except Exception as e:
            self._logger.error(f"Calibration service error: {e}")
            self._log_patrol_event("CALIBRATION_ERROR", f"Calibration service error: {e}")
            return False
    
    # Internal calibration helpers removed in favor of CalibrationService
    
    def _start_autonomous_exploration(self):
        """Start autonomous exploration mode"""
        if not self.nav_controller:
            self._logger.warning("❌ Navigation system not available")
            self.dog.speak("confused_1", volume=60)
            return
        
        success = self.nav_controller.start_exploration_mode()
        if success:
            self._logger.info("🔍 Autonomous exploration started")
            self.dog.speak("woohoo", volume=70)
            self.set_emotion(EmotionalState.EXCITED)
            self.set_behavior(BehaviorState.EXPLORING)
            
            self._log_patrol_event("NAV_START", "Autonomous exploration mode started", {
                "nav_status": self.nav_controller.get_navigation_status() if self.nav_controller else None
            })
        else:
            self._logger.warning("❌ Could not start exploration")
            self.dog.speak("confused_2", volume=60)
    
    def _stop_navigation(self):
        """Stop current navigation"""
        if not self.nav_controller:
            return
        
        self.nav_controller.stop_navigation()
        self._logger.info("🛑 Navigation stopped")
        self.dog.speak("single_bark_1", volume=60)
        
        self._log_patrol_event("NAV_STOP", "Navigation manually stopped")
    
    def _navigate_to_nearest_room(self):
        """Navigate to the nearest identified room"""
        self._logger.warning("❌ Room navigation is not supported in the current mapping system.")
    
    def _show_map_visualization(self):
        """Show visual representation of the current map"""
        if not self.slam_enabled or not self.home_map:
            self._logger.warning("❌ Mapping system not available for map visualization")
            return
        
        try:
            # Import visualization here to avoid dependency issues
            try:
                from packmind.visualization.map_visualization import MapVisualizer
            except Exception:
                from visualization.map_visualization import MapVisualizer
            
            visualizer = MapVisualizer(self.home_map)
            
            self._logger.info("🗺️ Current Home Map:")
            visualizer.print_map(show_colors=True)
            if hasattr(visualizer, 'print_anchor_summary'):
                visualizer.print_anchor_summary()
            # Export current map
            timestamp = int(time.time())
            export_files = []
            if hasattr(visualizer, 'export_to_json'):
                visualizer.export_to_json(f"current_map_{timestamp}.json")
                export_files.append(f"current_map_{timestamp}.json")
            if hasattr(visualizer, 'save_report'):
                visualizer.save_report(f"map_report_{timestamp}.txt")
                export_files.append(f"map_report_{timestamp}.txt")
            self.dog.speak("single_bark_1", volume=60)
            self._log_patrol_event("MAP_DISPLAY", "Map visualization shown", {
                "rooms_detected": 0,
                "landmarks_detected": 0,
                "export_files": export_files
            })
            
        except ImportError:
            self._logger.warning("❌ Map visualization not available")
            self.dog.speak("confused_1", volume=60)
        except Exception as e:
            self._logger.error(f"❌ Map visualization error: {e}")
            self.dog.speak("confused_2", volume=60)
    
    def _calibrate_sensors(self):
        """Calibrate sensor fusion system"""
        if not self.sensor_localizer:
            self._logger.warning("❌ Sensor fusion not available")
            self.dog.speak("confused_1", volume=60)
            return
        
        self._logger.info("🎯 Starting sensor calibration - keep PiDog stationary for 5 seconds...")
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
                self._logger.info("✓ Sensor calibration completed")
                self.dog.speak("woohoo", volume=70)
                self.set_emotion(EmotionalState.HAPPY)
                
                self._log_patrol_event("CALIBRATION_SUCCESS", "Sensor calibration completed successfully")
            else:
                self._logger.warning("❌ Sensor calibration failed")
                self.dog.speak("confused_2", volume=60)
                
                self._log_patrol_event("CALIBRATION_FAILED", "Sensor calibration failed")
                
        except Exception as e:
            self._logger.error(f"❌ Calibration error: {e}")
            self.dog.speak("confused_1", volume=60)
            
            self._log_patrol_event("CALIBRATION_ERROR", f"Sensor calibration error: {e}")
        
        # Restore behavior
        self.set_behavior(old_behavior)
    
    def print_status(self):
        """Print current AI status"""
        self._logger.info(f"=== PiDog AI Status ===")
        self._logger.info(f"Emotion: {self.current_emotion.value}")
        self._logger.info(f"Behavior: {self.current_behavior.value}")
        self._logger.info(f"Energy: {self.energy_level:.2f}")
        self._logger.info(f"Interactions: {self.interaction_count}")
        self._logger.info(f"Touch preferences: {self.touch_preferences}")
        self._logger.info(f"Attention target: {self.attention_target}°" if self.attention_target else "None")
        self._logger.info(f"Recent obstacles: {len(self.obstacle_memory)}")
        self._logger.info(f"Voice enabled: {self.voice_enabled}")
        self._logger.info(f"Last voice command: {time.time() - self.last_voice_command_time:.1f}s ago")
        self._logger.info(f"Walking state: {self.is_walking}")
        self._logger.info(f"Scan data: F:{self.obstacle_scan_data['forward']:.1f} L:{self.obstacle_scan_data['left']:.1f} R:{self.obstacle_scan_data['right']:.1f}")
        self._logger.info(f"Avoidance history: {len(self.avoidance_history)} recent")
        self._logger.info(f"Stuck counter: {self.stuck_counter}")
        try:
            total_events = len(self.log_service.dump())
        except Exception:
            total_events = len(self.patrol_log)
        self._logger.info(f"Patrol log entries: {total_events}")
        self._logger.info(f"Patrol log file: {self.log_file_path}")
        
        # SLAM system status
        if self.slam_enabled and self.home_map:
            try:
                map_summary = self.home_map.get_map_summary() if hasattr(self.home_map, 'get_map_summary') else {}
                current_pos = self.home_map.get_position() if hasattr(self.home_map, 'get_position') else None
                self._logger.info(f"Mapping enabled: {self.slam_enabled}")
                if current_pos:
                    self._logger.info(f"Map position: ({getattr(current_pos, 'x', 0.0):.1f}, {getattr(current_pos, 'y', 0.0):.1f}) @ {getattr(current_pos, 'heading', 0.0):.1f}°")
                    self._logger.info(f"Position confidence: {getattr(current_pos, 'confidence', 0.0):.3f}")
                self._logger.info(f"Map bounds: {map_summary.get('map_bounds', {})}")
                self._logger.info(f"Mapped area: {map_summary.get('mapped_area_m2', 0.0):.2f} m^2")
                self._logger.info(f"Cell counts: {map_summary.get('cell_counts', {})}")
                self._logger.info(f"Openings: {len(getattr(self.home_map, 'openings', {}))}")
                self._logger.info(f"Safe paths: {len(getattr(self.home_map, 'safe_paths', {}))}")
                # Sensor fusion status
                if self.sensor_localizer:
                    loc_status = self.sensor_localizer.get_localization_status()
                    pf_data = loc_status.get("particle_filter", {})
                    self._logger.info(f"Sensor fusion: Active")
                    self._logger.info(f"  Surface type: {loc_status.get('surface_type', 'unknown')}")
                    self._logger.info(f"  Particle filter confidence: {pf_data.get('confidence', 0.0):.3f}")
                    self._logger.info(f"  Recent ultrasonic scans: {loc_status.get('recent_scans', 0)}")
                    self._logger.info(f"  Motion samples: {loc_status.get('motion_samples', 0)}")
            except Exception as e:
                self._logger.warning(f"Mapping status error: {e}")
        else:
            self._logger.info(f"Mapping enabled: {self.slam_enabled}")
            
        self._logger.info(f"======================")

    def print_configuration(self):
        """Print current configuration settings"""
        self._logger.info(f"=== PiDog Configuration ===")
        self._logger.info(f"Mode: {'Advanced' if self.slam_enabled else 'Simple'}")
        
        self._logger.info(f"--- Feature Toggles ---")
        self._logger.info(f"Voice Commands: {self.config.ENABLE_VOICE_COMMANDS}")
        self._logger.info(f"SLAM Mapping: {self.config.ENABLE_SLAM_MAPPING}")
        self._logger.info(f"Sensor Fusion: {self.config.ENABLE_SENSOR_FUSION}")
        self._logger.info(f"Intelligent Scanning: {self.config.ENABLE_INTELLIGENT_SCANNING}")
        self._logger.info(f"Emotional System: {self.config.ENABLE_EMOTIONAL_SYSTEM}")
        self._logger.info(f"Learning System: {self.config.ENABLE_LEARNING_SYSTEM}")
        self._logger.info(f"Patrol Logging: {self.config.ENABLE_PATROL_LOGGING}")
        self._logger.info(f"Autonomous Navigation: {self.config.ENABLE_AUTONOMOUS_NAVIGATION}")
        
        self._logger.info(f"--- Obstacle Avoidance ---")
        self._logger.info(f"Immediate Threat: {self.config.OBSTACLE_IMMEDIATE_THREAT}cm")
        self._logger.info(f"Approaching Threat: {self.config.OBSTACLE_APPROACHING_THREAT}cm") 
        self._logger.info(f"Emergency Stop: {self.config.OBSTACLE_EMERGENCY_STOP}cm")
        self._logger.info(f"Safe Distance: {self.config.OBSTACLE_SAFE_DISTANCE}cm")
        self._logger.info(f"Scan Interval: {self.config.OBSTACLE_SCAN_INTERVAL}s")
        
        self._logger.info(f"--- Movement Parameters ---")
        self._logger.info(f"Turn Steps - Small: {self.config.TURN_STEPS_SMALL}, Normal: {self.config.TURN_STEPS_NORMAL}, Large: {self.config.TURN_STEPS_LARGE}")
        self._logger.info(f"Walk Steps - Short: {self.config.WALK_STEPS_SHORT}, Normal: {self.config.WALK_STEPS_NORMAL}, Long: {self.config.WALK_STEPS_LONG}")
        self._logger.info(f"Backup Steps: {self.config.BACKUP_STEPS}")
        self._logger.info(f"Walk Speeds - Slow: {self.config.SPEED_SLOW}, Normal: {self.config.SPEED_NORMAL}, Fast: {self.config.SPEED_FAST}")
        self._logger.info(f"Turn Speeds - Slow: {self.config.SPEED_TURN_SLOW}, Normal: {self.config.SPEED_TURN_NORMAL}, Fast: {self.config.SPEED_TURN_FAST}")
        self._logger.info(f"Emergency Speed: {self.config.SPEED_EMERGENCY}")
        
        self._logger.info(f"--- Turn Calibration ---")
        self._logger.info(f"Degrees per step: {self.config.TURN_DEGREES_PER_STEP}° (at speed {self.config.SPEED_TURN_NORMAL})")
        self._logger.info(f"Turn angles - 45°: {self.config.TURN_45_DEGREES} steps, 90°: {self.config.TURN_90_DEGREES} steps, 180°: {self.config.TURN_180_DEGREES} steps")
        
        self._logger.info(f"--- Behavior Timing ---")
        self._logger.info(f"Patrol Duration: {self.config.PATROL_DURATION_MIN}-{self.config.PATROL_DURATION_MAX}s")
        self._logger.info(f"Rest Duration: {self.config.REST_DURATION}s")
        self._logger.info(f"Interaction Timeout: {self.config.INTERACTION_TIMEOUT}s")
        
        self._logger.info(f"--- Voice Settings ---")
        self._logger.info(f"Wake Word: '{self.config.WAKE_WORD}'")
        self._logger.info(f"Default Volume: {self.config.VOICE_VOLUME_DEFAULT}")
        self._logger.info(f"Voice Timeout: {self.config.VOICE_COMMAND_TIMEOUT}s")
        
        self._logger.info(f"===========================")

    def _toggle_simple_mode(self):
        """Switch to simple mode - disable advanced features"""
        self._logger.info("🔄 Switching to Simple Mode...")
        
        # Disable advanced features
        self.slam_enabled = False
        self.sensor_fusion_enabled = False
        self.intelligent_scanning_enabled = False
        self.autonomous_nav_enabled = False
        
        # Stop advanced systems
        if self.slam_enabled and self.home_map:
            # If HomeMap requires explicit stop, call it here
            pass
        if self.sensor_localizer:
            self.sensor_localizer.stop_localization()
            
        self._log_patrol_event("MODE_CHANGE", "Switched to Simple Mode", {
            "slam_enabled": False,
            "sensor_fusion_enabled": False,
            "intelligent_scanning": False,
            "autonomous_navigation": False
        })
        
        self.dog.speak("single_bark_1", volume=self.config.VOICE_VOLUME_DEFAULT)
        self._logger.info("✓ Simple Mode activated - using basic obstacle avoidance")

    def _toggle_advanced_mode(self):
        """Switch to advanced mode - enable available features"""
        self._logger.info("🔄 Switching to Advanced Mode...")
        
        # Check if dependencies are available
        if not MAPPING_AVAILABLE:
            self._logger.warning("⚠️ Cannot enable Advanced Mode - missing dependencies (numpy)")
            self.dog.speak("confused_1", volume=self.config.VOICE_VOLUME_DEFAULT)
            return
            
        # Enable advanced features
        self.slam_enabled = True
        self.sensor_fusion_enabled = True
        self.intelligent_scanning_enabled = True
        self.autonomous_nav_enabled = True
        
        # Restart systems if needed
        if not self.home_map:
            self.home_map = HomeMap()
        if not self.sensor_localizer:
            self.sensor_localizer = SensorFusionLocalizer(self.home_map)
            self.sensor_localizer.start_localization()
        if not self.nav_controller:
            if not self.pathfinder:
                self.pathfinder = PiDogPathfinder(self.home_map)
            self.nav_controller = NavigationController(self.pathfinder)
        
        self._log_patrol_event("MODE_CHANGE", "Switched to Advanced Mode", {
            "slam_enabled": True,
            "sensor_fusion_enabled": True,
            "intelligent_scanning": True,
            "autonomous_navigation": True
        })
        
        self.dog.speak("woohoo", volume=self.config.VOICE_VOLUME_DEFAULT)
        self._logger.info("✓ Advanced Mode activated - full AI capabilities enabled")
    
    def _load_config_preset(self, preset_name):
        """Load a configuration preset"""
        try:
            self._logger.info(f"🔄 Loading {preset_name} configuration preset...")
            
            # Load new configuration
            new_config = load_config(preset_name)
            
            # Validate new configuration
            warnings = validate_config(new_config)
            if warnings:
                for warning in warnings:
                    self._logger.warning(f"Config warning: {warning}")
            
            # Apply new configuration
            try:
                old_config_name = type(self.config).__name__
            except Exception:
                old_config_name = 'Unknown'
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
            self._logger.info(f"✓ {preset_name.title()} configuration loaded successfully")
            self._logger.info(f"   SLAM: {'✓' if self.slam_enabled else '✗'}")
            self._logger.info(f"   Speed Normal: {self.config.SPEED_NORMAL}")
            self._logger.info(f"   Obstacle Threshold: {self.config.OBSTACLE_IMMEDIATE_THREAT}cm")
            
        except Exception as e:
            self._logger.error(f"✗ Failed to load {preset_name} preset: {e}")
            self.dog.speak("confused_2", volume=self.config.VOICE_VOLUME_DEFAULT)
    
    def _test_walk_speed(self, speed_mode):
        """Test walk speed calibration"""
        self._logger.info(f"🧪 Testing {speed_mode} walk speed...")
        
        if speed_mode == "slow":
            speed = self.config.SPEED_SLOW
        elif speed_mode == "normal":
            speed = self.config.SPEED_NORMAL
        elif speed_mode == "fast":
            speed = self.config.SPEED_FAST
        else:
            return
            
        self._logger.info(f"   Walking {self.config.WALK_STEPS_NORMAL} steps at speed {speed}")
        self.dog.do_action("forward", step_count=self.config.WALK_STEPS_NORMAL, speed=speed)
        
        self._log_patrol_event("SPEED_TEST", f"Walk speed test: {speed_mode}", {
            "speed_mode": speed_mode,
            "speed_value": speed,
            "step_count": self.config.WALK_STEPS_NORMAL
        })
    
    def _test_turn_angle(self, degrees):
        """Test turn angle calibration"""
        self._logger.info(f"🧪 Testing {degrees}° turn...")
        # Prefer IMU-based precise turning if orientation service is available
        if getattr(self, "orientation_service", None) is not None and bool(getattr(self.config, "ENABLE_ORIENTATION_SERVICE", True)):
            speed = int(getattr(self.config, "SPEED_TURN_NORMAL", 200))
            tol = float(getattr(self.config, "ORIENTATION_TURN_TOLERANCE_DEG", 5.0))
            timeout_s = float(getattr(self.config, "ORIENTATION_MAX_TURN_TIME_S", 3.0))
            self._turn_by_angle(degrees=float(degrees), speed=speed, tolerance_deg=tol, timeout_s=timeout_s)
        else:
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
            self._logger.info(f"   Turning {direction} {steps} steps at speed {speed} (should be {degrees}°)")
            self.dog.do_action(direction, step_count=steps, speed=speed)
        
        self._log_patrol_event("TURN_TEST", f"Turn angle test: {degrees}°", {
            "target_degrees": degrees,
            "method": "imu" if getattr(self, "orientation_service", None) is not None else "steps",
        })

    def _turn_by_angle(self, degrees: float, speed: int, tolerance_deg: float = 5.0, timeout_s: float = 3.0) -> None:
        """Rotate in place by a target angle using IMU heading feedback."""
        try:
            orientation = getattr(self, "orientation_service", None)
            if orientation is None:
                return
            start = float(getattr(self.context, "current_heading", 0.0))
            target_delta = float(degrees)
            # Normalize to [-180, 180] for shortest path
            def ang_diff(a: float, b: float) -> float:
                d = (a - b + 180.0) % 360.0 - 180.0
                return d
            end_time = time.time() + float(timeout_s)
            direction = "turn_left" if target_delta >= 0 else "turn_right"
            while time.time() < end_time:
                current = float(getattr(self.context, "current_heading", 0.0))
                delta = ang_diff(current, start)
                remaining = target_delta - delta
                if abs(remaining) <= float(tolerance_deg):
                    break
                step_dir = "turn_left" if remaining > 0 else "turn_right"
                # small discrete step; leverage existing step action
                try:
                    self.dog.do_action(step_dir, step_count=1, speed=int(speed))
                except Exception:
                    pass
                time.sleep(0.1)
        except Exception:
            pass


def main():
    """Main function with configuration display"""
    # Choose configuration: env override → platform hint → default
    import os, platform
    preset = os.getenv("PACKMIND_CONFIG") or os.getenv("HOUNDMIND_PROFILE")
    if not preset:
        # Platform hint: favor 'pi3' on 32-bit ARM (common on Pi 3B)
        try:
            mach = platform.machine().lower()
            if mach.startswith("armv7"):
                preset = "pi3"
        except Exception:
            preset = None
    config = load_config(preset or "default")
    warnings = validate_config(config)
    config_source = "packmind/packmind_config.py"
    logger = logging.getLogger("packmind.orchestrator")
    
    logger.info("🤖 Advanced PiDog AI Behavior System")
    logger.info("====================================")
    logger.info(f"📋 Configuration: {config_source}")
    if warnings:
        logger.warning("⚠️ Configuration warnings detected")
    logger.info("")
    logger.info("Features:")
    logger.info("• 🧠 Emotional state system with LED feedback")
    logger.info("• 📚 Learning touch preferences") 
    logger.info("• ⚡ Energy management and fatigue")
    logger.info("• 🚧 Smart obstacle avoidance with memory")
    logger.info("• 👂 Enhanced sound direction tracking & body turning")
    logger.info("• 🚶 Intelligent patrol behavior with predictive obstacle avoidance")
    logger.info("• 🔍 3-way ultrasonic scanning (forward/left/right) during movement")
    logger.info("• 🧠 Smart pathfinding - turns toward most open direction")
    logger.info("• 🔄 Anti-stuck system with multiple escape strategies")
    logger.info("• 🎙️ Voice commands with 'PiDog' wake word")
    logger.info("• 🎯 Advanced behavior state machine")
    logger.info("• 📊 Comprehensive patrol logging with timestamped events")
    logger.info("• 📝 Automatic patrol report generation")
    if MAPPING_AVAILABLE:
        logger.info("• 🗺️ SLAM house mapping with persistent map storage")
        logger.info("• 📍 Sensor fusion localization (IMU + ultrasonic + particle filter)")
        logger.info("• 🏃 Surface type detection and adaptive movement calibration")
        logger.info("• 🎯 Multiple calibration methods (wall-follow, corner-seek, sensor-cal)")
        logger.info("• 🧠 Landmark detection and room identification")
        logger.info("• 🔍 Ultrasonic triangulation for position correction")
    logger.info("• Multi-sensor fusion with movement analysis")
    logger.info("")
    if VOICE_AVAILABLE:
        logger.info("🎙️ Voice Commands Available:")
        logger.info("   Say 'PiDog' + command:")
        logger.info("   • 'sit', 'stand', 'lie down', 'walk'")
        logger.info("   • 'turn left', 'turn right', 'wag tail'")  
        logger.info("   • 'shake head', 'nod', 'stretch'")
        logger.info("   • 'play', 'explore', 'patrol', 'rest'")
        logger.info("   • 'good dog' (praise), 'bad dog' (scold)")
        logger.info("   • 'stop' (emergency)")
        if MAPPING_AVAILABLE:
            logger.info("   • 'calibrate' (wall follow), 'find corner' (corner seek)")
            logger.info("   • 'calibrate sensors' (IMU baseline calibration)")
            logger.info("   • 'explore' (autonomous exploration), 'go to room'")
            logger.info("   • 'show map' (display current map), 'stop navigation'")
            logger.info("   • 'status' (detailed info including localization data)")
    else:
        logger.info("🔇 Voice commands disabled (install: pip install speech_recognition pyaudio)")
    
    logger.info("")
    logger.info("💡 Configuration Tips:")
    logger.info("   • Edit packmind/packmind_config.py to customize behavior")
    logger.info("   • Use preset configurations: simple, advanced, indoor, explorer") 
    logger.info("   • Voice commands: 'load simple config', 'load advanced config'")
    logger.info("   • Test settings with voice commands before saving changes")
    logger.info("")
    
    if preset:
        logger.info(f"Using preset: {preset}")
    ai = Orchestrator(config_preset=preset or "default")
    
    try:
        success = ai.start_ai_system()
        if not success:
            logger.error("Failed to start AI system")
            return 1
            
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())