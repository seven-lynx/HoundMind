"""
PiDog AI Configuration File
==========================

This file contains all user-configurable settings for the PiDog AI system.
Edit the values in the PiDogConfig class to customize your PiDog's behavior.

IMPORTANT: After making changes, restart the pidog AI script to apply them.
"""

class PiDogConfig:
    """
    User-configurable settings for PiDog AI behavior
    
    FEATURE TOGGLES - Enable/Disable major systems:
    """
    
    # ============================================================================
    # FEATURE ENABLE/DISABLE TOGGLES
    # ============================================================================
    
    ENABLE_VOICE_COMMANDS = True      # Voice recognition with wake word "PiDog"
    ENABLE_SLAM_MAPPING = True        # Advanced SLAM house mapping system
    ENABLE_SENSOR_FUSION = True       # Advanced localization (requires SLAM)
    ENABLE_INTELLIGENT_SCANNING = True # 3-way obstacle scanning during movement
    ENABLE_EMOTIONAL_SYSTEM = True    # LED emotions and behavioral responses
    ENABLE_LEARNING_SYSTEM = True     # Learn touch preferences over time
    ENABLE_PATROL_LOGGING = True      # Comprehensive activity logging
    ENABLE_AUTONOMOUS_NAVIGATION = True # AI pathfinding and exploration (requires SLAM)
    ENABLE_FACE_RECOGNITION = True     # Face detection, recognition, and personality adaptation
    ENABLE_DYNAMIC_BALANCE = True      # Real-time balance monitoring and stability control
    ENABLE_ENHANCED_AUDIO = True       # Multi-source sound tracking and intelligent localization
    ENABLE_ORIENTATION_SERVICE = True  # Integrate IMU yaw to track heading
    
    # ============================================================================
    # ADVANCED MAPPING PARAMETERS (for HomeMap)
    # ============================================================================
    # Occupancy grid confidence threshold for cell type assignment
    MAPPING_CONFIDENCE_THRESHOLD = 0.7   # 0.0-1.0, above = OBSTACLE, below = FREE
    # Dynamic obstacle fading
    MAPPING_MAX_OBSTACLE_AGE = 300.0     # Seconds before obstacle starts to fade
    MAPPING_FADE_TIME = 300.0            # Time in seconds after which to start fading
    MAPPING_FADE_RATE = 0.05             # Amount to decay confidence per fade
    # Opening detection thresholds
    MAPPING_OPENING_MIN_WIDTH_CM = 60.0  # Minimum width for an opening (cm)
    MAPPING_OPENING_MAX_WIDTH_CM = 120.0 # Maximum width for an opening (cm)
    MAPPING_OPENING_CELL_CONF_MIN = 0.6  # Min confidence for opening cell
    # Safe path detection thresholds
    MAPPING_SAFEPATH_MIN_WIDTH_CM = 40.0   # Minimum width for a safe path (cm)
    MAPPING_SAFEPATH_MAX_WIDTH_CM = 200.0  # Maximum width for a safe path (cm)
    MAPPING_SAFEPATH_MIN_LENGTH_CELLS = 6  # Minimum length (cells)
    MAPPING_SAFEPATH_CELL_CONF_MIN = 0.5   # Min confidence for safe path cell

    # ============================================================================
    # OBSTACLE AVOIDANCE SETTINGS
    # ============================================================================
    
    OBSTACLE_IMMEDIATE_THREAT = 20.0  # Distance (cm) to trigger immediate stop
    OBSTACLE_APPROACHING_THREAT = 35.0 # Distance (cm) to prepare for avoidance  
    OBSTACLE_EMERGENCY_STOP = 15.0    # Distance (cm) for emergency halt
    OBSTACLE_SAFE_DISTANCE = 40.0     # Minimum safe following distance
    OBSTACLE_SCAN_INTERVAL = 0.5      # Time (seconds) between scans while moving
    
    # ============================================================================
    # MOVEMENT PARAMETERS
    # ============================================================================
    
    # Step counts for various movements
    TURN_STEPS_SMALL = 1              # Small turn adjustment
    TURN_STEPS_NORMAL = 2             # Normal turn
    TURN_STEPS_LARGE = 4              # Large turn (near 180°)
    WALK_STEPS_SHORT = 1              # Short forward movement
    WALK_STEPS_NORMAL = 2             # Normal forward movement  
    WALK_STEPS_LONG = 3               # Longer forward movement
    BACKUP_STEPS = 3                  # Steps when backing up
    
    # Movement speeds (0-255, PiDog servo range)
    SPEED_SLOW = 80                   # Slow, careful movement
    SPEED_NORMAL = 120                # Normal movement speed
    SPEED_FAST = 200                  # Fast, energetic movement
    SPEED_EMERGENCY = 100             # Emergency avoidance speed
    
    # Turn speeds (should be faster than walk speeds for natural movement)
    SPEED_TURN_SLOW = 100             # Turning speed when walking slow
    SPEED_TURN_NORMAL = 200           # Turning speed when walking normal
    SPEED_TURN_FAST = 220             # Turning speed when walking fast
    
    # ============================================================================
    # TURN CALIBRATION SETTINGS
    # ============================================================================
    
    # Turn angle calibration (steps to degrees ratio at SPEED_TURN_NORMAL=200)
    TURN_DEGREES_PER_STEP = 15        # Approximate degrees per step (3 steps ≈ 45°)
    TURN_90_DEGREES = 6               # Steps for 90-degree turn
    TURN_45_DEGREES = 3               # Steps for 45-degree turn
    TURN_180_DEGREES = 12             # Steps for 180-degree turn
    
    # ============================================================================
    # BEHAVIOR TIMING
    # ============================================================================
    
    PATROL_DURATION_MIN = 30          # Minimum patrol time (seconds)
    PATROL_DURATION_MAX = 120         # Maximum patrol time (seconds)
    REST_DURATION = 20                # Rest behavior duration (seconds)
    INTERACTION_TIMEOUT = 10          # Time to wait for interaction (seconds)
    VOICE_COMMAND_TIMEOUT = 5         # Max time between wake word and command
    
    # ============================================================================
    # SCANNING BEHAVIOR
    # ============================================================================
    
    HEAD_SCAN_RANGE = 45              # Maximum head turn angle (degrees)
    HEAD_SCAN_SPEED = 70              # Head movement speed
    SCAN_SAMPLES = 3                  # Number of distance readings to average
    SCAN_WHILE_MOVING = True          # Perform scans during movement
    # Orientation/Yaw integration
    ORIENTATION_GYRO_SCALE = 1.0      # Scale units to deg/s for gyro Z
    ORIENTATION_BIAS_Z = 0.0          # Bias to subtract from gyro Z
    ORIENTATION_TURN_TOLERANCE_DEG = 5.0
    ORIENTATION_MAX_TURN_TIME_S = 3.0

    # ============================================================================
    # LOCALIZATION / ACTIVE RECOVERY
    # ============================================================================
    # When ENABLE_SENSOR_FUSION is True, PackMind can actively recover localization
    # confidence by performing a short ultrasonic sweep and updating the particle
    # filter. These settings control when and how that happens.
    LOCALIZATION_ACTIVE_RECOVERY = True     # Perform recovery sweeps when confidence is low
    LOCALIZATION_CONFIDENCE_LOW = 0.35      # Threshold (0..1) to trigger recovery
    LOCALIZATION_RECOVERY_MIN_INTERVAL_S = 8.0  # Min seconds between recovery attempts
    LOCALIZATION_RECOVERY_SWEEPS = 1        # Number of sweep passes per attempt
    LOCALIZATION_RECOVERY_SWEEP_LEFT = 50   # Left sweep limit (deg)
    LOCALIZATION_RECOVERY_SWEEP_RIGHT = 50  # Right sweep limit (deg)
    LOCALIZATION_RECOVERY_STEP_DEG = 10     # Sweep step size (deg)
    
    # ============================================================================
    # SOUND RESPONSE
    # ============================================================================
    
    SOUND_HEAD_SENSITIVITY = 2.5      # Sound direction to head movement ratio
    SOUND_BODY_TURN_THRESHOLD = 45    # Head angle before body turns too
    SOUND_RESPONSE_ENERGY_MIN = 0.4   # Minimum energy to respond to sound
    
    # ============================================================================
    # ENERGY SYSTEM
    # ============================================================================
    
    ENERGY_DECAY_RATE = 0.001         # Energy loss per update cycle
    ENERGY_INTERACTION_BOOST = 0.05   # Energy gain from interactions
    ENERGY_REST_RECOVERY = 0.002      # Energy recovery while resting
    ENERGY_LOW_THRESHOLD = 0.3        # Switch to low-energy behaviors
    ENERGY_HIGH_THRESHOLD = 0.7       # Switch to high-energy behaviors
    
    # ============================================================================
    # STUCK DETECTION
    # ============================================================================
    
    STUCK_AVOIDANCE_LIMIT = 3         # Avoidances before "stuck" mode
    STUCK_TIME_WINDOW = 10.0          # Time window for stuck detection (seconds)
    STUCK_MOVEMENT_THRESHOLD = 1000   # IMU threshold for movement detection
    
    # ============================================================================
    # VOICE COMMANDS
    # ============================================================================
    
    WAKE_WORD = "pidog"               # Voice activation word
    VOICE_VOLUME_DEFAULT = 70         # Default speaking volume
    VOICE_VOLUME_EXCITED = 80         # Volume when excited
    VOICE_VOLUME_QUIET = 40           # Volume when tired/sad
    
    # ============================================================================
    # LOGGING
    # ============================================================================
    
    LOG_MAX_ENTRIES = 1000            # Maximum log entries in memory
    LOG_STATUS_INTERVAL = 10          # Status log interval (seconds)

    # ============================================================================
    # SYSTEM HEALTH / PERFORMANCE THRESHOLDS
    # ============================================================================

    # When system load per core exceeds this multiplier, treat as degraded
    HEALTH_LOAD_PER_CORE_WARN_MULTIPLIER = 1.5
    # When CPU temperature exceeds this (Celsius), treat as degraded
    HEALTH_TEMP_WARN_C = 70.0
    # When memory used percent exceeds this, treat as degraded
    HEALTH_MEM_USED_WARN_PCT = 85.0
    # When degraded, scanning interval will be adjusted conservatively:
    # new_interval = min(base * MULTIPLIER, base + ABS_DELTA)
    HEALTH_SCAN_INTERVAL_MULTIPLIER = 2.0
    HEALTH_SCAN_INTERVAL_ABS_DELTA = 1.0

    # How frequently the HealthMonitor samples and evaluates
    HEALTH_MONITOR_INTERVAL_S = 5.0
    # Actions to take under degraded health (informational for now)
    HEALTH_ACTIONS = ["throttle_scans"]  # future: "reduce_speed", "disable_nonessential"
    # Factor to reduce speeds when degraded (if applied in code)
    HEALTH_SPEED_REDUCTION_FACTOR = 0.8
    # Features to disable when degraded (by name in config toggles)
    HEALTH_DISABLE_FEATURES = []

    # ============================================================================
    # SCANNING AND SENSING DYNAMICS
    # ============================================================================
    SCAN_INTERVAL_MIN = 0.2          # minimum allowed scan interval (s)
    SCAN_INTERVAL_MAX = 2.0          # maximum allowed scan interval (s)
    SCAN_DYNAMIC_AGGRESSIVENESS = 0.5  # 0..1; higher adjusts scan rate more aggressively
    SCAN_DEBOUNCE_S = 0.05           # ignore new readings within this time window
    SCAN_SMOOTHING_ALPHA = 0.4       # EMA smoothing for distances (0..1)

    # Sensor monitor cadence and error backoff
    SENSOR_MONITOR_RATE_HZ = 20.0
    SENSOR_MONITOR_BACKOFF_ON_ERROR_S = 0.2

    # ============================================================================
    # VOICE RUNTIME
    # ============================================================================
    VOICE_WAKE_TIMEOUT_S = 5.0
    VOICE_VAD_SENSITIVITY = 0.5      # 0..1
    VOICE_MIC_INDEX = 0
    VOICE_LANGUAGE = "en-US"
    VOICE_NOISE_SUPPRESSION = True

    # ============================================================================
    # FACE RECOGNITION SYSTEM
    # ============================================================================
    FACE_RECOGNITION_THRESHOLD = 0.6      # Similarity threshold for recognition (0.0-1.0)
    FACE_DETECTION_INTERVAL = 2.0         # Seconds between face detection attempts
    FACE_MAX_FACES_PER_FRAME = 3          # Maximum faces to process per frame
    FACE_CAMERA_WIDTH = 640               # Camera resolution width
    FACE_CAMERA_HEIGHT = 480              # Camera resolution height
    FACE_CAMERA_FPS = 15                  # Camera frames per second
    FACE_DATA_DIR = "data/faces"          # Directory for face data storage
    FACE_AUTO_SAVE_INTERVAL = 300         # Auto-save interval (seconds)
    FACE_INTERACTION_TIMEOUT = 30         # Seconds before interaction times out
    FACE_PERSONALITY_LEARNING_RATE = 0.1  # Rate of personality trait adaptation (0.0-1.0)
    FACE_MEMORY_RETENTION_DAYS = 365      # Days to retain interaction history
    FACE_CONFIDENCE_DISPLAY_MIN = 0.7     # Minimum confidence to display recognition

    # ============================================================================
    # DYNAMIC BALANCE SYSTEM
    # ============================================================================
    BALANCE_SAMPLE_RATE = 20.0            # IMU sampling rate (Hz)
    BALANCE_CALIBRATION_TIME = 5.0        # Calibration duration (seconds)
    BALANCE_HISTORY_SIZE = 100            # Number of readings to keep in memory
    BALANCE_STABILITY_WINDOW = 10         # Window size for stability analysis
    BALANCE_DATA_DIR = "data/balance"     # Directory for balance data storage
    
    # Balance thresholds (degrees)
    BALANCE_SLIGHT_TILT_THRESHOLD = 15.0  # Minor tilt detection
    BALANCE_UNSTABLE_TILT_THRESHOLD = 25.0 # Unstable balance threshold
    BALANCE_CRITICAL_TILT_THRESHOLD = 35.0 # Critical tilt requiring immediate action
    
    # Motion detection
    BALANCE_RAPID_MOTION_THRESHOLD = 5.0  # Rapid angular velocity threshold (rad/s)
    
    # Correction behavior
    BALANCE_CORRECTION_COOLDOWN = 2.0     # Minimum time between corrections (seconds)

    # ============================================================================
    # ENHANCED AUDIO PROCESSING SYSTEM
    # ============================================================================
    
    # Audio hardware settings
    AUDIO_SAMPLE_RATE = 44100             # Audio sample rate (Hz)
    AUDIO_CHANNELS = 1                    # Number of audio channels (1=mono, 2=stereo)
    AUDIO_CHUNK_SIZE = 1024               # Audio buffer chunk size (samples)
    AUDIO_BUFFER_DURATION = 2.0           # Audio buffer duration (seconds)
    AUDIO_INPUT_DEVICE_INDEX = None       # Audio input device (None=default)
    
    # Audio analysis settings
    AUDIO_CALIBRATION_TIME = 3.0          # Background noise calibration time (seconds)
    AUDIO_HISTORY_SIZE = 200              # Number of audio samples to keep in memory
    AUDIO_SILENCE_THRESHOLD = 0.01        # RMS threshold for silence detection
    AUDIO_LOUD_NOISE_THRESHOLD = 0.5      # RMS threshold for loud noise events
    
    # Voice detection settings
    AUDIO_VOICE_FREQ_MIN = 85.0           # Minimum voice frequency (Hz)
    AUDIO_VOICE_FREQ_MAX = 255.0          # Maximum voice frequency (Hz) 
    AUDIO_VOICE_THRESHOLD = 0.3           # Voice energy ratio threshold (0.0-1.0)
    
    # Sound source tracking
    AUDIO_DIRECTION_HISTORY_SIZE = 50     # Number of direction readings to keep
    AUDIO_DIRECTION_CHANGE_THRESHOLD = 15.0 # Degrees for significant direction change
    AUDIO_SOURCE_DIRECTION_TOLERANCE = 30.0 # Degrees tolerance for same source
    AUDIO_SOURCE_TIMEOUT = 5.0            # Seconds before source is considered lost
    
    # Event logging
    AUDIO_EVENT_HISTORY_SIZE = 500        # Number of audio events to keep in memory
    AUDIO_DATA_DIR = "data/audio"         # Directory for audio session data storage

    # ============================================================================
    # SAFETY / WATCHDOG
    # ============================================================================
    WATCHDOG_HEARTBEAT_INTERVAL_S = 0.5
    WATCHDOG_TIMEOUT_S = 2.0
    WATCHDOG_ACTION = "stop_and_crouch"  # or "power_down"

    # ============================================================================
    # LOGGING / TELEMETRY
    # ============================================================================
    LOG_LEVEL = "INFO"               # "DEBUG" | "INFO" | "WARN" | "ERROR"
    LOG_FILE_MAX_MB = 10
    LOG_FILE_BACKUPS = 5

    TELEMETRY_ENABLED = False
    TELEMETRY_SAMPLE_INTERVAL_S = 2.0
    TELEMETRY_ENDPOINT = ""

    # ============================================================================
    # LEARNING / PERSISTENCE
    # ============================================================================
    LEARNING_STATE_PATH = "data/learning_state.json"
    LEARNING_AUTOSAVE_INTERVAL_S = 30.0
    LEARNING_DECAY = 0.995

    # ============================================================================
    # NAVIGATION (optional; used when ENABLE_AUTONOMOUS_NAVIGATION)
    # ============================================================================
    NAV_REPLAN_INTERVAL_S = 1.0
    NAV_GOAL_TOLERANCE_CM = 10.0
    NAV_OBSTACLE_INFLATION_CM = 10.0
    NAV_COST_TURN_WEIGHT = 1.2
    NAV_COST_FORWARD_WEIGHT = 1.0
    
    # ============================================================================
    # ADVANCED FEATURES (when enabled)
    # ============================================================================
    
    SLAM_MAP_RESOLUTION = 0.05        # Map resolution (meters per cell)
    SLAM_UPDATE_FREQUENCY = 10        # SLAM updates per second
    PARTICLE_FILTER_COUNT = 100       # Number of particles for localization
    SURFACE_CALIBRATION_TIME = 5      # Sensor calibration duration (seconds)


