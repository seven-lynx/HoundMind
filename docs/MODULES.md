# Module map — every module, what it reads and what it writes

Status: **reference** — describes the shipped module set and the context keys each one touches. If it
disagrees with `src/houndmind_ai/main.py::build_registry`, the file is wrong.
Pairs with: [`HOUNDMIND_PROGRAMMING_GUIDE.md`](HOUNDMIND_PROGRAMMING_GUIDE.md) (the module contract),
[`ARCHITECTURE.md`](ARCHITECTURE.md) (why the layers are split this way)

Every runtime component is a `Module` with `start`/`tick`/`stop`, and every one is registered by hand
in `main.build_registry` — a module missing from that list never runs, however correct it is. The
context is how they talk: a module reads keys it does not own and writes the ones it does.

**How to read the table.** *Reads* and *Writes* are the `context.get`/`context.set` keys in the
module's own file. A module writing a key another module also writes is a bug worth filing; a module
reading a key nobody writes is a feature that is silently off. *Shipped* is the shipped
`config/settings.jsonc`: **on** means a default start runs it, **off** means it is registered and
waiting for an operator. *Stream* is which plan owns the surface — a routing label for the work, not
a capability the module provides.

The loop itself owns `config`, `settings`, `module_names`, `trace_id`, `tick_ts`, `runtime_tick`, and
the per-module `module_statuses` / `module_tick_duration:<name>` / `module_heartbeat:<name>` family
(`core/runtime.py`); no module writes those.

| Module | Stream | Shipped | File | Reads | Writes |
|---|---|---|---|---|---|
| `hal` | HAL | on | `hal/module.py` | `pidog`, `settings` | `hal` |
| `hal_sensors` | HAL | on | `hal/sensors.py` | `hal`, `settings` | `sensor_reading`, `sensor_history`, `sensors`, `sensor_service`, `sensor_health`, `battery_voltage` |
| `motion_gateway` | ACT | on | `act/gateway.py` | `settings`, `runtime_mode`, `sensor_reading`, `battery_voltage`, `tilt_warning`, `behavior_action`, `navigation_action`, `safety_action`, `watchdog_action`, `behavior_state`, `autonomy_choice`, `navigation_decision`, `trace_id` | `motion_command`, `motion_verdict`, `motion_cancel`, `decision_record`, `intent_board`, `tilt_latched` |
| `hal_motors` | HAL | on | `hal/motors.py` | `settings`, `hal`, `motion_command`, `scan_in_flight`, `scan_reading`, `quiet_mode_active`, `attention_active_ts`, `current_heading`, `energy_speed_hint`, `emergency_stop_active`, `head_turn_follow_release_ts`, `navigation_followup`, `navigation_turn` | `head_turn_follow_release_ts`, `navigation_followup`, `navigation_turn` |
| `perception` | PERC | on | `perception/fusion.py` | `settings`, `sensor_reading`, `sensor_service`, `orientation`, `current_heading`, `faces` | `perception`, `pose_hint` |
| `scanning` | NAV | on | `navigation/scanning.py` | `settings`, `hal`, `motion_command`, `quiet_mode_active`, `scan_interval_override_s` | `scan_reading`, `scan_latest`, `scan_history`, `scan_duration_s`, `scan_quality`, `scan_in_flight`, `scan_service`, `scan_worker` |
| `orientation` | NAV | on | `navigation/orientation.py` | `settings`, `sensor_reading`, `sensor_service`, `orientation_bias_z` | `current_heading`, `orientation_bias_z`, `orientation_calibration_ok` |
| `odometry` | NAV | on | `navigation/odometry.py` | `settings`, `sensor_reading`, `current_heading`, `motion_command`, `odometry_reset`, `pose_reset` | `odometry`, `pose_reset` |
| `localization` | NAV | on | `navigation/localization.py` | `settings`, `odometry`, `slam_pose`, `slam_status`, `place_fix`, `module_heartbeat:slam_pi4` | `localization`, `localization_event`, `pose_trail` |
| `room_context` | MAP | on | `navigation/room_context.py` | `home_map`, `localization` | `current_room` |
| `calibration` | CAL | off | `calibration/workflow.py` | `settings`, `hal`, `calibration_request`, `sensors`, `scan_latest`, `pose_hint`, `localization_confidence` | `calibration_result`, `localization_confidence` |
| `mapping` | MAP | on | `mapping/mapper.py` | `settings`, `scan_latest`, `sensors`, `home_map`, `mapping_state` | `home_map`, `home_map_status`, `mapping_state`, `mapping_openings` |
| `navigation` | NAV | on | `navigation/obstacle_avoidance.py` | `settings`, `sensor_reading`, `scan_reading`, `scan_latest`, `scan_service`, `scan_duration_s`, `scan_stale_after_s`, `perception`, `mapping_state`, `mapping_openings`, `slam_nav_hint`, `intent_board` | `navigation_decision`, `navigation_followup`, `navigation_turn`, `mapping_hint`, `energy_speed_hint`, `led_request:navigation`, `stuck_recovery`, `gentle_recovery_active`, `gentle_recovery_until` |
| `behavior` | PET | on | `behavior/fsm.py` | `settings`, `intent_board`, `perception`, `battery_percent`, `battery_voltage`, `energy_level`, `quiet_mode_active`, `behavior_override` | `behavior_state`, `behavior_habituation`, `behavior_override`, `battery_low`, `energy_level`, `autonomy_choice` |
| `habituation` | PET | on | `behavior/habituation.py` | `settings`, `perception` | — |
| `attention` | PET | on | `behavior/attention.py` | `settings`, `hal`, `perception`, `scan_reading`, `scan_in_flight`, `habituation:sound:habituated` | `attention_active_ts`, `led_request:attention` |
| `routine_runner` | PET | on | `behavior/routine_runner.py` | `settings`, `intent_board`, `decision_record`, `routine_request`, `routine_reload`, `routine_stop` | `routine_run`, `routine_report`, `routine_store`, `routine_request`, `routine_reload`, `routine_stop` |
| `place_navigator` | NAV | on | `navigation/place_navigator.py` | `settings`, `intent_board`, `decision_record`, `motion_command`, `current_heading`, `place_request` | `place_goal`, `place_request`, `place_store` |
| `place_recognition` | PEOPLE | off | `navigation/place_recognition.py` | `settings`, `vision_frame`, `vision_frame_ts`, `place_store` | `place_fix`, `place_match`, `place_match_candidates`, `odometry_reset` |
| `route_follower` | NAV | off | `navigation/route_follower.py` | `settings`, `home_map`, `localization`, `mapping_state`, `place_match`, `intent_board`, `route_request` | `route`, `route_request` |

