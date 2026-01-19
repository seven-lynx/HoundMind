# HoundMind Features Guide (Unified System)

Version: v2026.01.18 • Author: 7Lynx

This guide explains what each feature does, how to use it, and how to disable it. All features are configured in `config/settings.jsonc`.

**Note:** Simulation mode is no longer supported. PackMind and CanineCore are now unified into a single system.

> **Rule of thumb:** If a feature is misbehaving, set its module `enabled` to `false` and restart.

---

## 1) Core Runtime
**What it does:** Runs the main loop and coordinates all modules.

**How to use:** Start with `python -m houndmind_ai`.

**How to disable:** Not applicable (core runtime is always required).

---

## 2) HAL — Sensors & Motors
### Sensors (HAL)
**What it does:** Reads ultrasonic, touch, sound direction, and IMU data.

**Disable:** `modules.hal_sensors.enabled = false`

### Motors (HAL)
**What it does:** Controls servos and executes actions.

**Disable:** `modules.hal_motors.enabled = false`

---

## 3) Perception
**What it does:** Lightweight sensor fusion and obstacle signals.

**Disable:** `modules.perception.enabled = false`

---

## 4) Scanning
**What it does:** Moves head and performs scans for navigation.

**Disable:** `modules.scanning.enabled = false`

---

## 5) Navigation & Obstacle Avoidance
**What it does:** Makes decisions from scans and triggers safe actions.

**Disable:** `modules.navigation.enabled = false`

---

## 6) Mapping (Pi3-safe)
**What it does:** Analyzes scan openings and saves lightweight home-map snapshots.

**Disable:** `modules.mapping.enabled = false`

---

## 7) Behavior
**What it does:** Picks actions based on state and rules.

**Micro-idle behaviors (lifelike idle):** When enabled, the robot occasionally performs small idle actions (e.g., `"shake head"`, `"wag tail"`, `"stretch"`) to feel more lifelike. These are safe, optional actions that do not affect navigation or safety logic.

**Settings:**
- `settings.behavior.micro_idle_enabled` (default: true)
- `settings.behavior.micro_idle_actions` (list of action names from your action catalog)
- `settings.behavior.micro_idle_interval_s` (minimum seconds between micro-idle actions)
- `settings.behavior.micro_idle_chance` (probability per eligible interval)

**Habituation (suppress repeated stimuli):**
When enabled, habituation reduces jittery or annoying reactions to repeated identical stimuli (touch or sound). The runtime tracks recent stimuli counts and will temporarily ignore a stimulus type after it has occurred a configurable number of times. Habituation automatically recovers after a quiet period.

**Settings:**
- `settings.behavior.habituation_enabled` (default: false) — enable/disable habituation
- `settings.behavior.habituation_threshold` (default: 3) — number of repeated events to suppress
- `settings.behavior.habituation_recovery_s` (default: 30.0) — seconds without that stimulus to reset the count

**Disable:** `modules.behavior.enabled = false`

**Energy (internal state)**
The runtime can maintain a lightweight `energy_level` that persists in the runtime context, decays over time, and increases briefly in response to stimuli (touch, sound). This is an optional internal state used by autonomy selection (play/rest bias) and can be enabled for more lifelike energy/mood dynamics.

**Settings:**
- `settings.energy.enabled` (default: false) — enable/disable energy persistence
- `settings.energy.initial` — initial energy when not present in context
- `settings.energy.decay_per_tick` — amount to reduce energy each tick
- `settings.energy.boost_touch` / `settings.energy.boost_sound` — per-stimulus energy boosts

Enable with:

```jsonc
"settings": {
    "energy": { "enabled": true }
}
```

When disabled, `energy_level` is not updated by the behavior module.

---

## 8) Attention
**What it does:** Turns head toward sound direction.

**Disable:** `modules.attention.enabled = false`

---

## 9) Safety
**What it does:** Emergency stop and tilt protection.

**Default:** Disabled (opt-in for testing).

**Disable:** `modules.safety.enabled = false`

---

