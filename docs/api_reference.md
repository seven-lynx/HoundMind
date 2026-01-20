# HoundMind & PiDog API Reference (Pi3)

Version: v2026.01.18 • Author: 7Lynx

> Beginner-friendly reference for HoundMind + the official SunFounder `pidog` library.

## Important: Two Layers
HoundMind is an **add-on** that runs on top of the official SunFounder PiDog software.

- **`pidog`** = SunFounder’s hardware control library (servos, sensors, LEDs, audio).
- **`houndmind_ai`** = HoundMind runtime and modules (behavior, mapping, safety, logging).

Install `pidog` first, then HoundMind in the **same Python environment**. Simulation mode is no longer supported. PackMind and CanineCore are now unified.

---

## Quick Start (Safe Pattern)
```python
from pidog import Pidog

dog = Pidog()
try:
	dog.do_action("stand", speed=50)
	dog.wait_all_done()
finally:
	dog.close()
```

Need feature-level explanations? See [docs/FEATURES_GUIDE.md](docs/FEATURES_GUIDE.md) and the [HoundMind Programming Guide](HOUNDMIND_PROGRAMMING_GUIDE.md).

---

## Core PiDog Class (Official `pidog` Library)

### Beginner-Friendly Commands
| Method | Description | Parameters |
|--------|-------------|------------|
| `do_action(action_name, step_count=1, speed=50)` | Run a preset action | `action_name`, `step_count`, `speed` |
| `wait_all_done()` | Wait until actions finish | — |
| `stop_and_lie()` | Safe stop + lie down | — |
| `body_stop()` | Emergency stop (immediate) | — |
| `close()` | Shutdown hardware safely | — |

### Head / Tail / Legs
| Method | Description |
|--------|-------------|
| `head_move(target_angles, roll_comp=0, pitch_comp=0, immediately=True, speed=50)` | Move head (yaw/roll/pitch) |
| `tail_move(target_angles, immediately=True, speed=50)` | Move tail |
| `legs_move(target_angles, immediately=True, speed=50)` | Move legs (advanced) |
| `wait_head_done()` / `wait_tail_done()` / `wait_legs_done()` | Wait for movement |

### Sensors
| Property / Method | Description |
|------------------|-------------|
| `ultrasonic.read_distance()` | Distance in cm |
| `ears.isdetected()` / `ears.read()` | Sound detected + direction |
| `dual_touch.read()` | Touch sensor status |
| `accData`, `gyroData` | IMU raw values |

### RGB LEDs
| Method | Description |
|--------|-------------|
| `rgb_strip.set_mode(style, color, bps=1.0, brightness=1.0)` | LED effects |
| `rgb_strip.close()` | Turn off LEDs |

---

## HoundMind Runtime (`houndmind_ai`) Modules
These modules run each tick and publish data into the runtime context.

- **SensorModule**: publishes `sensor_reading`, `sensors`, `sensor_history`, `sensor_health`.
- **ScanningModule**: publishes `scan_reading`, `scan_latest`, `scan_history`, `scan_quality`.
- **OrientationModule**: updates `current_heading`.
- **MappingModule**: publishes `mapping_openings`, `mapping_state`; optional home-map snapshots.
- **LocalPlannerModule**: publishes `local_plan`, `mapping_recommendation`.
- **ObstacleAvoidanceModule**: sets `navigation_action`, `navigation_turn`, `navigation_followup`, `navigation_decision`.
- **BehaviorModule**: sets `behavior_action` and handles overrides.
- **AttentionModule**: uses sound direction to orient head; emits `led_request:attention`.
- **SafetyModule**: sets `safety_action`, `safety_active`, `emergency_stop_active`, `tilt_warning`.
- **WatchdogModule**: sets `watchdog_action`, `behavior_override`, `restart_modules`.
- **HealthMonitorModule**: sets `health_status`, `health_degraded`, `scan_interval_override_s`.
- **BalanceModule**: IMU-based balance compensation via `dog.set_rpy`.
- **EventLoggerModule**: writes event logs and summary.
- **LedManagerModule**: centralizes RGB LEDs using `led_request:*` signals.

---

## Core Context Keys
- `sensor_reading` (SensorReading)
- `sensors` (dict) and `sensor_health` (dict)
- `scan_reading` (ScanReading), `scan_latest` (dict), `scan_quality` (dict)
- `current_heading` (float)
- `mapping_openings` (dict), `mapping_state` (dict)
- `navigation_action` (str), `navigation_turn` (dict), `navigation_decision` (dict)
- `behavior_action` (str)
- `led_request:safety` | `led_request:navigation` | `led_request:attention` | `led_request:emotion`
- `safety_action` (str), `safety_active` (bool)
- `watchdog_action` (str)
- `health_status` (dict), `health_degraded` (bool)

