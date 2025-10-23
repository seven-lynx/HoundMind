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
    if config.OBSTACLE_SCAN_INTERVAL < 0.2:
        warnings.append("Very fast scan interval may impact performance")
    
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
