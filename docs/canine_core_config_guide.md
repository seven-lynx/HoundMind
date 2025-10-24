# CanineCore Configuration Guide
> Author: 7Lynx · Doc Version: 2025.10.24

This is the canonical configuration guide for CanineCore. All references should point here (`docs/canine_core_config_guide.md`).

This guide is part of HoundMind. CanineCore is the modular behaviors/services framework within the HoundMind project for PiDog.

This guide explains every option in `canine_core/config/canine_config.py` and how it affects behaviors. Use it with the interactive launcher `canine_core/control.py`. Presets live in the same file and can be selected in the controller.

## Feature toggles
- ENABLE_VOICE_COMMANDS: Enable voice pipeline (VoiceBehavior/VoiceService).
- ENABLE_SLAM_MAPPING: Reserve for future mapping features.
- ENABLE_SENSOR_FUSION: Reserve for fused sensor logic (IMU + distance + audio).
- ENABLE_INTELLIGENT_SCANNING: Allow adaptive scan strategies (future).
- ENABLE_EMOTIONAL_SYSTEM: Enable LED emotion themes and effects.
- ENABLE_LEARNING_SYSTEM: Enable long-term memory (obstacle maps, habits).
- ENABLE_AUTONOMOUS_NAVIGATION: Enable advanced navigation modes.
 - ENABLE_ENERGY_SYSTEM: Enable simple energy model (decay/recovery/boosts).
 - ENABLE_BALANCE_MONITOR: IMU-based stability assessment (requires IMU).
 - ENABLE_AUDIO_PROCESSING: Optional VAD/noise helpers (webrtcvad if available).
 - ENABLE_SCANNING_COORDINATOR: Head sweep helper that publishes scan events.
- ENABLE_SAFETY_SUPERVISOR: Tilt emergency detection and safe pose reactions.
- ENABLE_BATTERY_MONITOR: Low/critical events and telemetry.
- ENABLE_IMU_MONITOR: Access accelerometer/gyro and basic tilt checks.
- ENABLE_TELEMETRY: Periodic snapshots (battery, tilt, head orientation).
- ENABLE_DEFAULT_HOOKS: Default event-driven reactions (battery, tilt emergencies).
- ENABLE_SENSORS_FACADE: Sim-safe wrappers for ears (sound) and dual touch.
- ENABLE_BEHAVIOR_WATCHDOG: Enforce max dwell time and error caps per behavior.

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
- BEHAVIOR_MIN_DWELL_S (s): Minimum time a behavior will be kept active.
- WATCHDOG_MAX_BEHAVIOR_S (s): Cap a behavior run when watchdog is enabled.
- WATCHDOG_MAX_ERRORS: Consecutive errors allowed before early stop.

## Scanning
- HEAD_SCAN_RANGE (deg): Head sweep angle left/right during scans.
- HEAD_SCAN_SPEED: Speed of head movement during scans.
- SCAN_SAMPLES: Samples per scan position (future use).
- SCAN_WHILE_MOVING: Allow concurrent scan + motion (when safe).
- SCAN_DEBOUNCE_S (s): Debounce window to ignore jittery repeated readings.
- SCAN_SMOOTHING_ALPHA (0..1): EMA smoothing factor for ultrasonic distances.
 
Note: When `ENABLE_INTELLIGENT_SCANNING` is true, Smart Patrol narrows the head sweep when the forward baseline distance is comfortably above `OBSTACLE_SAFE_DISTANCE`, and widens it otherwise. This reduces scan time in clear corridors while retaining wider sweeps near obstacles.

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

Note: Reactions behavior reads these values directly. Defaults are conservative and simulation-safe.

Tuning tips: Increase thresholds to reduce false triggers on bumpy surfaces.

## Energy system
- ENERGY_DECAY_RATE: Per-tick energy decay during activity.
- ENERGY_INTERACTION_BOOST: Energy gain on user interaction.
- ENERGY_REST_RECOVERY: Energy recovery rate in idle.
- ENERGY_LOW_THRESHOLD|HIGH_THRESHOLD: Boundaries for mood/behavior changes.