---

## Configuration Sections
- `modules`: module enable/disable
- `sensors`: polling and filtering
- `navigation`: scan and decision settings
- `mapping`: home map settings
- `behavior`: action catalog and selection
- `attention`: sound direction head turns
- `safety`: emergency stop and tilt
- `balance`: IMU compensation settings
- `watchdog`: timeouts and restarts
- `logging`: event logs and console/file logs
- `led`: LED manager priority and color settings
- `performance`: safe mode and runtime warnings
- `calibration`: servo offsets and calibration persistence

---

## SensorReading Fields
- `distance_cm`, `touch`, `sound_detected`, `sound_direction`
- `acc`, `gyro`, `timestamp`
- `distance_valid`, `touch_valid`, `sound_valid`, `imu_valid`

## ScanReading Fields
- `mode`: `sweep` or `three_way`
- `data`: angle map or left/right/forward
- `timestamp`

---

## HoundMind Mapping (Unified System)
HoundMind’s `MappingModule` provides lightweight opening analysis and optional home-map snapshots. Use the public MappingModule API rather than calling private methods. See the runnable demo `examples/houndmind_mapping_demo.py` for a complete example.

Illustrative snippet (do not rely on private `_`-prefixed helpers in production):

```python
from houndmind_ai.mapping.mapper import MappingModule

# Configure mapping settings in config/settings.jsonc; use MappingModule instance APIs
# rather than calling private implementation helpers. Refer to examples/houndmind_mapping_demo.py
# for a runnable demo.

```

Runnable demo: [examples/houndmind_mapping_demo.py](examples/houndmind_mapping_demo.py)

---

## Beginner Troubleshooting
-- **`ModuleNotFoundError: pidog`**: Install the official SunFounder PiDog software first, then install HoundMind in the same environment. Example:

```bash
git clone https://github.com/sunfounder/pidog.git
python -m pip install ./pidog
python -m pip install -e .
```
- **`ModuleNotFoundError: houndmind_ai`**: Ensure you installed HoundMind with `python -m pip install -e .` in the active environment.
- **I2C / sensor errors**: Verify I2C is enabled in Raspberry Pi OS and reboot.
- **Servo jitter**: Lower speed and reduce `step_count`, then try again.
-- **Audio not working**: The guided installer can run the PiDog `i2samp.sh` helper for you. Use the top-level wrapper `scripts/install_houndmind.sh` and pass `--run-i2samp`, set `RUN_I2SAMP=1` for non-interactive runs, or answer the interactive prompt when running the script. Otherwise run it manually from the cloned `pidog` repo:

```bash
sudo bash .cache/houndmind_deps/pidog/i2samp.sh
```

---

## Safety Defaults (Recommended Starting Values)
| Setting | Recommended | Notes |
|---------|-------------|-------|
| `speed` | 30–60 | Start low and increase gradually |
| `step_count` | 1–3 | Keep short while testing |
| `tick_hz` | 5–10 | Lower tick rate is safer for first runs |
| `scan_interval_s` | 0.6–1.5 | Slower scans reduce load |

---

## HoundMind Module Data Flow (High Level)
```
Sensors -> Perception -> Navigation -> Behavior -> Motors
	\-> Safety / Watchdog / Health -> overrides
	\-> Logging / LEDs -> status output
```

---

## Minimal HoundMind Runtime Example
```python
from houndmind_ai.core.config import load_config
from houndmind_ai.core.runtime import HoundMindRuntime
from houndmind_ai.main import build_modules

config = load_config()
runtime = HoundMindRuntime(config, build_modules(config))
runtime.run()
```

---

## Compatibility Note (Pi3 vs Pi4)
- **Pi3**: Supported target. Vision/voice are disabled by default.
-- **Pi4**: Pi3 is the primary target; Pi4 features are optional and disabled by default (enable via the `pi4` profile in `config/settings.jsonc`).

---

## Pi4 Vision Stream (HTTP)
If `vision_pi4.http.enabled` is true, the module serves a live MJPEG stream:

- `GET /stream` → MJPEG video stream

Example (browser):
http://<pi-ip>:8090/stream

---

## Face Recognition HTTP Endpoints
If `face_recognition.http.enabled` is true:

- `GET /status` → backend status
- `GET /faces` → last detections
- `GET /enroll?name=Alice` → enqueue enrollment
- `POST /enroll` with `{ "name": "Alice" }`