## 10) Watchdog
**What it does:** Detects stale sensors/scan data and triggers recovery.

**Default:** Enabled (low-impact defaults: no actions/restarts unless configured).

**Disable:** `modules.watchdog.enabled = false`

---

## 11) Service Watchdog
**What it does:** Restarts failed/stale modules with backoff and caps.

**Default:** Enabled.

**Disable:** `modules.service_watchdog.enabled = false`

---

## 12) Health Monitor
**What it does:** Monitors CPU/memory/temp and throttles scans if needed.

**Default:** Disabled; throttling actions are opt-in.

**Disable:** `modules.health.enabled = false`

---

## 13) Balance
**What it does:** IMU-based posture compensation.

**Default:** Disabled.

**Disable:** `modules.balance.enabled = false`

---

## 14) Event Logging
**What it does:** Writes event logs and summaries.

**Disable:** `modules.event_log.enabled = false`

---

## 15) LED Manager
**What it does:** Centralized LED priority handling.

**Disable:** `modules.led_manager.enabled = false`

---

## 16) Calibration
**What it does:** Runs servo calibration workflows.

**Disable:** `modules.calibration.enabled = false`

---

## 17) Vision (Pi3 legacy)
**What it does:** Uses Vilib for camera output and preview.

**Disable:** `modules.vision.enabled = false`

---

## 18) Voice (Pi3 legacy)
**What it does:** Voice subsystem wiring only (disabled by default).

**Disable:** `modules.voice.enabled = false`

---

## 19) Voice Assistant (Pi4)
**What it does:** Maps voice text/commands into PiDog actions via `behavior_override`.

**How it works:**
- Provide `voice_text` or `voice_command` in runtime context.
- The module maps phrases to actions using `settings.voice_assistant.command_map`.

**Enable:**
- `modules.voice.enabled = true`
- `settings.voice_assistant.enabled = true`

**HTTP endpoints (optional):**
- `settings.voice_assistant.http.enabled = true`
- `GET /say?text=sit`
- `GET /command?action=forward`

**CLI helper:**
```bash
python tools/voice_cli.py say --text "sit"
python tools/voice_cli.py command --action "forward"
```

**Disable:**
- `modules.voice.enabled = false` or `settings.voice_assistant.enabled = false`

---

## 20) Face Recognition (Pi4)
**What it does:** Detects faces and optionally recognizes identities. Supports lite (OpenCV) and heavy (face_recognition) backends.

**Enable:**
- `modules.face_recognition.enabled = true`
- `settings.face_recognition.backend = "opencv"` or `"face_recognition"`

**HTTP endpoints (optional):**
- `settings.face_recognition.http.enabled = true`
- `GET /enroll?name=Alice`
- `POST /enroll {"name":"Alice"}`

**Disable:** `modules.face_recognition.enabled = false`

---

## 21) Pi4 Vision Feed (Pi4)
**What it does:** Captures frames and publishes `vision_frame` for other modules. Optional MJPEG stream.

**Enable:**
- `modules.vision_pi4.enabled = true`
- `settings.vision_pi4.backend = "picamera2"` (or `"opencv"` fallback)

**HTTP stream (optional):**
- `settings.vision_pi4.http.enabled = true`
- Stream URL: `http://<pi-ip>:8090/stream`

**Camera check tool:**
```bash
python tools/camera_check.py --list-devices --max-index 5
python tools/camera_check.py --index 0 --save frame.jpg
```

**Disable:** `modules.vision_pi4.enabled = false`


## 21a) Vision Inference Scheduler (Pi4)
**What it does:** Runs vision model inference in a background thread for Pi4/5 hardware. Accepts preprocessed frames, schedules inference, and returns results asynchronously for downstream modules.

**Enable:**
- Enabled automatically when `modules.vision_pi4.enabled = true` and `settings.vision_pi4.inference_scheduler_enabled = true` (default: true).

**Configuration:**
- `settings.vision_pi4.inference_scheduler_enabled`: Enable/disable scheduler (default: true)
- `settings.vision_pi4.preprocessing`: Preprocessing config (see below)