| `event_log` | PLAT | on | `logging/event_logger.py` | `settings`, `intent_board`, `module_statuses`, `motion_command`, `navigation_decision`, `odometry`, `scan_latest`, `mapping_hint`, `mapping_openings`, `stuck_recovery`, `health_degraded` | `event_log_report` |
| `decision_log` | PLAT | on | `logging/decision_log.py` | `settings`, `decision_record` | `decision_ring` |
| `led_manager` | PLAT | on | `logging/led_manager.py` | `settings`, `hal` | — |
| `health` | SAFE | off | `safety/health_monitor.py` | `settings`, `health_status_last_log_ts` | `health_status`, `health_high_water`, `health_degraded`, `health_status_last_log_ts`, `scan_interval_override_s`, `vision_frame_interval_override_s` |
| `sensor_health` | SAFE | off | `safety/sensor_health.py` | `settings`, `sensor_reading` | `led_request:health` |
| `watchdog` | SAFE | on | `safety/watchdog.py` | `settings`, `sensor_reading`, `scan_reading`, `scan_duration_s`, `module_statuses`, `intent_board` | `watchdog_status`, `watchdog_hold`, `restart_modules`, `scan_stale_after_s` |
| `balance` | SAFE | off | `safety/balance.py` | `settings`, `hal`, `sensors`, `sensor_reading`, `motion_command` | — |
| `safety` | SAFE | off | `safety/supervisor.py` | `settings`, `sensors`, `sensor_reading`, `sensor_service`, `intent_board` | `safety_active`, `emergency_stop_active`, `tilt_warning`, `led_request:safety` |
| `energy_emotion` | PET | off | `optional/energy_emotion.py` | `settings`, `perception`, `energy_level` | `emotion_state`, `energy_speed_hint`, `led_request:emotion` |
| `vision` | VIS | off | `optional/vision.py` | — | `vision_frame`, `vision_frame_ts`, `vision_status` |
| `vision_pi4` | VIS | off | `optional/vision_pi4.py` | `settings`, `vision_frame_interval_override_s` | `vision_frame`, `vision_frame_jpeg`, `vision_frame_ts`, `vision_status`, `vision_inference_status`, `vision_inference_result` |
| `assistant` | AUD | off | `optional/assistant.py` | `settings` | `assistant`, `assistant_reply`, `voice_question_handler` |
| `voice` | AUD | off | `optional/voice.py` | `settings`, `voice_command`, `voice_text`, `assistant_reply`, `voice_question_handler` | `voice`, `voice_command`, `voice_text`, `assistant_reply`, `behavior_override` |
| `face_recognition` | PEOPLE | off | `optional/face_recognition.py` | `settings`, `tick_ts`, `vision_frame`, `vision_frame_ts`, `vision_faces_raw`, `face_recognition_command` | `faces`, `face_recognition_status`, `face_recognition_command`, `identity_admin`, `identity_roster` |
| `semantic_labeler` | PEOPLE | off | `optional/semantic_labeler.py` | `settings`, `tick_ts`, `vision_frame`, `vision_objects_raw` | `semantic_labels`, `semantic_status` |
| `slam_pi4` | SLAM | off | `optional/slam_pi4.py` | `settings`, `sensor_reading`, `vision_frame`, `vision_frame_ts` | `slam_pose`, `slam_status`, `slam_stats`, `slam_map_data`, `slam_trajectory`, `slam_nav_hint` |
| `api` | API | on | `services/module.py` | `settings`, `command_bus`, `restart_modules` | `api_alive`, `restart_modules` |

## Reading the map

- **The motion path is four rows.** `motion_gateway` decides and writes `motion_command`;
  `hal_motors` is the only module that executes it. A producer of motion publishes a typed intent to
  `intent_board` (`kernel/intents.py`) and never writes an action string into the context. If a page
  or a plan tells you another module moves the dog, the page is wrong.
- **Validity rides beside the value.** `sensor_reading` and `scan_latest` carry the flags
  (`distance_valid`, `valid` per bearing), and the interlock branches on the flag before the number.
  A consumer that reads only the value is a defect.
- **Off is not absent.** 21 of the 37 ship `off`; they are registered, reported by
  `GET /api/v1/modules` with a reason, and turn on through `modules.<name>.enabled`. Two of them
  (`health`, `sensor_health`) exist for the safety flip that is still owed (#26), which is the
  owner's call and not an agent's.
- **Two modules are expected everywhere even though neither is `required`:** `hal` and `hal_motors`.
  A runtime without them is a simulator, and `python -m houndmind_ai --dry-run` is how you find that
  out without starting one.

