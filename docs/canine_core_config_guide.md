# CanineCore Configuration Guide

This guide explains every option in `canine_core/config/pidog_config.py` and how it affects behaviors.

## Feature toggles
- ENABLE_VOICE_COMMANDS: Enable voice pipeline (VoiceBehavior/VoiceService).
- ENABLE_SLAM_MAPPING: Reserve for future mapping features.
- ENABLE_SENSOR_FUSION: Reserve for fused sensor logic (IMU + distance + audio).
- ENABLE_INTELLIGENT_SCANNING: Allow adaptive scan strategies (future).
- ENABLE_EMOTIONAL_SYSTEM: Enable LED emotion themes and effects.
- ENABLE_LEARNING_SYSTEM: Enable long-term memory (obstacle maps, habits).
- ENABLE_AUTONOMOUS_NAVIGATION: Enable advanced navigation modes.

## Obstacle avoidance
- OBSTACLE_IMMEDIATE_THREAT (mm): Very close; behavior should react urgently.
- OBSTACLE_APPROACHING_THREAT (mm): Close side obstacles; bias turns away.
- OBSTACLE_EMERGENCY_STOP (mm): Emergency retreat threshold straight ahead.
- OBSTACLE_SAFE_DISTANCE (mm): If forward < this, steer to freer side.
- OBSTACLE_SCAN_INTERVAL (s): Time between patrol scan cycles.

Recommended ranges: 15–80 mm depending on environment; start with defaults.

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

## Sound response
- SOUND_HEAD_SENSITIVITY: Head responsiveness to sound (future use).
- SOUND_BODY_TURN_THRESHOLD (deg): Angle to trigger body turn toward sound.
- SOUND_RESPONSE_ENERGY_MIN: Minimum energy to consider a sound significant.

## Reactions (IMU / touch / sound)
- REACTIONS_INTERVAL (s): Interval between reaction checks.
- REACTIONS_LIFT_THRESHOLD: IMU accel (x) > this → treat as lifted.
- REACTIONS_PLACE_THRESHOLD: IMU accel (x) < this → treat as placed down.
- REACTIONS_FLIP_ROLL_THRESHOLD: |roll| > this → treat as flipped.

Tuning tips: Increase thresholds to reduce false triggers on bumpy surfaces.

## Energy system
- ENERGY_DECAY_RATE: Per-tick energy decay during activity.
- ENERGY_INTERACTION_BOOST: Energy gain on user interaction.
- ENERGY_REST_RECOVERY: Energy recovery rate in idle.
- ENERGY_LOW_THRESHOLD|HIGH_THRESHOLD: Boundaries for mood/behavior changes.

## Battery
- LOW_BATTERY_THRESHOLD (%): Warn and reduce activity below this level.
- CRITICAL_BATTERY_THRESHOLD (%): Trigger safe/low-power mode.

## Guard Mode
- GUARD_DETECT_MM (mm): Forward distance to trigger alert/bark/scan.

## Voice
- WAKE_WORD: Voice wake keyword (engine-dependent).
- VOICE_VOLUME_DEFAULT|EXCITED|QUIET: Output volume profiles (if supported).

## Logging
- LOG_MAX_ENTRIES: Max log entries retained in memory.
- LOG_STATUS_INTERVAL (s): Interval for periodic status logs.

## Control & UI
- INTERRUPT_KEY: Keyboard key to interrupt/exit control loops.

## Behavior selection (Control script)
- AVAILABLE_BEHAVIORS: Beginner-friendly names resolved by the orchestrator.

## How behaviors use config
- SmartPatrolBehavior: OBSTACLE_* thresholds, HEAD_SCAN_* values, speeds/steps, OBSTACLE_SCAN_INTERVAL.
- ReactionsBehavior: REACTIONS_* thresholds/timing, SOUND_BODY_TURN_THRESHOLD, HEAD_SCAN_SPEED, SPEED_*.
- GuardBehavior: GUARD_DETECT_MM, SPEED_SLOW, SPEED_TURN_*; respects ENABLE_EMOTIONAL_SYSTEM.

## Overriding options
- Edit `pidog_config.py` to change defaults or extend presets (Simple, Patrol, Interactive).
- Optional YAML (`canine_core/config/canine_core.yaml`) can override the behavior queue and feature flags if PyYAML is installed.

## Presets
- simple: Conservative movement and fewer systems enabled.
- patrol: Emotions + learning enabled; patrol-focused behavior list.
- interactive: Voice + emotions enabled; reactive/guard behaviors available.

If you’re unsure, start with the preset closest to your usage and tweak only a couple of values (e.g., GUARD_DETECT_MM, OBSTACLE_SAFE_DISTANCE) before adjusting speeds.
