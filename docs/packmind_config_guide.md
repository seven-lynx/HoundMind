# PackMind Configuration Guide
> Author: 7Lynx · Doc Version: 2025.10.30

This is the canonical configuration guide for PackMind. All references should point here (`docs/packmind_config_guide.md`).

PackMind is the standalone AI runtime in HoundMind with its own orchestrator, services, and optional mapping/navigation. This guide explains the options in `packmind/packmind_config.py`, how they affect behavior, and how to use presets. For a side-by-side comparison with CanineCore modules, see [`docs/CANINE_CORE_PACKMIND_FEATURE_MATRIX.md`](CANINE_CORE_PACKMIND_FEATURE_MATRIX.md).

## Presets
PackMind ships with multiple presets declared in `packmind/packmind_config.py`.

- default (PiDogConfig): Balanced feature set for general use
- simple (SimpleConfig): Minimal features; conservative movement; no SLAM/nav
- advanced (AdvancedConfig): All features; faster exploration; tighter obstacle thresholds
- indoor (IndoorPetConfig): Home‑friendly; quieter volumes; safe distances; learning enabled
- explorer (ExplorerConfig): Mapping/navigation focus; higher SLAM cadence; moderate speeds

Switching presets:
- Edit the default: set `DEFAULT_CONFIG` at the bottom of `packmind_config.py`
- At runtime (if voice enabled): "PiDog, simple mode" | "PiDog, advanced mode" | "PiDog, indoor mode" | "PiDog, explorer mode"

## Feature toggles
## Advanced Mapping Parameters

PackMind's mapping system exposes advanced options for fine-tuning the occupancy grid, dynamic obstacle fading, and detection of openings and safe paths. These are set in `packmind/packmind_config.py` and used by the mapping system automatically.

- **MAPPING_CONFIDENCE_THRESHOLD**: Occupancy grid confidence threshold (0.0–1.0). Above = OBSTACLE, below = FREE. Default: 0.7
- **MAPPING_MAX_OBSTACLE_AGE**: Seconds before an obstacle cell starts to fade if not observed. Default: 300.0
- **MAPPING_FADE_TIME**: Time in seconds after which to start fading dynamic obstacles. Default: 300.0
- **MAPPING_FADE_RATE**: Amount to decay confidence per fade step. Default: 0.05
- **MAPPING_OPENING_MIN_WIDTH_CM**: Minimum width (cm) for an opening to be detected. Default: 60.0
- **MAPPING_OPENING_MAX_WIDTH_CM**: Maximum width (cm) for an opening. Default: 120.0
- **MAPPING_OPENING_CELL_CONF_MIN**: Minimum confidence for a cell to be considered part of an opening. Default: 0.6
- **MAPPING_SAFEPATH_MIN_WIDTH_CM**: Minimum width (cm) for a safe path (corridor). Default: 40.0
- **MAPPING_SAFEPATH_MAX_WIDTH_CM**: Maximum width (cm) for a safe path. Default: 200.0
- **MAPPING_SAFEPATH_MIN_LENGTH_CELLS**: Minimum length (cells) for a safe path. Default: 6
- **MAPPING_SAFEPATH_CELL_CONF_MIN**: Minimum confidence for a cell to be considered part of a safe path. Default: 0.5

These parameters allow you to:
- Make the map more or less sensitive to new obstacles and free space
- Control how quickly transient obstacles (like people or pets) fade from the map
- Tune what counts as a doorway/opening or a navigable corridor for your environment

**Usage:**
Edit these values in your config or preset class in `packmind/packmind_config.py`. They will be picked up automatically by the mapping system when you create a `HomeMap` with your config.
- ENABLE_VOICE_COMMANDS: Voice recognition with wake word (requires `speech_recognition` + `pyaudio`)
- ENABLE_SLAM_MAPPING: Enable SLAM/house mapping (requires `numpy`)
- ENABLE_SENSOR_FUSION: Enable fused localization (depends on SLAM)
- ENABLE_INTELLIGENT_SCANNING: 3‑way obstacle scanning while moving
- ENABLE_EMOTIONAL_SYSTEM: LED emotions and behavior effects
- ENABLE_LEARNING_SYSTEM: Touch preference/interaction learning
- ENABLE_PATROL_LOGGING: Detailed patrol/activity logs
- ENABLE_AUTONOMOUS_NAVIGATION: Pathfinding and exploration (depends on SLAM)

## Obstacle avoidance
- OBSTACLE_IMMEDIATE_THREAT (cm): Immediate stop/avoid threshold (forward)
- OBSTACLE_APPROACHING_THREAT (cm): Pre‑avoid threshold (slow down/prepare)
- OBSTACLE_EMERGENCY_STOP (cm): Emergency halt safety margin
- OBSTACLE_SAFE_DISTANCE (cm): Distance considered "clear" for planning
- OBSTACLE_SCAN_INTERVAL (s): Time between scans while moving