# ============================================================================
# PRESET CONFIGURATIONS
# ============================================================================

class SimpleConfig(PiDogConfig):
    """
    Simple mode configuration - minimal features, conservative behavior
    Good for: Basic operation, limited resources, indoor safe environment
    """
    
    # Disable advanced features
    ENABLE_SLAM_MAPPING = False
    ENABLE_SENSOR_FUSION = False
    ENABLE_INTELLIGENT_SCANNING = False
    ENABLE_AUTONOMOUS_NAVIGATION = False
    ENABLE_EMOTIONAL_SYSTEM = False
    ENABLE_LEARNING_SYSTEM = False
    ENABLE_FACE_RECOGNITION = False  # Simplified mode - no face recognition
    ENABLE_DYNAMIC_BALANCE = False  # Disabled for simplicity
    ENABLE_ENHANCED_AUDIO = False  # Basic audio only
    
    # Conservative obstacle avoidance
    OBSTACLE_IMMEDIATE_THREAT = 30.0
    OBSTACLE_APPROACHING_THREAT = 50.0
    
    # Slower, more careful movement
    SPEED_NORMAL = 80
    SPEED_FAST = 100
    SPEED_TURN_NORMAL = 120
    TURN_STEPS_NORMAL = 1


class AdvancedConfig(PiDogConfig):
    """
    Advanced mode configuration - all features enabled, aggressive exploration
    Good for: Full AI capabilities, outdoor exploration, tech demonstrations
    """
    
    # Enable all features
    ENABLE_SLAM_MAPPING = True
    ENABLE_SENSOR_FUSION = True
    ENABLE_INTELLIGENT_SCANNING = True
    ENABLE_AUTONOMOUS_NAVIGATION = True
    ENABLE_EMOTIONAL_SYSTEM = True
    ENABLE_LEARNING_SYSTEM = True
    ENABLE_PATROL_LOGGING = True
    ENABLE_FACE_RECOGNITION = True  # Full AI capabilities
    ENABLE_DYNAMIC_BALANCE = True  # Advanced balance monitoring
    ENABLE_ENHANCED_AUDIO = True  # Full audio processing capabilities
    
    # Advanced face recognition settings
    FACE_RECOGNITION_THRESHOLD = 0.5  # Lower threshold for better detection
    FACE_DETECTION_INTERVAL = 1.0     # More frequent detection
    FACE_MAX_FACES_PER_FRAME = 5      # Process more faces
    FACE_PERSONALITY_LEARNING_RATE = 0.15  # Faster learning
    
    # Enhanced balance monitoring settings
    BALANCE_SAMPLE_RATE = 30.0  # Higher sampling rate for better response
    BALANCE_CORRECTION_COOLDOWN = 1.5  # Faster corrections
    
    # Advanced audio processing settings
    AUDIO_SAMPLE_RATE = 48000  # Higher quality audio
    AUDIO_CALIBRATION_TIME = 2.0  # Faster calibration
    AUDIO_VOICE_THRESHOLD = 0.25  # More sensitive voice detection
    
    # Aggressive exploration settings
    OBSTACLE_IMMEDIATE_THREAT = 15.0
    OBSTACLE_APPROACHING_THREAT = 25.0
    
    # Fast, energetic movement
    SPEED_NORMAL = 120
    SPEED_FAST = 200
    SPEED_TURN_NORMAL = 200
    SPEED_TURN_FAST = 220