**Disable:** Set `settings.vision_pi4.inference_scheduler_enabled = false`

**Notes:**
- Results are published to `vision_inference_result` in context.
- Replace the dummy inference function with your own model for custom tasks.

## 21b) Vision Preprocessing (Pi4)
**What it does:** Preprocesses camera frames before inference (resize, normalize, ROI selection). Hardware-friendly and configurable for Pi4/5 vision tasks.

**Enable:**
- Enabled automatically when `modules.vision_pi4.enabled = true`.

**Configuration:**
- `settings.vision_pi4.preprocessing.resize`: Target size, e.g. `[224, 224]`
- `settings.vision_pi4.preprocessing.normalize`: Enable normalization (default: true)
- `settings.vision_pi4.preprocessing.roi`: Region of interest, e.g. `[x, y, w, h]`
- `settings.vision_pi4.preprocessing.mean`: Mean for normalization (default: `[0.485, 0.456, 0.406]`)
- `settings.vision_pi4.preprocessing.std`: Std for normalization (default: `[0.229, 0.224, 0.225]`)

**Disable:** Not recommended; preprocessing is lightweight and safe for all Pi4/5 vision tasks.

## 22) Semantic Labeler (Pi4)
**What it does:** Adds object labels from camera frames (lite stub or OpenCV DNN).

**Enable:**
- `modules.semantic_labeler.enabled = true`
- `settings.semantic_labeler.backend = "opencv_dnn"` (or `"stub"`)

**Basic model (recommended first):**
Run the downloader once to fetch a lightweight MobileNet-SSD model and labels:

```bash
python tools/download_opencv_models.py
```

This populates `models/` with:
- `ssd_mobilenet_v3_large_coco_2020_01_14.pb`
- `ssd_mobilenet_v3_large_coco_2020_01_14.pbtxt`
- `coco_labels.txt`

**Disable:** `modules.semantic_labeler.enabled = false`

---

## 23) SLAM (Pi4)
**What it does:** Provides real-time pose and mapping outputs for robust navigation. Supports RTAB-Map (visual/IMU SLAM) as the recommended backend for Pi4/5, with fallback to a safe stub if not available.

**Enable:**
- `modules.slam_pi4.enabled = true`
- `settings.slam_pi4.backend = "rtabmap"` (recommended for Pi4/5)
- See `scripts/install_rtabmap_pi4.md` for RTAB-Map install steps.

**Configuration:**
- `settings.slam_pi4.rtabmap`: RTAB-Map options (database path, frame size, RGB-D, parameters)
- `settings.slam_pi4.interval_s`: SLAM update interval

**Navigation integration (optional):**
- `settings.slam_pi4.nav_hint_enabled = true`
- `settings.slam_pi4.nav_target_heading_deg = 0`
- `settings.navigation.slam_nav_enabled = true`

**Disable:** `modules.slam_pi4.enabled = false`

**Notes:**
- RTAB-Map requires camera and IMU data; see the install guide for dependencies and troubleshooting.
- If RTAB-Map is not installed or fails, the module falls back to stub mode for safe operation.

## 24) Telemetry Dashboard (Pi4)
**What it does:** Serves a responsive web dashboard and JSON snapshot of the runtime context, including `performance_telemetry` (FPS, latency, CPU/GPU/RAM). The dashboard can optionally embed an MJPEG/HLS camera stream via a configurable `camera_path`.

**Enable:**
- `modules.telemetry_dashboard.enabled = true`
- `settings.telemetry_dashboard.enabled = true`
- `settings.telemetry_dashboard.http.enabled = true`

**Open:**
- Dashboard: `http://<pi-ip>:8092/`
- Snapshot JSON: `http://<pi-ip>:8092/snapshot`

**Camera preview / `camera_path`**
- Purpose: If you run a separate camera stream (MJPEG, HLS, or a web preview) you can point the dashboard to it so a live preview appears on the dashboard.
- Config key: `settings.telemetry_dashboard.camera_path`
- Example values:
    - Local MJPEG stream path on same host: `/stream` (dashboard will embed `http://<pi-ip>:<stream-port>/stream`)
    - Full URL to another host: `http://camera-host:8090/stream`