## Movement parameters
- TURN_STEPS_SMALL | TURN_STEPS_NORMAL | TURN_STEPS_LARGE: Discrete turn step counts
- WALK_STEPS_SHORT | WALK_STEPS_NORMAL | WALK_STEPS_LONG: Forward step counts
- BACKUP_STEPS: Steps when retreating
- SPEED_SLOW | SPEED_NORMAL | SPEED_FAST | SPEED_EMERGENCY: Motion speeds (0‑255)
- SPEED_TURN_SLOW | SPEED_TURN_NORMAL | SPEED_TURN_FAST: Turn speeds (should be ≥ walk speeds)
- TURN_DEGREES_PER_STEP | TURN_45_DEGREES | TURN_90_DEGREES | TURN_180_DEGREES: Turn calibration aids

## Orientation (IMU yaw)
- ENABLE_ORIENTATION_SERVICE (bool): Enable IMU-based heading integration (gyro Z → heading degrees).
- ORIENTATION_GYRO_SCALE: Scale factor converting gyro Z units to deg/s.
- ORIENTATION_BIAS_Z: Bias to subtract from gyro Z (drift compensation).
- ORIENTATION_TURN_TOLERANCE_DEG: Allowed error when turning by angle.
- ORIENTATION_MAX_TURN_TIME_S: Safety timeout for turn-by-angle loops.

Notes:
- When enabled, the orchestrator updates an internal `current_heading` each sensor tick.
- Obstacle avoidance can use precise IMU-based turning instead of fixed steps.
- If disabled or heading unavailable, the system falls back to step-based turns using `TURN_DEGREES_PER_STEP`.
- Real-world turning can vary with speed and surface; the IMU closed-loop approach compensates for this automatically. Only the fallback step path depends on `TURN_DEGREES_PER_STEP` calibration.

## Calibration (when SLAM is enabled)
- Runtime calibration is handled by `CalibrationService` and invoked by the orchestrator.
- Voice commands: "PiDog, calibrate" (wall-follow) and "PiDog, find corner" (corner-seek).
- Programmatic use:

```python
from packmind.services.calibration_service import CalibrationService

cal = CalibrationService(slam_system=home_map, scanning_service=scanner, dog=pidog, logger=logger)
ok = cal.calibrate("wall_follow")  # or "corner_seek", "landmark_align"
```

Notes:
- There is no separate feature toggle for calibration; the orchestrator delegates to the service when SLAM is enabled and dependencies are available.

## Turn calibration tool
- Run `python tools/turn_calibration.py` on the PiDog to auto-calibrate turning.
- The tool measures degrees-per-step at your configured speeds and updates:
	- PackMind: `TURN_DEGREES_PER_STEP` and derived `TURN_45_DEGREES`/`TURN_90_DEGREES`/`TURN_180_DEGREES`
	- CanineCore: `TURN_DEGREES_PER_STEP` and `TURN_DPS_BY_SPEED`

## Localization and recovery (sensor fusion)
When SLAM and sensor fusion are enabled, PackMind maintains a probabilistic pose estimate (particle filter) and monitors confidence. If confidence dips, it can actively recover by sweeping the ultrasonic sensor and re-weighting the filter.

Settings in `packmind_config.py`:
- `LOCALIZATION_ACTIVE_RECOVERY` (bool): Enable automatic recovery sweeps on low confidence.
- `LOCALIZATION_CONFIDENCE_LOW` (0..1): Confidence threshold to trigger recovery (default 0.35).
- `LOCALIZATION_RECOVERY_MIN_INTERVAL_S` (s): Minimum time between recovery attempts.
- `LOCALIZATION_RECOVERY_SWEEPS`: How many sweep passes per attempt.
- `LOCALIZATION_RECOVERY_SWEEP_LEFT` / `LOCALIZATION_RECOVERY_SWEEP_RIGHT` (deg): Sweep bounds.
- `LOCALIZATION_RECOVERY_STEP_DEG` (deg): Sweep step size.

Behavior:
- During the main loop, if confidence is below the threshold and the minimum interval has elapsed, the orchestrator performs a short head sweep and feeds the bearing‑tagged distances back into the localizer.
- This helps the filter converge again without user input and slightly increases near‑term scan density.

## Behavior timing
- PATROL_DURATION_MIN | PATROL_DURATION_MAX (s): Patrol dwell suggestion
- REST_DURATION (s): Rest window when tired
- INTERACTION_TIMEOUT (s): Interaction UI timeout
- VOICE_COMMAND_TIMEOUT (s): Time window from wake word to command