class IndoorPetConfig(PiDogConfig):
    """
    Indoor pet mode configuration - friendly, safe, learning-enabled
    Good for: Home environment, family interaction, gentle behavior
    """
    
    # Features for indoor pet behavior
    ENABLE_SLAM_MAPPING = True
    ENABLE_SENSOR_FUSION = False  # Not needed indoors
    ENABLE_INTELLIGENT_SCANNING = True
    ENABLE_EMOTIONAL_SYSTEM = True
    ENABLE_LEARNING_SYSTEM = True
    ENABLE_PATROL_LOGGING = True
    ENABLE_AUTONOMOUS_NAVIGATION = False  # Manual control preferred
    ENABLE_FACE_RECOGNITION = True  # Perfect for family interaction
    ENABLE_DYNAMIC_BALANCE = True  # Safety for indoor play
    ENABLE_ENHANCED_AUDIO = True  # Family voice recognition and interaction
    
    # Indoor-friendly face recognition settings
    FACE_DETECTION_INTERVAL = 1.5     # Moderate detection frequency
    FACE_PERSONALITY_LEARNING_RATE = 0.12  # Good learning for family bonds
    FACE_INTERACTION_TIMEOUT = 45     # Longer interaction timeouts for family time
    
    # Safe indoor distances
    OBSTACLE_IMMEDIATE_THREAT = 25.0
    OBSTACLE_APPROACHING_THREAT = 40.0
    
    # Gentle movement for indoors
    SPEED_NORMAL = 100
    SPEED_FAST = 150
    VOICE_VOLUME_DEFAULT = 50  # Quieter indoors
    
    # More responsive to interaction
    ENERGY_INTERACTION_BOOST = 0.08
    INTERACTION_TIMEOUT = 15


