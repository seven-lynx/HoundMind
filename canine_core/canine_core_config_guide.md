# CanineCore Configuration Guide

This guide explains every option in `canine_core/config/canine_config.py` and how it affects behaviors. Use it with the interactive launcher `canine_core/control.py`. Presets live in the same file and can be selected in the controller.

## Feature toggles
- ENABLE_VOICE_COMMANDS: Enable voice pipeline (VoiceBehavior/VoiceService).
- ENABLE_SLAM_MAPPING: Reserve for future mapping features.
- ENABLE_SENSOR_FUSION: Reserve for fused sensor logic (IMU + distance + audio).
- ENABLE_INTELLIGENT_SCANNING: Allow adaptive scan strategies (future).
- ENABLE_EMOTIONAL_SYSTEM: Enable LED emotion themes and effects.
- ENABLE_LEARNING_SYSTEM: Enable long-term memory (obstacle maps, habits).
- ENABLE_AUTONOMOUS_NAVIGATION: Enable advanced navigation modes.

## Obstacle avoidance
- OBSTACLE_IMMEDIATE_THREAT (cm): Very close; behavior should react urgently.
- OBSTACLE_APPROACHING_THREAT (cm): Close side obstacles; bias turns away.
- OBSTACLE_EMERGENCY_STOP (cm): Emergency retreat threshold straight ahead.
- OBSTACLE_SAFE_DISTANCE (cm): If forward < this, steer to freer side.
- OBSTACLE_SCAN_INTERVAL (s): Time between patrol scan cycles.

Recommended ranges: 15–80 cm depending on environment; start with defaults.

## Movement parameters
- TURN_STEPS_SMALL|NORMAL|LARGE: Step counts for turning granularity.
- WALK_STEPS_SHORT|NORMAL|LONG: Step counts for forward movements.
- BACKUP_STEPS: Steps when retreating after an obstacle.
- SPEED_SLOW|NORMAL|FAST: General motion speeds.
- SPEED_EMERGENCY: Speed for retreats and emergency moves.
- SPEED_TURN_SLOW|NORMAL|FAST: Speeds specific to turning actions.

Notes: Step counts scale angular/linear distance; speeds are device-specific.

## Behavior timing
- PATROL_DURATION_MIN|MAX (s): Suggested scheduling window for patrol runs.
- REST_DURATION (s): Idle rest between active segments.
- INTERACTION_TIMEOUT (s): Timeouts for UI/interaction prompts.
- VOICE_COMMAND_TIMEOUT (s): Timeout for voice listening segments.

## Scanning
- HEAD_SCAN_RANGE (deg): Head sweep angle left/right during scans.
- HEAD_SCAN_SPEED: Speed of head movement during scans.
- SCAN_SAMPLES: Samples per scan position (future use).
- SCAN_WHILE_MOVING: Allow concurrent scan + motion (future use).
- SCAN_DEBOUNCE_S (s): Debounce window to ignore jittery repeated readings.
- SCAN_SMOOTHING_ALPHA (0..1): EMA smoothing factor for ultrasonic distances.

## Sound response
- SOUND_HEAD_SENSITIVITY: Head responsiveness to sound (future use).
- SOUND_BODY_TURN_THRESHOLD (deg): Angle to trigger body turn toward sound.
- SOUND_RESPONSE_ENERGY_MIN: Minimum energy to consider a sound significant.
- SOUND_COOLDOWN_S (s): Cooldown to avoid repeated turns from the same sound.

## Reactions (IMU / touch / sound)
- REACTIONS_INTERVAL (s): Interval between reaction checks.
- REACTIONS_LIFT_THRESHOLD: IMU accel (x) > this → treat as lifted.
- REACTIONS_PLACE_THRESHOLD: IMU accel (x) < this → treat as placed down.
- REACTIONS_FLIP_ROLL_THRESHOLD: |roll| > this → treat as flipped.
- TOUCH_DEBOUNCE_S (s): Debounce for touch inputs.
- REACTION_COOLDOWN_S (s): Cooldown between reaction-triggered actions.

Tuning tips: Increase thresholds to reduce false triggers on bumpy surfaces.

## Energy system
- ENERGY_DECAY_RATE: Per-tick energy decay during activity.
- ENERGY_INTERACTION_BOOST: Energy gain on user interaction.
- ENERGY_REST_RECOVERY: Energy recovery rate in idle.
- ENERGY_LOW_THRESHOLD|HIGH_THRESHOLD: Boundaries for mood/behavior changes.

## Battery
- LOW_BATTERY_THRESHOLD (%): Warn and reduce activity below this level.
- CRITICAL_BATTERY_THRESHOLD (%): Trigger safe/low-power mode.
- LOW_BATTERY_REDUCE_SPEED_FACTOR (0..1): Scale motion speeds when low.
- CRITICAL_BATTERY_REST_BEHAVIOR (bool): Prefer rest behavior when critical.
- CHARGING_DETECT_MIN_DELTA_V (V): Minimum voltage delta to detect charging.

