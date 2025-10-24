"""
CanineCore Configuration (Beginner-friendly)
===========================================

This configuration mirrors the style of PackMind's packmind_config.py, with grouped
options and handy presets for common scenarios.
"""

class CanineConfig:
    # =====================================================================
    # FEATURE TOGGLES
    # =====================================================================
    ENABLE_VOICE_COMMANDS = True
    # New modular services toggles
    ENABLE_SAFETY_SUPERVISOR = True
    ENABLE_BATTERY_MONITOR = True
    ENABLE_IMU_MONITOR = True
    ENABLE_TELEMETRY = False
    ENABLE_DEFAULT_HOOKS = True
    ENABLE_SENSORS_FACADE = True
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
    # Additional scan tuning
    SCAN_DEBOUNCE_S = 0.05              # ignore jittery repeat reads within this window
    SCAN_SMOOTHING_ALPHA = 0.4          # EMA smoothing factor for distances

    # =====================================================================
    # SOUND RESPONSE
    # =====================================================================
    SOUND_HEAD_SENSITIVITY = 2.5
    SOUND_BODY_TURN_THRESHOLD = 45
    SOUND_RESPONSE_ENERGY_MIN = 0.4
    SOUND_COOLDOWN_S = 1.5              # cooldown between sound-driven turns

    # =====================================================================
    # REACTIONS (IMU / TOUCH / SOUND)
    # =====================================================================
    REACTIONS_INTERVAL = 0.5            
    REACTIONS_LIFT_THRESHOLD = 25000    
    REACTIONS_PLACE_THRESHOLD = -25000  # IMU accel (x) below this → placed down
    REACTIONS_FLIP_ROLL_THRESHOLD = 30000  # abs(roll) above this → flipped
    TOUCH_DEBOUNCE_S = 0.1
    REACTION_COOLDOWN_S = 1.0

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
    LOW_BATTERY_REDUCE_SPEED_FACTOR = 0.8
    CRITICAL_BATTERY_REST_BEHAVIOR = True
    CHARGING_DETECT_MIN_DELTA_V = 0.1

    # =====================================================================
    # VOICE
    # =====================================================================
    WAKE_WORD = "pidog"
    VOICE_VOLUME_DEFAULT = 70
    VOICE_VOLUME_EXCITED = 80
    VOICE_VOLUME_QUIET = 40
    VOICE_TTS_RATE = 1.0
    VOICE_TTS_PITCH = 1.0

    # =====================================================================
    # LOGGING
    # =====================================================================
    LOG_MAX_ENTRIES = 1000
    LOG_STATUS_INTERVAL = 10
    LOG_LEVEL = "INFO"
    LOG_FILE_MAX_MB = 10
    LOG_FILE_BACKUPS = 5

    # =====================================================================
    # CONTROL & UI
    # =====================================================================
    INTERRUPT_KEY = "esc"
    INTERRUPT_LONG_PRESS_S = 1.0
    UI_STATUS_OVERLAY = False

    # =====================================================================
    # GUARD MODE
    # =====================================================================
    # Legacy absolute distance trigger (kept for compatibility)
    GUARD_DETECT_MM = 100.0  # distance threshold to trigger alert (millimeters)
    # Continuous scan parameters
    GUARD_SCAN_YAW_MAX_DEG = 90       # max yaw sweep to either side
    GUARD_SCAN_STEP_DEG = 15          # step size per sample
    GUARD_SCAN_SETTLE_S = 0.15        # settle time after head move before read
    GUARD_BETWEEN_READS_S = 0.05      # tiny pause between successive angle reads
    # Baseline & deviation detection
    GUARD_BASELINE_EMA = 0.20         # per-angle EMA smoothing for baseline
    GUARD_DEVIATION_MM = 120.0        # absolute drop vs baseline to consider approaching
    GUARD_DEVIATION_PCT = 0.25        # percent drop vs baseline to consider approaching
    GUARD_CONFIRM_WINDOW = 3          # window of recent samples per angle
    GUARD_CONFIRM_THRESHOLD = 2       # required positives in window to alert
    GUARD_ALERT_COOLDOWN_S = 3.0      # cooldown between alerts

    # =====================================================================
    # PATROL (SMART PATROL)
    # =====================================================================
    # Lightweight head scans at patrol cadence with approach confirmation
    PATROL_SCAN_YAW_MAX_DEG = 45       # smaller than guard for quicker cycles
    PATROL_SCAN_STEP_DEG = 15          # sample granularity
    PATROL_SCAN_SETTLE_S = 0.12        # settle after head move before read
    PATROL_BETWEEN_READS_S = 0.04      # pause between reads
    PATROL_BASELINE_EMA = 0.25         # smoothing for per-angle baseline
    PATROL_APPROACH_DEVIATION_MM = 100.0  # absolute drop vs baseline
    PATROL_APPROACH_DEVIATION_PCT = 0.20  # percent drop vs baseline
    PATROL_CONFIRM_WINDOW = 3          # N-of-M confirmation window
    PATROL_CONFIRM_THRESHOLD = 2       # positives needed to confirm
    PATROL_ALERT_COOLDOWN_S = 2.0      # cooldown between reactive maneuvers
    PATROL_TURN_STEPS_ON_ALERT = 1     # small in-place turn when approaching

    # =====================================================================
    # OPEN SPACE (FIND_OPEN_SPACE)
    # =====================================================================
    OPEN_SPACE_SCAN_YAW_MAX_DEG = 60     # scan a wider arc than patrol
    OPEN_SPACE_SCAN_STEP_DEG = 15
    OPEN_SPACE_SCAN_SETTLE_S = 0.12
    OPEN_SPACE_BETWEEN_READS_S = 0.04
    OPEN_SPACE_MIN_GAP_WIDTH_DEG = 30    # contiguous width required to consider a gap
    OPEN_SPACE_MIN_SCORE_MM = 600.0      # min distance per angle to count toward a gap (mm)
    OPEN_SPACE_CONFIRM_WINDOW = 2        # number of quick scans
    OPEN_SPACE_CONFIRM_THRESHOLD = 2     # require same pick across scans
    OPEN_SPACE_FORWARD_STEPS = 2         # advance after turning toward best gap
    OPEN_SPACE_TURN_SPEED = 200          # turn speed override (falls back to SPEED_TURN_NORMAL)

    # Behavior aliases available for selection in the control script
    AVAILABLE_BEHAVIORS = [
        "idle_behavior",
        "smart_patrol",
        "smarter_patrol",
        "voice_patrol",
        "guard_mode",
        "whisper_voice_control",
        "find_open_space",
        "event_hooks_demo",
    ]

    # =====================================================================
    # MOVEMENT / KINEMATICS TUNING
    # =====================================================================
    WALK_GAIT = "default"                # placeholder for future gait profiles
    TURN_BIAS_DEGREES = 0                # corrects systemic turn bias
    STEP_PAUSE_S = 0.02                  # micro pause between steps
    SPEED_RAMP_UP_MS = 150
    SPEED_RAMP_DOWN_MS = 150

    # =====================================================================
    # OBSTACLE AVOIDANCE DETAILS
    # =====================================================================
    OBSTACLE_HYSTERESIS_CM = 3.0
    OBSTACLE_SIDE_BIAS = 0.0            # negative favors left; positive favors right
    BACKUP_DISTANCE_SCALE = 1.0         # scales BACKUP_STEPS on emergency

    # =====================================================================
    # SENSORS / FILTERING
    # =====================================================================
    IMU_LPF_ALPHA = 0.3
    ULTRASONIC_MIN_CM = 3.0
    ULTRASONIC_MAX_CM = 200.0
    ULTRASONIC_OUTLIER_REJECT_Z = 2.5

    # =====================================================================
    # BEHAVIOR ORCHESTRATION
    # =====================================================================
    BEHAVIOR_SELECTION_MODE = "weighted"  # or "sequential"
    BEHAVIOR_WEIGHTS = {                   # used when selection mode = weighted
        "idle_behavior": 1.0,
        "smart_patrol": 1.0,
        "smarter_patrol": 1.0,
        "voice_patrol": 1.0,
        "guard_mode": 1.0,
        "whisper_voice_control": 1.0,
        "find_open_space": 1.0,
    }
    BEHAVIOR_MIN_DWELL_S = 10.0

    # =====================================================================
    # SAFETY
    # =====================================================================
    EMERGENCY_STOP_POSE = "crouch"
    SAFETY_MAX_TILT_DEG = 45
    SAFETY_MAX_ROLL_DEG = 45


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