class ExplorerConfig(PiDogConfig):
    """
    Explorer mode configuration - maximum mapping and navigation
    Good for: Mapping unknown areas, autonomous exploration, research
    """
    
    # Full exploration capabilities
    ENABLE_SLAM_MAPPING = True
    ENABLE_SENSOR_FUSION = True
    ENABLE_INTELLIGENT_SCANNING = True
    ENABLE_AUTONOMOUS_NAVIGATION = True
    ENABLE_PATROL_LOGGING = True
    
    # Moderate emotional responses (focus on exploration)
    ENABLE_EMOTIONAL_SYSTEM = False
    ENABLE_LEARNING_SYSTEM = False
    ENABLE_FACE_RECOGNITION = False  # Focus on mapping, not social interaction
    ENABLE_DYNAMIC_BALANCE = True  # Critical for outdoor terrain
    ENABLE_ENHANCED_AUDIO = True  # Environmental sound awareness for outdoor exploration
    
    # Balanced exploration settings
    OBSTACLE_IMMEDIATE_THREAT = 18.0
    OBSTACLE_APPROACHING_THREAT = 30.0
    
    # Consistent, reliable movement
    SPEED_NORMAL = 120
    SPEED_FAST = 180
    
    # More frequent mapping updates
    SLAM_UPDATE_FREQUENCY = 15
    LOG_STATUS_INTERVAL = 5