Example `config/settings.jsonc` snippet:
```jsonc
"modules": {
    "telemetry_dashboard": { "enabled": true }
},
"settings": {
    "telemetry_dashboard": {
        "enabled": true,
        "http": { "enabled": true, "port": 8092 },
        "camera_path": "http://<pi-ip>:8090/stream"
    }
}
```

**Embedding notes & security**
- The dashboard embeds the provided `camera_path` in an `<iframe>` or `<img>` depending on stream type. Ensure the camera stream allows same-origin embedding or configure a reverse proxy if needed.
- The telemetry dashboard has no built-in authentication. Recommended deployment patterns:
    - Run it bound to a LAN-only interface (or `127.0.0.1` behind an SSH tunnel) when used on untrusted networks.
    - Place a reverse proxy (nginx/Caddy) in front and enable TLS + HTTP auth if exposing to wider networks.
    - Use firewall rules to restrict access to known hosts.

**Disable:** `modules.telemetry_dashboard.enabled = false`


## 25) WiFi Localization (Pi4/5)
**What it does:** Scans for nearby WiFi access points, records signal strengths (RSSI), and provides fingerprint-based localization for indoor positioning. Useful for context-aware behaviors and navigation.

**Enable:**
- `modules.wifi_localization.enabled = true`
- (Optional) Adjust scan interval, ignore list, and fingerprint file in `settings.wifi_localization`:
	- `scan_interval`: Scan period in seconds (default: 10.0)
	- `ignore_ssids`: List of SSIDs to ignore
	- `fingerprint_file`: Path for persistent storage (default: `wifi_fingerprints.json`)
	- `max_fingerprint_file_size`: Max file size in bytes (default: 262144)

**Disable:** `modules.wifi_localization.enabled = false`

**Notes:**
- Disabled by default. Safe to enable on Pi4/5 with WiFi hardware.
- Fingerprints are updated when `current_location` is set in context.
- File size limit prevents SD card bloat; oldest entries are pruned automatically.

## 25) How to Disable Any Feature
1) Open `config/settings.jsonc`
2) Find the module under `modules`.
3) Set `enabled` to `false`.
4) Restart HoundMind.

## Profiles
Use `profile: "pi3" | "pi4"` in `config/settings.jsonc`, or set `HOUNDMIND_PROFILE=pi4`.

---

## 25) Troubleshooting
- If `pidog` import fails: install SunFounder PiDog first, then HoundMind.
- If a module fails: disable it in `modules` and restart.
- For camera issues: switch `settings.vision_pi4.backend` to `opencv`.

---

## 22) Path Planning (A* for Pi4)
**What it does:**
- Plans a path from the current cell to a specified goal using the A* algorithm on a grid map.
- The planned path is available in the runtime context for navigation and debugging.

**Enable:**
- Set `"path_planning_enabled": true` in the `mapping` section of your config.
- Set a goal with `"goal": [x, y]` in the same section.

**Usage:**
- The mapping module will call the path planning hook each tick if enabled.
- The planned path will be available in the context as `path_planning`.
 
Note: When `mapping.path_planning_enabled` is set, the runtime will automatically
register the default A* hook into the context as `path_planning_hook`, so no
further wiring is required for the basic grid-based planner.

**Example:**
```python
from houndmind_ai.mapping.path_planner import astar

grid = [
    [0, 0, 0, 1, 0],
    [1, 1, 0, 1, 0],
    [0, 0, 0, 0, 0],
    [0, 1, 1, 1, 0],
    [0, 0, 0, 0, 0],
]
start = (0, 0)
goal = (4, 4)
path = astar(grid, start, goal)
print("Path:", path)
# Output: [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (3, 2), (4, 2), (4, 3), (4, 4)]
```

**Disable:**
- Set `"path_planning_enabled": false` in the mapping config.

---