## Learning system
- ENABLE_LEARNING_SYSTEM (bool): When true, CanineCore wires a lightweight LearningService into the behavior context as `ctx.learning`.
- What it does: Maintains simple JSON-backed counters for categories like interactions, commands, and obstacles.
- Persistence: Saved to `data/canine_core/learning.json` automatically at intervals and on shutdown.
- API (for behaviors):
	- `ctx.learning.record_interaction(key)` / `record_command(key)` / `record_obstacle(key)`
	- `ctx.learning.get_count(category, key)`
	- `ctx.learning.top_n(category, n=5)`

Notes: The service is sim-safe and writes locally when running on non-Pi hosts.

Example usage in built-in behaviors (when enabled):
- Reactions: records touch (`touch_head`, `touch_body`), IMU (`imu_lift`, `imu_place`, `imu_flip`), and sound-induced turns (`sound_turn_left/right`).
- Smart Patrol: records obstacle events (`retreat`, `approach_forward`) and issued movement commands (`turn_left/right`, `forward`).

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

## Open Space (Find Open Space)
- OPEN_SPACE_SCAN_YAW_MAX_DEG / OPEN_SPACE_SCAN_STEP_DEG / OPEN_SPACE_SCAN_SETTLE_S / OPEN_SPACE_BETWEEN_READS_S: Head scan parameters for detecting gaps.
- OPEN_SPACE_MIN_GAP_WIDTH_DEG: Minimum contiguous angular width to qualify as a navigable gap.
- OPEN_SPACE_MIN_SCORE_MM: Minimum per-angle distance (mm) for angles to count toward the gap.
- OPEN_SPACE_CONFIRM_WINDOW / OPEN_SPACE_CONFIRM_THRESHOLD: N-of-M confirmation across quick rescans.
- OPEN_SPACE_FORWARD_STEPS: Number of forward steps after turning toward the gap.
- OPEN_SPACE_TURN_SPEED: Turn speed override (falls back to SPEED_TURN_NORMAL).

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

Note: Weighted selection is implemented; when enabled, the orchestrator builds a weighted random permutation of `AVAILABLE_BEHAVIORS` each cycle using `BEHAVIOR_WEIGHTS` (defaults to 1.0 for unspecified behaviors).

## Safety
- EMERGENCY_STOP_POSE: Pose to assume on emergency stop.
- SAFETY_MAX_TILT_DEG|ROLL_DEG: Tip angle limits for safety reactions.

## Smoke behavior (HardwareSmoke)
- SMOKE_ALLOW_MOVE (bool): If true, run a minimal movement sequence.
- SMOKE_SPEED: Speed used for smoke movement checks.

## How behaviors use config
- SmartPatrolBehavior: OBSTACLE_* thresholds, HEAD_SCAN_* values, speeds/steps, OBSTACLE_SCAN_INTERVAL.
- ReactionsBehavior: REACTIONS_* thresholds/timing, SOUND_BODY_TURN_THRESHOLD, HEAD_SCAN_SPEED, SPEED_*.
- GuardBehavior: GUARD_DETECT_MM, SPEED_SLOW, SPEED_TURN_*; respects ENABLE_EMOTIONAL_SYSTEM.
- HardwareSmokeBehavior: uses SMOKE_* flags and reads sensors/IMU/battery/sensors_facade.

## Presets
- Edit `canine_core/config/canine_config.py` to change defaults or extend presets (Simple, Patrol, Interactive, Safety-First).
- simple: Conservative movement and fewer systems enabled.
- patrol: Emotions + learning enabled; patrol-focused behavior list.
- interactive: Voice + emotions enabled; reactive/guard behaviors available.
- safety-first: Safety, IMU, Battery, and hooks enabled; slower motion; no scan while moving; cautious thresholds.

If you’re unsure, start with the preset closest to your usage and tweak only a couple of values (e.g., GUARD_DETECT_MM, OBSTACLE_SAFE_DISTANCE) before adjusting speeds.

## Running with a preset

Launch the interactive controller and pick a preset:

```powershell
python canine_core/control.py
```

Presets determine which behaviors are in rotation (`AVAILABLE_BEHAVIORS`) as well as default timing windows.