## Guard Mode
- GUARD_DETECT_MM (mm): Forward distance to trigger alert/bark/scan.
- GUARD_SCAN_YAW_MAX_DEG / GUARD_SCAN_STEP_DEG / GUARD_SCAN_SETTLE_S / GUARD_BETWEEN_READS_S: Head scan parameters.
- GUARD_BASELINE_EMA: EMA smoothing for per-angle baselines.
- GUARD_DEVIATION_MM / GUARD_DEVIATION_PCT: Approaching detection thresholds vs baseline.
- GUARD_CONFIRM_WINDOW / GUARD_CONFIRM_THRESHOLD: N-of-M confirmation window/threshold.
- GUARD_ALERT_COOLDOWN_S: Minimum time between alerts.

## Patrol (Smart Patrol)
- PATROL_SCAN_YAW_MAX_DEG / PATROL_SCAN_STEP_DEG / PATROL_SCAN_SETTLE_S / PATROL_BETWEEN_READS_S: Fast head scans during patrol.
- PATROL_BASELINE_EMA: EMA smoothing for per-angle baselines.
- PATROL_APPROACH_DEVIATION_MM / PATROL_APPROACH_DEVIATION_PCT: Forward approaching thresholds vs baseline.
- PATROL_CONFIRM_WINDOW / PATROL_CONFIRM_THRESHOLD: N-of-M confirmation for approach.
- PATROL_ALERT_COOLDOWN_S: Cooldown between reactive maneuvers.
- PATROL_TURN_STEPS_ON_ALERT: Small in-place turn steps when approach confirmed.

## Voice
- WAKE_WORD: Voice wake keyword (engine-dependent).
- VOICE_VOLUME_DEFAULT|EXCITED|QUIET: Output volume profiles (if supported).
- VOICE_TTS_RATE|VOICE_TTS_PITCH: Text-to-speech voice parameters.

## Logging
- LOG_MAX_ENTRIES: Max log entries retained in memory.
- LOG_STATUS_INTERVAL (s): Interval for periodic status logs.
- LOG_LEVEL: Overall logging level (INFO/DEBUG/etc.).
- LOG_FILE_MAX_MB|LOG_FILE_BACKUPS: JSON log rotation settings.

## Control & UI
- INTERRUPT_KEY: Keyboard key to interrupt/exit control loops.
- INTERRUPT_LONG_PRESS_S: Long-press duration for safety/exit actions.
- UI_STATUS_OVERLAY: Enable simple status overlay/LED hints.

## Behavior selection (Control script)
- AVAILABLE_BEHAVIORS: Beginner-friendly names resolved by the orchestrator.

## Movement / kinematics tuning
- WALK_GAIT: Placeholder for future gait profiles.
- TURN_BIAS_DEGREES: Compensate consistent over/under turning.
- STEP_PAUSE_S: Micro pause between steps for smoothness.
- SPEED_RAMP_UP_MS|DOWN_MS: Accel/decel easing for servos.

## Obstacle avoidance details
- OBSTACLE_HYSTERESIS_CM: Reduce oscillation near thresholds.
- OBSTACLE_SIDE_BIAS: Prefer left/right when both sides are similar.
- BACKUP_DISTANCE_SCALE: Scale BACKUP_STEPS during emergency retreat.

## Sensors / filtering
- IMU_LPF_ALPHA: Low-pass filter for IMU noise reduction.
- ULTRASONIC_MIN_CM|MAX_CM: Hard limits for valid readings.
- ULTRASONIC_OUTLIER_REJECT_Z: Sigma-based outlier rejection.

## Behavior orchestration
- BEHAVIOR_SELECTION_MODE: "sequential" or "weighted" selection.
- BEHAVIOR_WEIGHTS: Weights used when mode is weighted.
- BEHAVIOR_MIN_DWELL_S: Minimum time to stay in a behavior.

## Safety
- EMERGENCY_STOP_POSE: Pose to assume on emergency stop.
- SAFETY_MAX_TILT_DEG|ROLL_DEG: Tip angle limits for safety reactions.

## How behaviors use config
- SmartPatrolBehavior: OBSTACLE_* thresholds, HEAD_SCAN_* values, speeds/steps, OBSTACLE_SCAN_INTERVAL.
- ReactionsBehavior: REACTIONS_* thresholds/timing, SOUND_BODY_TURN_THRESHOLD, HEAD_SCAN_SPEED, SPEED_*.
- GuardBehavior: GUARD_DETECT_MM, SPEED_SLOW, SPEED_TURN_*; respects ENABLE_EMOTIONAL_SYSTEM.

## Presets
- Edit `canine_core/config/canine_config.py` to change defaults or extend presets (Simple, Patrol, Interactive).
- simple: Conservative movement and fewer systems enabled.
- patrol: Emotions + learning enabled; patrol-focused behavior list.
- interactive: Voice + emotions enabled; reactive/guard behaviors available.

If you’re unsure, start with the preset closest to your usage and tweak only a couple of values (e.g., GUARD_DETECT_MM, OBSTACLE_SAFE_DISTANCE) before adjusting speeds.

## Running with a preset

Launch the interactive controller and pick a preset:

```powershell
python canine_core/control.py
```

Presets determine which behaviors are in rotation (`AVAILABLE_BEHAVIORS`) as well as default timing windows.