## Voice
- WAKE_WORD: Wake word string (default "pidog")
- VOICE_VOLUME_DEFAULT | VOICE_VOLUME_EXCITED | VOICE_VOLUME_QUIET (0‑100): Speaking volumes

Voice runtime (ASR) settings used by `runtime/voice_runtime.py`:
- VOICE_WAKE_TIMEOUT_S (s): Listen timeout for capture
- VOICE_VAD_SENSITIVITY (0..1): Voice activity detection sensitivity
- VOICE_MIC_INDEX: Input device index (None/system default if not set)
- VOICE_LANGUAGE: Recognition language (e.g., en‑US)
- VOICE_NOISE_SUPPRESSION (bool): Ambient calibration and denoising

## Energy system
- ENERGY_DECAY_RATE: Per‑tick decay during activity
- ENERGY_INTERACTION_BOOST: Increment on user interaction/sound
- ENERGY_REST_RECOVERY: Recovery rate while resting
- ENERGY_LOW_THRESHOLD | ENERGY_HIGH_THRESHOLD: Thresholds for speed/mood bands

## Scanning
- HEAD_SCAN_RANGE (deg): Head sweep left/right range
- HEAD_SCAN_SPEED: Head movement speed during scans
- SCAN_SAMPLES: Readings per scan position (used for smoothing/robustness)
- SCAN_DEBOUNCE_S (s): Debounce for repeated readings
- SCAN_SMOOTHING_ALPHA (0..1): EMA smoothing of ultrasonic distances
- SCAN_INTERVAL_MIN | SCAN_INTERVAL_MAX (s): Bounds for dynamic scan cadence
- SCAN_DYNAMIC_AGGRESSIVENESS (0..1): How aggressively to adjust scan rate
- SENSOR_MONITOR_RATE_HZ: Sensor polling rate
- SENSOR_MONITOR_BACKOFF_ON_ERROR_S: Backoff sleep after sensor errors

## Sound response
- SOUND_HEAD_SENSITIVITY: Converts sound direction to head yaw responsiveness
- SOUND_BODY_TURN_THRESHOLD (deg): Add body turn when yaw exceeds threshold
- SOUND_RESPONSE_ENERGY_MIN: Minimum energy required to turn body toward sound

## Stuck detection
- STUCK_TIME_WINDOW (s): Movement history window for stuck detection
- STUCK_MOVEMENT_THRESHOLD: IMU magnitude threshold for "moving"
- STUCK_AVOIDANCE_LIMIT: Consecutive low‑movement checks before advanced escape

## Face recognition
- ENABLE_FACE_RECOGNITION (bool): Enable detection/recognition and person adaptation
- FACE_RECOGNITION_THRESHOLD (0..1): Similarity threshold (lower=permissive)
- FACE_DETECTION_INTERVAL (s): Detection cadence
- FACE_MAX_FACES_PER_FRAME: Max faces per frame
- FACE_CAMERA_WIDTH | FACE_CAMERA_HEIGHT | FACE_CAMERA_FPS: Camera settings
- FACE_PERSONALITY_LEARNING_RATE (0..1): Adaptation speed per person
- FACE_INTERACTION_TIMEOUT (s): Interaction patience window
- FACE_MEMORY_RETENTION_DAYS (days): Memory horizon
- FACE_DATA_DIR: On‑disk storage for profiles/encodings/interactions
- FACE_AUTO_SAVE_INTERVAL (s): Autosave cadence
- FACE_CONFIDENCE_DISPLAY_MIN (0..1): Min confidence to display recognition feedback

Performance note (Raspberry Pi):
- On Pi 4/5, prebuilt ARM wheels for `dlib` (dependency of `face_recognition`) are often available via piwheels.
- On Pi 3B, compiling `dlib` is slow and can fail due to memory limits. Consider setting `ENABLE_FACE_RECOGNITION = False`, or use `requirements-lite.txt`.
- See `docs/face_recognition_setup.md` for setup, build prerequisites (e.g., `cmake`), and troubleshooting.

## Dynamic balance
- ENABLE_DYNAMIC_BALANCE (bool): Enable balance monitoring
- BALANCE_SAMPLE_RATE (Hz): IMU sampling rate
- BALANCE_CALIBRATION_TIME (s): Stationary calibration window
- BALANCE_HISTORY_SIZE (readings): In‑memory sample window
- BALANCE_STABILITY_WINDOW (readings): Rolling window for stability analysis
- BALANCE_SLIGHT_TILT_THRESHOLD | BALANCE_UNSTABLE_TILT_THRESHOLD | BALANCE_CRITICAL_TILT_THRESHOLD (deg): Tilt thresholds
- BALANCE_RAPID_MOTION_THRESHOLD (rad/s): Angular velocity threshold
- BALANCE_CORRECTION_COOLDOWN (s): Cooldown between corrections
- BALANCE_DATA_DIR: Storage for balance session data

