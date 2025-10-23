"""
CanineCore Configuration (Beginner-friendly)
===========================================

This configuration mirrors the style of PackMind's pidog_config.py, with grouped
options and handy presets for common scenarios.
"""

class CanineConfig:
    # =====================================================================
    # FEATURE TOGGLES
    # =====================================================================
    ENABLE_VOICE_COMMANDS = True
    ENABLE_SLAM_MAPPING = True
    ENABLE_SENSOR_FUSION = True
    ENABLE_INTELLIGENT_SCANNING = True
    ENABLE_EMOTIONAL_SYSTEM = True
    ENABLE_LEARNING_SYSTEM = True
    ENABLE_AUTONOMOUS_NAVIGATION = True

    # =====================================================================
    # OBSTACLE AVOIDANCE
    # =====================================================================
    OBSTACLE_IMMEDIATE_THREAT = 20.0
    OBSTACLE_APPROACHING_THREAT = 35.0
    OBSTACLE_EMERGENCY_STOP = 15.0
    OBSTACLE_SAFE_DISTANCE = 40.0
    OBSTACLE_SCAN_INTERVAL = 0.5

    # =====================================================================
    # MOVEMENT PARAMETERS
    # =====================================================================
    TURN_STEPS_SMALL = 1
    TURN_STEPS_NORMAL = 2
    TURN_STEPS_LARGE = 4
    WALK_STEPS_SHORT = 1
    WALK_STEPS_NORMAL = 2
    WALK_STEPS_LONG = 3
    BACKUP_STEPS = 3

    SPEED_SLOW = 80
    SPEED_NORMAL = 120
    SPEED_FAST = 200
    SPEED_EMERGENCY = 100

    SPEED_TURN_SLOW = 100
    SPEED_TURN_NORMAL = 200
    SPEED_TURN_FAST = 220

    # =====================================================================
    # BEHAVIOR TIMING
    # =====================================================================
    PATROL_DURATION_MIN = 30
    PATROL_DURATION_MAX = 120
    REST_DURATION = 20
    INTERACTION_TIMEOUT = 10
    VOICE_COMMAND_TIMEOUT = 5

    # =====================================================================
    # SCANNING
    # =====================================================================
    HEAD_SCAN_RANGE = 45
    HEAD_SCAN_SPEED = 70
    SCAN_SAMPLES = 3
    SCAN_WHILE_MOVING = True

    # =====================================================================
    # SOUND RESPONSE
    # =====================================================================
    SOUND_HEAD_SENSITIVITY = 2.5
    SOUND_BODY_TURN_THRESHOLD = 45
    SOUND_RESPONSE_ENERGY_MIN = 0.4

    # =====================================================================
    # REACTIONS (IMU / TOUCH / SOUND)
    # =====================================================================
    REACTIONS_INTERVAL = 0.5            # seconds between reaction checks
    REACTIONS_LIFT_THRESHOLD = 25000    # IMU accel (x) above this → lifted
    REACTIONS_PLACE_THRESHOLD = -25000  # IMU accel (x) below this → placed down
    REACTIONS_FLIP_ROLL_THRESHOLD = 30000  # abs(roll) above this → flipped

    # =====================================================================
    # ENERGY SYSTEM
    # =====================================================================
    ENERGY_DECAY_RATE = 0.001
    ENERGY_INTERACTION_BOOST = 0.05
    ENERGY_REST_RECOVERY = 0.002
    ENERGY_LOW_THRESHOLD = 0.3
    ENERGY_HIGH_THRESHOLD = 0.7

    # =====================================================================
    # BATTERY
    # =====================================================================
    LOW_BATTERY_THRESHOLD = 20
    CRITICAL_BATTERY_THRESHOLD = 10

    # =====================================================================
    # VOICE
    # =====================================================================
    WAKE_WORD = "pidog"
    VOICE_VOLUME_DEFAULT = 70
    VOICE_VOLUME_EXCITED = 80
    VOICE_VOLUME_QUIET = 40

    # =====================================================================
    # LOGGING
    # =====================================================================
    LOG_MAX_ENTRIES = 1000
    LOG_STATUS_INTERVAL = 10

    # =====================================================================
    # CONTROL & UI
    # =====================================================================
    INTERRUPT_KEY = "esc"

    # =====================================================================
    # GUARD MODE
    # =====================================================================
    GUARD_DETECT_MM = 100.0  # distance threshold to trigger alert (millimeters)

    # Behavior aliases available for selection in the control script
    AVAILABLE_BEHAVIORS = [
        "idle_behavior",
        "smart_patrol",
        "smarter_patrol",
        "voice_patrol",
        "guard_mode",
        "whisper_voice_control",
        "find_open_space",
    ]


class SimplePreset(CanineConfig):
    ENABLE_SLAM_MAPPING = False
    ENABLE_SENSOR_FUSION = False
    ENABLE_INTELLIGENT_SCANNING = False
    ENABLE_AUTONOMOUS_NAVIGATION = False
    ENABLE_EMOTIONAL_SYSTEM = False
    ENABLE_LEARNING_SYSTEM = False

    OBSTACLE_IMMEDIATE_THREAT = 30.0
    OBSTACLE_APPROACHING_THREAT = 50.0

    SPEED_NORMAL = 80
    SPEED_FAST = 100
    SPEED_TURN_NORMAL = 120
    TURN_STEPS_NORMAL = 1


class PatrolPreset(CanineConfig):
    ENABLE_EMOTIONAL_SYSTEM = True
    ENABLE_LEARNING_SYSTEM = True
    AVAILABLE_BEHAVIORS = [
        "idle_behavior",
        "smart_patrol",
        "smarter_patrol",
        "find_open_space",
    ]


class InteractivePreset(CanineConfig):
    ENABLE_VOICE_COMMANDS = True
    ENABLE_EMOTIONAL_SYSTEM = True
    AVAILABLE_BEHAVIORS = [
        "idle_behavior",
        "voice_patrol",
        "whisper_voice_control",
        "guard_mode",
    ]


PRESETS = {
    "simple": SimplePreset,
    "patrol": PatrolPreset,
    "interactive": InteractivePreset,
    "default": CanineConfig,
}