# ============================================================================
# CONFIGURATION LOADER
# ============================================================================

def load_config(config_name="default"):
    """
    Load a configuration preset
    
    Args:
        config_name (str): Configuration to load
            - "default" or "standard": Standard PiDogConfig
            - "simple": SimpleConfig  
            - "advanced": AdvancedConfig
            - "indoor": IndoorPetConfig
            - "explorer": ExplorerConfig
    
    Returns:
        PiDogConfig: Configuration object
    """
    
    config_map = {
        "default": PiDogConfig,
        "standard": PiDogConfig,
        "simple": SimpleConfig,
        "advanced": AdvancedConfig,
        "indoor": IndoorPetConfig,
        "pet": IndoorPetConfig,  # Alias
        "explorer": ExplorerConfig,
        "exploration": ExplorerConfig,  # Alias
    }
    
    config_class = config_map.get(config_name.lower(), PiDogConfig)
    return config_class()


# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

def validate_config(config):
    """
    Validate configuration values and provide warnings for potential issues
    
    Args:
        config (PiDogConfig): Configuration to validate
        
    Returns:
        list: List of validation warnings (empty if no issues)
    """
    
    warnings = []
    
    # Speed validation
    if config.SPEED_NORMAL > 255:
        warnings.append(f"SPEED_NORMAL ({config.SPEED_NORMAL}) exceeds servo limit (255)")
    
    if config.SPEED_TURN_NORMAL <= config.SPEED_NORMAL:
        warnings.append("SPEED_TURN_NORMAL should be faster than SPEED_NORMAL for natural movement")
    
    # Obstacle distance validation
    if config.OBSTACLE_IMMEDIATE_THREAT >= config.OBSTACLE_APPROACHING_THREAT:
        warnings.append("OBSTACLE_IMMEDIATE_THREAT should be less than OBSTACLE_APPROACHING_THREAT")
    
    if config.OBSTACLE_EMERGENCY_STOP >= config.OBSTACLE_IMMEDIATE_THREAT:
        warnings.append("OBSTACLE_EMERGENCY_STOP should be less than OBSTACLE_IMMEDIATE_THREAT")
    
    # Feature dependency validation
    if config.ENABLE_SENSOR_FUSION and not config.ENABLE_SLAM_MAPPING:
        warnings.append("ENABLE_SENSOR_FUSION requires ENABLE_SLAM_MAPPING to be True")
    
    if config.ENABLE_AUTONOMOUS_NAVIGATION and not config.ENABLE_SLAM_MAPPING:
        warnings.append("ENABLE_AUTONOMOUS_NAVIGATION requires ENABLE_SLAM_MAPPING to be True")
    
    # Performance warnings
    if config.OBSTACLE_SCAN_INTERVAL < getattr(config, 'SCAN_INTERVAL_MIN', 0.2):
        warnings.append("OBSTACLE_SCAN_INTERVAL below SCAN_INTERVAL_MIN may impact performance")
    if config.OBSTACLE_SCAN_INTERVAL > getattr(config, 'SCAN_INTERVAL_MAX', 2.0):
        warnings.append("OBSTACLE_SCAN_INTERVAL above SCAN_INTERVAL_MAX may reduce responsiveness")
    
    if config.LOG_MAX_ENTRIES > 5000:
        warnings.append("Large log size may consume significant memory")
    
    return warnings


if __name__ == "__main__":
    """
    Test configuration loading and validation
    """
    print("PiDog Configuration System Test")
    print("===============================")
    
    # Test all preset configurations
    presets = ["default", "simple", "advanced", "indoor", "explorer"]
    
    for preset_name in presets:
        print(f"\n--- Testing {preset_name.upper()} Configuration ---")
        config = load_config(preset_name)
        warnings = validate_config(config)
        
        print(f"SLAM Mapping: {config.ENABLE_SLAM_MAPPING}")
        print(f"Speed Normal: {config.SPEED_NORMAL}")
        print(f"Turn Speed: {config.SPEED_TURN_NORMAL}")
        print(f"Obstacle Threshold: {config.OBSTACLE_IMMEDIATE_THREAT}cm")
        
        if warnings:
            print("⚠️ Warnings:")
            for warning in warnings:
                print(f"  - {warning}")
        else:
            print("✅ Configuration valid")