## Enhanced audio processing
- ENABLE_ENHANCED_AUDIO (bool): Enable advanced audio pipeline
- AUDIO_SAMPLE_RATE (Hz) | AUDIO_CHANNELS | AUDIO_CHUNK_SIZE (samples): Audio input settings
- AUDIO_INPUT_DEVICE_INDEX: Specific input device (None=default)
- AUDIO_CALIBRATION_TIME (s): Background noise calibration duration
- AUDIO_HISTORY_SIZE (samples): Analysis history length
- AUDIO_SILENCE_THRESHOLD (RMS): Silence level
- AUDIO_LOUD_NOISE_THRESHOLD (RMS): Loud noise level
- AUDIO_VOICE_FREQ_MIN | AUDIO_VOICE_FREQ_MAX (Hz): Voice band
- AUDIO_VOICE_THRESHOLD (0..1): Voice energy ratio threshold
- AUDIO_DIRECTION_HISTORY_SIZE (readings): Direction buffer length
- AUDIO_DIRECTION_CHANGE_THRESHOLD (deg): Change threshold for events
- AUDIO_SOURCE_DIRECTION_TOLERANCE (deg): Grouping tolerance for same source
- AUDIO_SOURCE_TIMEOUT (s): Source expiration window
- AUDIO_EVENT_HISTORY_SIZE (events): Event history size
- AUDIO_DATA_DIR: Storage for audio session data

## Health and performance
- HEALTH_MONITOR_INTERVAL_S (s): Health sampling cadence
- HEALTH_LOAD_PER_CORE_WARN_MULTIPLIER: CPU load/core threshold for degraded mode
- HEALTH_TEMP_WARN_C (°C): CPU temp threshold for degraded mode
- HEALTH_MEM_USED_WARN_PCT (%): Memory usage threshold for degraded mode
- HEALTH_SCAN_INTERVAL_MULTIPLIER | HEALTH_SCAN_INTERVAL_ABS_DELTA: How much to slow scans when degraded
- HEALTH_ACTIONS: Planned actions when degraded (e.g., "throttle_scans")

## Safety / watchdog
- WATCHDOG_HEARTBEAT_INTERVAL_S (s): Heartbeat cadence
- WATCHDOG_TIMEOUT_S (s): Timeout before safety action
- WATCHDOG_ACTION: Action on timeout (e.g., `stop_and_crouch`, `power_down`)

## Logging / telemetry
- LOG_LEVEL: Overall log level (DEBUG/INFO/WARN/ERROR)
- LOG_FILE_MAX_MB | LOG_FILE_BACKUPS: JSON log rotation
- TELEMETRY_ENABLED (bool): Enable telemetry export
- TELEMETRY_SAMPLE_INTERVAL_S (s): Telemetry cadence
- TELEMETRY_ENDPOINT: Optional remote endpoint

## Learning / persistence
- LEARNING_STATE_PATH: Path to learning state file
- LEARNING_AUTOSAVE_INTERVAL_S (s): Autosave cadence
- LEARNING_DECAY: Long‑term decay factor

## Navigation (optional)
- NAV_REPLAN_INTERVAL_S (s): Replanning cadence
- NAV_GOAL_TOLERANCE_CM (cm): Goal acceptance radius
- NAV_OBSTACLE_INFLATION_CM (cm): Inflation radius for obstacles
- NAV_COST_TURN_WEIGHT | NAV_COST_FORWARD_WEIGHT: Motion cost weights

## Running PackMind
Launch PackMind with the default (or selected) config:

```powershell
python packmind/orchestrator.py
# or
python packmind.py
```

To validate config (optional):
```powershell
python packmind/packmind_config.py
```

IMU turn sanity check (optional):
```powershell
python tools/imu_turn_test.py
```
This rotates +90° then -90° using IMU closed‑loop and prints the final angular error for quick validation after calibration.

## Tips
- Start with a preset closest to your use case, then tune only what’s needed (e.g., OBSTACLE_SAFE_DISTANCE, SPEED_NORMAL).
- Increase SCAN_DEBOUNCE_S or SCAN_SMOOTHING_ALPHA in noisy environments.
- Tune VOICE_VAD_SENSITIVITY and VOICE_WAKE_TIMEOUT_S based on your mic and room.
- Reduce ENABLE_ENHANCED_AUDIO or SLAM features on low‑power setups.
