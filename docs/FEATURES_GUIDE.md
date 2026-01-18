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

**Disable:** `modules.behavior.enabled = false`

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

---

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
**What it does:** Provides pose/mapping outputs for robust navigation. Defaults to a safe stub until a backend is configured.

**Enable:**
- `modules.slam_pi4.enabled = true`
- `settings.slam_pi4.backend = "stub"` (or a future backend like `orbslam3`)

**Navigation integration (optional):**
- `settings.slam_pi4.nav_hint_enabled = true`
- `settings.slam_pi4.nav_target_heading_deg = 0`
- `settings.navigation.slam_nav_enabled = true`

**Disable:** `modules.slam_pi4.enabled = false`

---

## 24) Telemetry Dashboard (Pi4)
**What it does:** Serves a simple web dashboard and JSON snapshot of runtime context, including `performance_telemetry` (FPS, latency, CPU/GPU/RAM).

**Enable:**
- `modules.telemetry_dashboard.enabled = true`
- `settings.telemetry_dashboard.enabled = true`
- `settings.telemetry_dashboard.http.enabled = true`

**Open:**
- Dashboard: `http://<pi-ip>:8092/`
- Snapshot JSON: `http://<pi-ip>:8092/snapshot`

**Disable:** `modules.telemetry_dashboard.enabled = false`

---

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
