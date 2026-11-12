# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and adheres to semantic-ish sections.

Current Release: v2026.01.18 • Author: 7Lynx


## [Unreleased]

- **The action repertoire is classified.** `config/actions.jsonc` gained an `actions` table: one class
  per action (`locomotion`, `posture`, `expression`, `non_motion`), and the class decides which part of
  the interlock's envelope applies. Every name a catalog bucket lists must have a class, or the runtime
  refuses to start and names the action it could not place.
- `GET /api/v1/repertoire`: every action the running device can execute, with its class and the
  parameters it reads — the classification unioned with the HAL's own action list. This is the menu a
  client should render instead of one baked into the app.
- **HAL audio**: `sound(name, volume)` plays one of the dog's built-in effects and
  `speak(text, volume)` uses the vendor's speech path, so a routine can talk without the optional
  `voice` module. Audio runs on its own worker, so a sound never holds up a gait; `FakeDogHAL` records
  both.
- `rgb` keeps its `bps` argument, so an LED effect can specify its animation rate instead of silently
  running at the vendor's default.
- `state.actuators.source` and `state.actuators.displaced`: the producer that won the tick, and how
  many intents a higher-priority one overrode. A client that pressed forward can now tell "someone
  else is driving" from "the dog ignored me".
- `state.supervisor`: whether the watchdog is holding motion and why, which modules it asked the
  runtime to restart, and which it has given up on. `docs/CONTROL_API.md` §4 documents both.
- **Board detection** (`src/houndmind_ai/board/detect.py`): the device-tree model is read once at boot
  and classified as `pi4`, `pi5`, `unsupported` or `unknown`. `GET /api/v1/meta` now reports `board`,
  a field the contract has promised since the control plane shipped while nothing ever set it, and
  `profile`, which can differ from the board when `HOUNDMIND_PROFILE` is set.
- `settings.device.device_id` is a real key with a schema entry; it was read by `main.py` and shipped
  nowhere, so `device_id` in `/meta` and in every log record was always the hostname fallback.
- `profiles.pi5`: the same cadence and enablement as `pi4`, with thermal warning thresholds that suit a
  board which idles near 65 °C and throttles at 80 °C. **Unmeasured on hardware** — the values are the
  board's published figures, not a bench result.
- `Source.ROUTINE` (`15`): a routine ranks above idle behaviour and below navigation, so a routine
  yields to whatever is avoiding an obstacle. `MODE_ALLOWED_SOURCES` needed no edit — `idle` and
  `patrol` are `frozenset(Source)`, so the new member is admitted there and excluded from `manual`
  and `rest` by construction. Nothing produces one yet: the runner arrives with the routines phase.

- `GET /api/v1/routines` and `POST /api/v1/routines/{id}/run` (`docs/CONTROL_API.md` §2/§3): what the
  runner loaded — including each refused file with the validator's own reason — and a start that
  publishes one step per tick, optionally as a `dry_run` rehearsal that moves nothing. `409` covers
  both a run in progress and a request still queued for the next tick, `404` suggests the closest id,
  and `503` means no runner is loaded. `GET /meta`'s `capabilities` gains `routines` when one is.

- **Routines run.** `behavior/routine_runner.py` plays a routine from `settings.routines.dir` one
  step per tick through the normal intent path, so the interlock, the obstacle stop and the mode
  gate all apply to it; the first refusal ends the run instead of skipping the step, `dry_run`
  walks the steps without publishing anything, and a broken routine file is skipped by name rather
  than stopping the runtime. Two identical steps are two commands: the runner retires its intent
  between steps, which clears the dedupe memories that would otherwise merge them.
- `settings.routines.dir`: where the routine files live, `~/.houndmind/routines` by default. `~` is
  expanded at startup and a missing directory is an empty list, not an error.
- Routine steps keep the parameters the catalog declares: a `forward` with `speed`/`steps`/`wait`
  now reaches the HAL with them, and a parameterised locomotion step runs on the motor module's own
  worker instead of holding the tick.
- `POST /stop` stopped the motion but not a running routine: the runner published its next step on
  the following tick and the dog walked again. The route now sets `routine_stop`, which the runner
  consumes and ends the run as `stopped` — only when a runner is loaded, so the flag cannot outlive
  the stop and kill the next run.

- `state.routines` in the snapshot and a `routine` socket event: the run the runner is playing,
  step by step, as the same object `GET /api/v1/routines` calls `current`. The event fires only
  when the run moves — a new step, a new state or a veto — never on the tick that republishes
  it, which is the rule P1 set for `decision`. A client that was told `202` can now follow the
  run to its end and see the `veto` that stopped it.

- Twenty routine fixtures in `tests/fixtures/routines/` — one file per rule in `docs/ROUTINES.md` — and
  `tests/test_routine_fixtures.py` to hold them: every `invalid_` file is asserted against the problem it
  is *named* for, and `RoutineStore` loads the directory in place, because it is a legal routines
  directory. The quarantine rule is therefore proved over real files rather than invented ones, and
  `docs/ROUTINES.md` points at the set.
- The LED manager's requests gained a lifetime: `{mode, color?, bps?, until_ts?}`. `until_ts` is a
  deadline on the monotonic clock — once it passes, the request stops winning, its key is cleared and
  the next source in `settings.led.priority` takes the strip. A request without `until_ts` stands until
  it is replaced, so nothing that ships today changes behaviour. When the request that owned the strip
  expires and nothing else is live, the strip now returns to `led.default_color` with the new
  `led.idle_mode` (default `breath`) instead of keeping the last expression forever. A request's own
  `color` is honoured (it used to be dropped, `safety/sensor_health.py` was already sending one) and
  `bps` finally reaches the HAL, from the request or from the new `led.bps` map keyed by source.
- `modules.routine_runner` in the shipped config and `docs/ROUTINES.md`, the routine file format as a
  `contract`: keys, `allow_locomotion`, the refusal rules, and one example `check_routine` accepts —
  asserted by `tests/test_docs_routines.py`, so the doc cannot drift into printing a routine the device
  refuses. `docs/README.md` gains its row, and the programming guide the context keys the runner
  publishes (`routine_request`, `routine_report`, `routine_run`, `routine_stop`) and the `routines`
  config section it shipped with.

### Changed
- `POST /api/v1/command` accepts any action classified in `config/actions.jsonc`, not only the twelve
  names in `KNOWN_ACTIONS`. A name nothing classifies is still a `400` with a did-you-mean.
- The interlock judges every class, not only the gaits: `act/gateway.py` returned early for anything
  that was not a locomotion action. Two consequences — a posture or an expression now answers to the
  tilt latch and the battery floor, and every action (`rgb`, `sound` and `head` included) spends its
  deadman, so a stale non-motion command can no longer run late.
- `profile` in `config/settings.jsonc` ships as `auto`: the profile now comes from the board instead of
  being hard-coded. `HOUNDMIND_PROFILE` still wins over the file.
- An unknown profile name is a load-time error with a did-you-mean; it used to be a warning, so a typo
  ran the shipped cadence and looked exactly like success. A profile *resolved* from the board may have
  no overrides — a config with no `profiles` table is legal.
- The installer accepts Python 3.11–3.13, matching `requires-python`, instead of 3.10–3.11. It was
  wrong in both directions: 3.10 is outside the range `pip install` accepts, and 3.12/3.13 were refused
  even though the package declares support for them.


### Fixed
- The interlock's `unknown_action` veto was unreachable in the runtime: `act/gateway.py` skipped the
  interlock for every action outside `MOTION_ACTIONS`, so the catalog's gestures were not vetoed — they
  were unchecked. Every action is judged now, and a name nothing classifies is refused with a reason.
- The action catalog listed `nod lethargy` twice, as `nod_lethargy` and `nod lethargy`. Both
  canonicalise to the same vendor action, so it was two keys for one behaviour and two chances to
  classify it differently.
- The installer reported a Pi 5 as a Pi 4, and detected a Pi 3 it then tried to install on. It now
  refuses an unsupported board before touching anything and names `v2026.01.18` as the last release
  that ran on one. `tests/test_board_detect.py` holds the installer's copy of the rule and the
  runtime's to the same answers.
- The installer's OpenCV model downloader pointed at a repo-root `tools/` directory deleted with the
  legacy servers, so it had silently done nothing. It resolves `src/tools/` now.
- A classified non-motion command returned `202` and then did nothing: `hal/motors.py` passed an
  empty dict to the HAL, so a `sound` had no effect name and an `rgb` no colour. The actions whose
  parameters are the whole command now reach the HAL verbatim. Locomotion stayed out of that set
  here because `speed`/`steps` would make the HAL block the tick; it landed with the motor worker
  described above.
- `trot` skipped the obstacle stop: the forward family was `{"forward"}` even though `trot` is a
  forward gait. `trot` is a motion action now (so it also counts for the watchdog hold and the
  scan lock) and the sonar gate applies to it.
- The `head` action ignored its `pitch` parameter: `hal/vendor.py` built the target as
  `[yaw, pitch, 0]`, while the vendor unpacks `[yaw, roll, pitch]`, so a non-zero `pitch` rolled
  the head by that angle and the pitch channel stayed at zero. Every caller in the tree sends
  `pitch: 0`, which is why the shipped runtime looked correct — a client using the parameter
  `DogHAL.action` documents got the wrong joint with no error to notice.

- The motor cooldown swallowed commands: a repeat inside `min_action_interval_s` returned without a
  word and the command was never retried, and the dedupe compared action names only, so a step with
  new parameters was treated as the step already running. The key is now the action **and** its
  parameters, an absent command clears it, and a deferred command runs on the first tick after the
  interval — with a counter and one log line that prove it was not lost.
- A refused intent from an internal producer (navigation, behaviour, a routine) appeared in the
  decision record as the tick's intent with no veto: `act/gateway.py::_resolve` recorded refusals for
  clients and for the mode gate only. The record carries the reason now, which is what lets a
  routine stop at the first veto instead of guessing from `motion_verdict`.
- `manual` mode refused `Source.ROUTINE` (`kernel/commands.py`), so a user who started a routine from
  a client watched it die at step one. A routine is the same hand on the wheel, scripted: `manual`
  still excludes navigation and behaviour, and `rest` still excludes routines.


### Docs
- `docs/CONTROL_API.md` §2/§3 document `GET /api/v1/repertoire` and the four action classes;
  `docs/FEATURES_GUIDE.md` §2/§7 cover the HAL audio primitives and how to classify a custom action;
  `docs/ARCHITECTURE.md` §4/§5 replace the motion-only interlock table with the class table.

- `docs/BASELINE.md` gains a second addendum: the re-measured counts (416 passed across 56 test files,
  84 source files under `mypy`), and the three items the Pi 5 edition closed — H-06, the installer's
  board mapping, and the installer's Python gate. Its "known gap" paragraph said the installer's
  3.10/3.11 restriction was out of scope; that restriction is what this change removes, so the
  paragraph would have described a tree that no longer exists.
- `docs/PI3_VALIDATION.md` deleted and its still-true rows moved into `docs/INSTALL.md` § "Bench
  checklist". A checklist for a board we no longer support is a second source of truth; the
  replacements are the rows that apply to a Pi 4/5 (scan, stop, watchdog, tilt, logging) plus the
  motion-flag warning on `tools.smoke_test`.
- `docs/INSTALL.md` rewritten around the hardware that actually exists: Pi 4/5 only, Python 3.11–3.13,
  and the Robot HAT **V5** requirement for a Pi 5 (a V4 supplies 5V/3A against the Pi 5's 5V/5A, so the
  board can shut down mid-run). The Python 3.10/pyenv instructions are gone, because 3.10 is outside
  `requires-python` and the docs were telling operators to build an environment `pip install` refuses.
- `docs/ARCHITECTURE.md` §2 and §6 corrected again: `board/` exists now, `pi3` is not the default and
  is not a profile at all, and the resolution rules are written down in the order they apply.
- `README.md`: the primary-features table now lists `Sensor Health`. The module is registered by
  the runtime and ships disabled, but the authoritative default table skipped it, so a reader
  could not tell it existed.
- `docs/README.md`: the documentation index — every file, its status, and who it binds. A file with
  no row in that table is unreachable, so the row is part of the change.
- One schema for all ten remaining docs: a `Status:` line (`contract`, `design`, `reference`,
  `guide`, `runbook`, `index`, `historical`), the existing `Version:` line, and a `Pairs with:` line
  naming the code it describes.
- `docs/ARCHITECTURE.md` corrected against the tree it claims to describe: the package layout
  (`board/`, `android/`, `nav/`, `act/calibration.py` did not exist), the adapter names
  (`PidogHAL`/`FakeDogHAL`, not per-board classes), board profiles as JSON5 `pi3`/`pi4` rather than
  TOML, `/health` versus `/modules`, the nonexistent `--unsafe` flag and `houndmind doctor`, and the
  false claim that safety cannot be disabled in configuration — the interlock cannot, the module
  ships off.
- `docs/CONTROL_API.md` corrected against `services/api.py`: no mDNS address, no
  `POST /calibration/run`, no `command_ack` frame, no `device` object in the snapshot, no
  `capabilities.actions` list, and the event names reduced to the five that are actually published.
  The endpoint table is still parsed by `tests/test_api_routes.py`, so it stays in lockstep with
  `ROUTES`.
- `docs/BASELINE.md` gains an addendum rather than an edit: `requires-python` moved to
  `>=3.11,<3.14`, ruff is pinned and configured, H-12 is fixed by `testpaths`, and the current
  numbers are recorded with the interpreter that produced them.
- `docs/FEATURES_GUIDE.md` renumbered to close the gap at §11 and remove the duplicate §22 and §25;
  voice setup folded into §17; profiles, path planning, disabling and troubleshooting ordered last.
  Every `§` cross-reference in `README.md` and `ROADMAP.md` was checked against the new numbers.
- `docs/HOUNDMIND_PROGRAMMING_GUIDE.md` rewritten around the code: `loop.tick_hz` (not `core.tick_hz`),
  `IntentBoard` instead of the removed `navigation_action`/`behavior_action`, request-driven
  calibration instead of a `--calibrate` flag that does not exist, the commands CI actually runs, and
  the stray closing chat block removed.
- `docs/PIDOG_PROGRAMMING_GUIDE.md` gains a vendor method reference and points at the HoundMind guide
  instead of the deleted `api_reference.md`.
- `docs/LOGGING.md` documents both support bundles — the CLI one carries logs, the HTTP one does not.
- `docs/INSTALL.md` states the installer's Python 3.10–3.11 gate and the `pyproject.toml` range it
  disagrees with, instead of leaving the contradiction silent.

### Removed
- `docs/api_reference.md`, `docs/QUICK_START_PROGRAMMING.md` and `docs/voice_setup_instructions.md`.
  Their content moved into `HOUNDMIND_PROGRAMMING_GUIDE.md` (§4–§6, §1, §14), `FEATURES_GUIDE.md`
  (§17) and `PIDOG_PROGRAMMING_GUIDE.md` (vendor method reference). Four documents described the same
  context keys; two of them were wrong.

### Added
- `services/`: the control plane — one process, one port (8420), one authenticated API (D7).
  REST, WebSocket telemetry, MJPEG and the web app are routes on the same aiohttp application,
  and it runs on its own thread so the decision loop never blocks on a socket. This is what
  B-05 was: there was no way to command the dog from anything but the dog.
- `services/auth.py`: the device token is generated on first start into `~/.houndmind/api_token`
  (0600, never logged, never in the repo), with `state:read` / `move` / `config` / `admin`
  scopes, a single-use 6-digit pairing code for phones, a pairing rate limit, and a bounded
  motion audit recording the reason for every veto (D8, M-13).
- `kernel/commands.py`: `CommandBus`, the bounded, acknowledged hand-off between the control
  plane and the actuator gateway. A full queue answers `429` instead of adding latency to the
  servo bus, and every submitted command gets exactly one verdict back.
- `services/state.py`: the `docs/CONTROL_API.md` §4 snapshot, including the validity flags a
  client must honour — an invalid reading stays `null`, it never becomes a plausible zero.
- `services/stream.py`: WebSocket fan-out at 10 Hz where `state` is a latest value (a slow
  client skips frames) and `event`/`command_ack` are never dropped (a client that cannot keep up
  is disconnected, because losing a veto reason is worse than losing a socket).
- `services/camera.py`: one MJPEG producer, many viewers, per-client frame cap (M-04).
- `services/sessions.py`: client sessions keyed by a token *fingerprint*, so "what did I ask and
  what happened" is answerable without storing a credential.
- `services/module.py`: `ControlPlaneModule` owns the thread, the socket and the shutdown. A
  port already in use disables the module with the reason instead of taking the runtime down.
- `main.build_registry` creates one `CommandBus`, hands it to the gateway and to the API module.
- `docs/CONTROL_API.md` gained `GET /api/v1/history`, and the route table is now asserted against
  the code by `tests/test_api_routes.py`.
- `settings.api`: typed section for host, port, token path, telemetry rate, pairing, queue size,
  ack timeout, link-loss window, client cap and log tail.
- `kernel/state.py`: a lock-protected state store behind `RuntimeContext`. Sensor and scan
  services publish from daemon threads while the loop reads, so the shared mapping now has a
  lock and snapshot reads instead of relying on `dict` operations being individually atomic.
- `kernel/registry.py`: modules are registered with a `Capability`, and asking for the sole
  provider of an exclusive capability (the servo bus) raises instead of guessing.
- `act/gateway.py`: one motion path. The gateway resolves `safety` > `watchdog` > `navigation` >
  `behavior` in a single declared place, sends the winner through the interlock, and publishes
  `motion_command` / `motion_verdict` / `tilt_latched`.
- `kernel/config_schema.py`: config validation is enforced, not advisory. Unknown keys are an
  error with a did-you-mean suggestion.
- `hal/vendor.py`: `PidogHAL`, the vendor-backed `DogHAL`, plus `hal/module.py`: `HalModule` owns
  the dog and publishes it as the context key `hal`. Before this, `hal/sensors.py`,
  `hal/motors.py` and `navigation/scanning.py` each opened their own `Pidog()` and raced over
  one servo bus; the last one to start also won the `pidog_owner` key that decided who closed it.
- `hal/sensors.py`: `SensorService` polls a `DogHAL` instead of a vendor object, and the sensor
  signal conditioning (multi-sample median, outlier rejection, debounce, EMA, IMU low-pass)
  lives in `PidogHAL` next to the reads it belongs to.
- `DogHAL` gained `sample_distance()` (a head scan needs the distance *after* the head moved) and
  `apply_offsets()` (calibration offsets are user data, applied by the owner of the servos).
  `SensorSnapshot` carries `acc`, `gyro` and `sound_detected`, which consumers already read.
- `main.build_registry(config, hal=...)` injects a `DogHAL`; `FakeDogHAL` is now enough to run
  the sensor, scan, LED, head and posture paths, and `tests/test_runtime_tick.py` no longer
  carries a `HARDWARE_MODULES` exclusion list.
- `kernel/config_schema.py`: `settings` is validated section by section. Every section the
  repo ships — `attention`, `balance`, `battery`, `behavior`, `calibration`, `emotion`,
  `energy`, `face_recognition`, `habituation`, `led`, `logging`, `mapping`, `motors`,
  `movement`, `navigation`, `orientation`, `perception`, `performance`, `personality`,
  `quiet_mode`, `safety`, `semantic_labeler`, `sensor_health`, `sensors`, `service_watchdog`,
  `slam_pi4`, `vision_pi4`, `voice_assistant`, `watchdog` — rejects an
  unknown key (with a suggestion) and a value of the wrong type, and profile overrides are
  validated the same way. An unknown *section* is an error too, so `settings.voice` instead of
  `settings.voice_assistant` no longer loads a table nothing reads. Enum-valued keys carry the
  choices the code branches on, and nullable keys say so.
- `settings.performance.runtime_ema_alpha` is a documented key (default `0.2`): the runtime
  read it with a hard-coded fallback but the shipped file never mentioned it.
- `settings.logging.console_level` is an accepted key, so the console can be quieter than the
  file without editing code.

### Changed
- **One owner for the servo bus.** `PidogHAL` now serialises `read`, `sample_distance`, `action`
  and `stop` on one re-entrant lock. The loop's motors, the scan worker and the attention module
  were three callers of an I2C bus and a vendor action queue that is not thread-safe; two of them
  interleaved is a servo command arriving mid-step. The cost is latency and it is deliberate:
  every caller is a worker, never the decision loop.
- **Head moves no longer block the tick.** Head-following (`hal/motors.py`) and attention
  (`behavior/attention.py`) queue the move (`wait=False`) instead of waiting for the servos to
  finish, and a scan in flight owns the head: nothing else moves it until the sweep is published.
- **A scan no longer blocks the decision loop.** `ScanningModule` submits the sweep to an owned
  worker (`kernel/scheduler.py`) and returns immediately, instead of running nine head moves and
  27 distance samples inside `tick` (~2.6 s against a 200 ms budget, H-01/#13). The service's
  private daemon thread is gone with it: a thread nobody owns cannot be stopped, and `daemon=True`
  with no supervisor entry is the pattern the architecture forbids. `scan_in_flight` is published
  while a sweep is running, and a request that arrives during one is dropped rather than queued —
  its result would be superseded before it started.
- `scan_continuous: false` now means "scan while a motion is being executed". The old flag
  disabled scanning in exactly that case: the continuous thread only started when the flag was
  true, and the tick path only ran when the dog was *not* moving.
- **Internal producers publish typed intents; the four action keys are gone.** `safety_action`,
  `watchdog_action`, `navigation_action` and `behavior_action` are no longer written or read.
  `kernel/intents.py` keeps one slot per `Source`, and an entry expires unless it is refreshed
  within the board's hold window. A producer that wedges or blocks stops the dog instead of
  leaving it walking: the deadman used to protect clients only, because the gateway re-stamped
  whatever it found in those keys on every tick. `motion_cancel` reports every intent a
  higher-priority one displaced, so "the dog ignored me" has an answer in the event stream.
- **A mode now gates every source, not just clients.** `rest` used to veto client motion while
  the behaviour FSM and the navigator kept driving; `GET /state` reported a resting dog that was
  walking. `manual` is now a hand on the wheel (client in, autonomy out) and `rest` allows only
  the watchdog and the system. `stop` passes the mode gate and the interlock: an escape hatch a
  mode can refuse is not an escape hatch.
- Command dedupe compares action, source **and** parameters, so a producer that keeps asking for
  `forward` at a new speed is heard instead of being dropped as the same intent.
- `canonical_action` / `legacy_action` moved to `kernel/commands.py` next to the action
  vocabulary they translate; `act/gateway.py` re-exports them.
- **One watchdog, and recovery is "stop and report".** `safety/service_watchdog.py` is merged into
  `safety/watchdog.py`, which now delegates the restart decision to `kernel/supervisor.py`.
  Recovery no longer poses the dog: `recovery_mode`, `recovery_behavior` and `recovery_action` are
  gone, and a stale reading publishes a `stop` intent through the same gateway and interlock as
  any other command. Candidates are modules that are enabled *and* started — the old list was
  `module_names`, which includes every disabled module, so the stale set was never empty on the
  shipped config and the dog was told to lie down every five seconds (H-03).
- **Restarts back off and eventually give up.** `restart_cooldown_s` is the base delay,
  `restart_backoff_factor` the multiplier, `restart_max_delay_s` the cap, and after `max_restarts`
  the module is reported failed instead of being retried forever. A module that stays up for
  `healthy_after_s` earns a fresh budget.
- **A slow scan is no longer "stale".** The scan staleness window is `max(scan_timeout_s, 1.5 ×
  measured scan duration)`; the shipped sweep takes ~2.6 s and the old fixed window was 0.8 s, so
  a healthy scan was stale by definition (P3-4).
- **`stop` bypasses the motor rate limiter and outranks every source.** A watchdog hold used to be
  able to sit behind a gait for the 200 ms action interval, and a supervisor's stop could lose a
  tick to a higher-priority retreat. `hal/motors.py` skips `min_action_interval_s` for `stop`, and
  `act/gateway.py` ranks a `stop` above any other intent whatever its source.
- **A module that gives up during a restart is no longer marked started.** `core/runtime.py`
  checks `status.enabled` after `start()` and reports the reason instead of putting a module that
  just failed back into the tick list.
- `optional/vision_pi4.py` publishes `vision_frame_jpeg` next to `vision_frame`, and
  `services/camera.py` reads the encoded key. The raw array is still what face recognition, the
  semantic labeler and SLAM consume; encoding once per frame replaces the old encode loop that ran
  once per client. OpenCV is now imported before the backend branch, because the picamera2 path
  needed it to encode and previously skipped every frame when it was absent.
- The gateway accepts `Command` objects from the bus in addition to the legacy context keys. A
  client command can be vetoed by the interlock like any other producer, and each client is told
  the fate of its own command even when a higher-priority producer wins the tick.
- `aiohttp` is a base dependency. It is the only new dependency in this phase; its resident cost
  on a Pi 4 has not been measured yet, which is a Phase 3 device task.
- `mode` is a typed value (`idle`, `patrol`, `manual`, `rest`) published as `runtime_mode`.
  `rest` and `manual` gate every source, not just clients, and `POST /stop` is never refused.
- `hal_motors` executes `motion_command` only; it no longer merges four context keys by `or` and
  deduplicates on the action string, which had made a `forward` from navigation and one from
  behaviour indistinguishable.
- `attention`, `led_manager`, `balance` and `scanning` reach the hardware through `hal.action()`
  instead of grabbing `context["pidog"]` and calling vendor methods themselves. `import pidog` in
  `src/` is now confined to `hal/vendor.py` (plus the optional voice module and the device CLI).
- `calibration/workflow.py` is the one remaining consumer of the raw vendor handle;
  `HalModule` still publishes it as `pidog` so a calibration run behaves as before until the
  wizard is rebuilt.
- `SensorHealthModule` is wired into the runtime (disabled by default, as before).
- Logging reads the keys `config/settings.jsonc` actually ships (`log_level`, `log_file_name`,
  `log_file_backups`, `log_file_max_mb`, `enable_console`, `enable_file`). Previously the
  configured DEBUG level was ignored and rotation was hardcoded to 10 MB.
- Log records carry four whitelisted context fields instead of every key in the runtime context,
  so a log line no longer serialises the whole config, the sensor history and the vendor
  hardware handle.
- The event log JSONL rotates at `logging.event_log_max_mb` (one generation) instead of growing
  until the SD card filled.
- `requires-python` is `>=3.11,<3.14`; Pi 3 support is dropped. `json5` is now a real dependency.
- Ruff is pinned (`0.17.4`) with an explicit rule set.
- `core/config.py` parses JSON5 with `json5` and nothing else. The 60-line comment stripper
  that duplicated it is deleted: it was only there because `json5` used to be optional, and a
  syntax error now names the file it came from instead of a hand-rolled message.
- `core/config.validate_config` is down to the cross-field rules a per-value schema cannot
  express (distance ordering, an interval inside its own bounds, turn speed above walk speed,
  `override_priority` keeping `safety`). The type and range checks it duplicated are gone with
  the schema that enforces them.
- CI runs on every branch and every pull request (`.github/workflows/ci.yml`), not just on
  `main`. Work now lands on one branch per phase and merges into `refactor/resurrection`, so a
  `main`-only trigger meant phase PRs were reviewed with no `ruff`/`pytest`/`mypy` result at
  all. Jobs, order and interpreter are unchanged: this widens the trigger, it does not relax the
  gate.

### Fixed
- A client command that sat in a tunnel can no longer execute on arrival: the deadman starts
  when the device receives it, and an expired command is refused by the interlock.
- **The placeholder vision inference thread is gone.** `vision_pi4` started a background thread on
  any install that enabled the camera; its whole job was `sleep(0.05)` and `{"result": "ok"}`, and
  it was on by default (M-03, #9). `inference_scheduler_enabled` now ships `false`, starts nothing
  without an `inference_fn`, and reports `vision_inference_status: unconfigured` when it is turned
  on with no model rather than pretending to infer. The scheduler and the preprocessor are kept and
  are what a real model plugs into; the scheduler starts only after a camera opens, so a failed
  camera cannot leave an orphan thread behind.
- Removed the `__main__` demo in `optional/vision_inference_scheduler.py` — the only `print()` in
  `src/houndmind_ai/` (L-03). The remaining prints are `src/tools/` device CLIs, where stdout is
  the interface.

### Removed
- `safety/service_watchdog.py`, `modules.service_watchdog` and `settings.service_watchdog`. The
  restart policy lives in `kernel/supervisor.py`, driven by `settings.watchdog`.
- `settings.watchdog.recovery_mode`, `recovery_behavior`, `recovery_action`, `restart_modules` and
  `restart_module_cooldown_s`: the watchdog no longer poses the dog, and one backoff replaces two
  cooldowns. An existing file that still sets them now fails to load with a did-you-mean, which is
  the honest outcome — they described behaviour that no longer exists.
- **The four per-feature HTTP servers.** Face recognition on 8088, the vision feed on 8090, voice
  control on 8091 and the telemetry dashboard on 8092 are gone, with their `http` config blocks.
  Three of them bound `0.0.0.0` and answered without any token; `GET /command?action=` on 8091 set
  `behavior_override` and moved the dog without passing the interlock, the deadman or the audit
  log (B-06). The control plane on 8420 replaces all four, behind one token.
- `optional/telemetry_dashboard.py` and `modules.telemetry_dashboard`. Every endpoint it served is
  a control-plane route: `/snapshot` is `/api/v1/state`, the HTML page is the web app, the support
  bundle is `/api/v1/support-bundle`, the camera is `/api/v1/camera/*`. Two things have no v1
  route yet and are documented gaps, not silent losses: the SLAM map/trajectory downloads
  (`slam_map_data` and `slam_trajectory` are still published by `slam_pi4`) and face enrollment by
  URL. Enrollment itself still works — `face_recognition_command` on the runtime context is the
  path the old `/enroll` handler used internally too.
- `tools/generate_auth_token.py` and the root `tools/` directory. The script printed a
  `{telemetry: {auth_token}}` snippet for a section that no longer exists; the token is written by
  `services/auth.py::TokenStore` on first start. Removing it also removes the root `tools/`, which
  shadowed `src/tools` on `sys.path` and broke `python -m tools.*` after a real install (H-05).
- `tools/voice_cli.py`, `tools/face_recognition_cli.py` and `tools/run_telemetry.py`: each existed
  only to talk to one of the deleted ports.
- `optional/wifi_localization.py` and `modules.wifi_localization`. It shelled out to `netsh wlan
  show networks`, which does not exist on Raspberry Pi OS, had no test, and was never registered.
- Eighteen `settings` keys that nothing in `src/`, `tests/` or `src/tools/` read:
  `navigation.enable_dynamic_scan`, `navigation.dynamic_scan_yaw_max_deg`,
  `navigation.scan_debounce_s`, `navigation.scan_smoothing_alpha`,
  `navigation.planner_influence_weight`, `mapping.safe_path_min_length_cells`, and the whole
  `movement` step/speed table except `turn_degrees_per_step`, `speed_normal` and
  `speed_turn_slow|normal|fast` (`gentle_recovery_speed`, `turn_steps_*`, `walk_steps_*`,
  `backup_steps`, `speed_slow`, `speed_fast`, `speed_emergency`, `step_pause_s`). They were
  documented as tuning knobs and changed nothing; the gentle-recovery threshold that does work
  (`navigation.gentle_recovery_stuck_count`, `navigation.gentle_recovery_cooldown_s`) was read
  by the module but missing from the file, and is now shipped.

### Fixed
- `python -m houndmind_ai` no longer dies with `ModuleNotFoundError: cv2` on an install without
  OpenCV, which included the installer's own lite fallback.
- `loop.max_cycles` defaults to `null`; a fresh install used to run for two seconds and exit.
- `src/tools/smoke_test.py` is no longer collected as a test, so the suite can collect at all.
- `src/houndmind_ai/core` has an `__init__.py`; it was an accidental namespace package that
  package discovery could not see by name.
- The built wheel contains `tools/` and `houndmind_ai/core/`, so the documented
  `python -m tools.*` commands work after a real install.
- **Decision records**: one record per tick explaining why the dog did that — the intent that won,
  every intent that lost with its reason (`mode`, `precedence`, or the interlock's own veto), the
  readings the decision used with their validity flags, and a `confidence` that stays `null` rather
  than inventing `0.0`. Published four ways over one object: `GET /api/v1/decisions?limit=50` (the
  last 200 in a bounded ring), `state.decision` in every snapshot, the `decision` WebSocket event
  (sent when the *choice* changes, not on every tick, because that channel is never dropped), and an
  optional JSONL (`logging.decision_log_file_enabled`, off by default — ~9 MB/hour at 10 Hz).
- `state.behavior_state` publishes the FSM's current state, so a decision record can name the state
  the dog was in when it decided.
- `python -m tools.replay_decisions` replays a recorded `logs/houndmind_decisions.jsonl` through the
  real control plane, so the decision feed can be built and reviewed without the dog on the desk.
  `--check` validates a file and serves nothing; `--speed 0` plays it instantly. `DecisionRecord`
  gained `from_dict` — the reader `SCHEMA_VERSION` always implied: an unknown shape is refused by
  name, and a veto without a reason is an error rather than a guess. Replay is read-only and moves
  nothing.

### Notes
- **Upgrading a config.** If `config/settings.jsonc` still has a `settings.<module>.http` block or
  a `telemetry_dashboard` section, the runtime now refuses to start and names the offending path.
  Delete those blocks; nothing in them has an effect any more. `tests/test_no_legacy_http.py`
  keeps the servers deleted rather than relying on review to notice a fifth one.


## [v2026.01.18] - 2026-01-18

### Changed
- Simulation mode (shim/sim) is no longer supported; all features require real PiDog hardware.
- PackMind and CanineCore have been unified into a single system; all features and docs reflect this change.
- Release: bumped version and updated documentation headers to v2026.01.18.
- No functional changes since `v2026.01.16`; this release consolidates docs, metadata, and release notes.
 - Moved developer CLI/tools into a proper package: `src/tools` (removed top-level `tools/` copies). This fixes importability during CI and editable installs.
 - Docs: added troubleshooting and support bundle collection instructions to `docs/INSTALL.md`.
 - Fix: use timezone-aware UTC datetimes in logging and support-bundle metadata to avoid deprecation warnings.

### Notes
- Files updated: `pyproject.toml`, top-level docs and guides (version header updates).
- If you rely on runtime behavior, there were no code changes since the previous release (see v2026.01.16 notes).


## [v2026.01.16] - 2026-01-16

### Added
- Pi4 optional modules: vision feed, face recognition, semantic labeling, SLAM stub, voice assistant enhancements, telemetry dashboard.
- Telemetry performance metrics (FPS, tick latency, CPU/GPU/RAM) and dashboard snapshot integration.
- Pi4 profile overrides with higher tick rates and feature flags.
- Background service watchdog with restart policies (enabled by default, low-impact).
- Install automation and validation helpers plus camera/voice/face CLI tools.

### Changed
- Runtime package renamed from `pidog_ai` to `houndmind_ai` and imports updated.
- Installer flow extended with Pi3/Pi4 presets and dependency verification.
- Docs consolidated and updated across README, install guides, and API reference.
- Default configuration: basic watchdog enabled; safety/throttling features disabled by default for bug testing.

### Notes
- Safety, balance, and health throttling are opt-in via `config/settings.jsonc`.

---

## [v2025.11.04] - 2025-11-04

### Improved
- Guided installer (`scripts/install_houndmind.sh`):
  - I2S audio setup now installs `alsa-utils`, guides reboot after `i2samp.sh`, and adds a dedicated audio test option (lists devices, sets volume, plays a test sound).
  - Header shows Python version and prints clear notes when on 32‑bit OS or Python 3.13 (heavy ML wheels like mediapipe/tflite may be unavailable and are optional).
  - Verify step prints `robot_hat` load path and whether it exports `Robot` to catch mismatched installs early.
  - New “Repair vendor modules” option to remove conflicting pip installs and reinstall Robot HAT (2.5.x), Vilib, and PiDog from vendor sources.

### Docs
- `docs/INSTALL.md`: Added a “Guided installer quick start (Raspberry Pi)” section at the top with exact commands and the recommended menu flow; clarified that mediapipe/tflite warnings on Pi 3B (32‑bit) or Python 3.13 are expected and safe to ignore when using the lite path.
- `README.md`: Added a concise guided installer quick‑start with the recommended menu flow under Install and run.

### Notes
- No behavior or runtime changes; improvements focus on installation reliability and first‑time setup clarity on the Pi.

## [v2025.11.03] - 2025-11-03 - Guided installer launcher, vendor-aligned install docs, and telemetry version sync

### Added
- Guided installer enhancements (`scripts/install_houndmind.sh`):
  - New launcher options to start CanineCore (main/control) and PackMind (with optional `PACKMIND_CONFIG` preset) directly from the menu.
  - One-stop menu: install vendor modules (Robot HAT 2.5.x, Vilib, PiDog), set up I2S audio, run vendor demo, verify imports/I2C, install HoundMind deps for Pi 4/5 (full) or Pi 3B (lite), and launch systems.
- Install guide overhaul (`docs/INSTALL.md`):
  - Linear Raspberry Pi flow with anchors: A0 (OS) → A1 (vendor modules) → A2 (checks/calibration) → A3 (deps per model) → A4 (run systems).
  - Clear separation of CanineCore vs PackMind; added a note that the guided installer can launch either system.
  - Pi 3B OS guidance (32-bit recommended; 64-bit supported with caveats) and vendor steps aligned with SunFounder docs (Robot HAT 2.5.x install.py, Vilib install.py, PiDog setup.py, I2S i2samp.sh).
- Tools: camera/audio helpers referenced from the guide to list devices and probe camera.

### Changed
- Telemetry server (`packmind/runtime/telemetry_server.py`) now reads version from `packmind.__version__` to avoid drift.
- `packmind.__version__` bumped to `2025.11.03` for release consistency.
- README and subsystem docs updated to reflect guided installer launch capability and current doc version.

### Notes
- Remaining file headers that still show 2025.11.01/02 are unchanged modules and will be updated on their next functional change.

## [v2025.11.02] - 2025-11-02 - Pi import robustness, explicit simulator alias, and docs

### Added
- `pidog_sim` package: explicit simulator alias that forces sim mode and re-exports the `pidog` shim. Use `from pidog_sim import Pidog` for examples/tests that must not touch hardware.
 - Telemetry server runner: `src/tools/run_telemetry.py` now starts the FastAPI dashboard using config defaults with `--host/--port` overrides and `--force` to run when disabled.
- Telemetry quickstart: `docs/telemetry_quickstart.md` with install instructions and usage.

### Changed
- `pidog` shim hardened to avoid self-import and to support multiple vendor class name variants (`Pidog`, `PiDog`, `PIDog`, `PIDOG`). On the Pi with the official package installed, the shim now reliably delegates to the real hardware library; otherwise it falls back to the simulator.
- `packmind/orchestrator.py` can be run directly (`python3 packmind/orchestrator.py`) without `PYTHONPATH` tweaks; a small bootstrap adds the repo root to `sys.path` when needed.
- `packmind/__main__.py` added so `python3 -m packmind` starts the orchestrator.
 - `src/tools/caninecore_checkup.py` now prepends the repo root to `sys.path` when run from `src/tools/`, fixing `ModuleNotFoundError: canine_core` on the Pi.
- README updated with a new "Hardware vs Simulator imports: pidog vs pidog_sim" section for clarity.
- Telemetry config flags (`TELEMETRY_ENABLED`, `TELEMETRY_HOST`, `TELEMETRY_PORT`, `TELEMETRY_BASIC_AUTH`) consolidated in `packmind/packmind_config.py`; duplicate `TELEMETRY_ENABLED` key removed from the logging section.

### Notes
- You can still force simulation anywhere with `HOUNDMIND_SIM=1`.
- On the robot, prefer `from pidog import Pidog` (uses real hardware automatically). For explicit sim in docs/tests, use `from pidog_sim import Pidog`.
- Docs: corrected voice setup to use the canonical PyPI name `SpeechRecognition` (import as `speech_recognition`) and added Pi-friendly PyAudio guidance (PortAudio headers + python3-dev, with apt fallback).

## [v2025.11.01] - 2025-11-01 - Desktop Simulation Mode, Lite Face Backend, and Setup Docs

### Added
- `pidog` shim: uses the real hardware package by default on the Pi; provides a safe simulated `Pidog`/`PiDog` when `HOUNDMIND_SIM=1`.
- No-op motion with plausible sensor values for development on desktops.
- Optional noise via `HOUNDMIND_SIM_RANDOM=1`.
- OpenCV Haar-based detection with low-res grayscale frames; optional LBPH identity when `opencv-contrib-python` is installed.
- Configurable via `FACE_BACKEND = "lite"`; uses `FACE_LITE_DATA_DIR` for simple training assets.
- Pi 3B preset now defaults to the lite backend when face recognition is enabled.
- `scripts/train_faces_lite.py` — trains LBPH from `data/faces_lite/<name>/*.jpg`.
 - `src/tools/lite_face_smoke_test.py` — runs the lite backend and logs detections for N seconds.

### Changed
- Added desktop simulation mode instructions and PowerShell/Bash examples.
- Added optional Face Recognition install block with cmake/build-tools note and a pointer to the setup guide; referenced `requirements-lite.txt` for Pi 3B.
- Added quick-start section for the lite face backend (config switch, training CLI, smoke test).
- Documented default vs lite face backends; added usage, training, and smoke test links.
- Added performance notes for Face Recognition on Pi 3B with link to the setup guide.
- Added `FACE_BACKEND` and `FACE_LITE_DATA_DIR` configuration keys.

### Maintenance
- Analyzer hardening and sim-safety:
  - Introduced a `PidogLike` Protocol and extended the pidog shim to align with runtime usage (read_distance, wait_head_done, rgb_strip.set_mode, stop_and_lie, close), reducing false-positive attribute warnings while keeping non-Pi runs safe.
  - Stabilized obstacle avoidance history slicing and recent-movement computations to avoid static analyzer mis-parses.
  - Enhanced audio service: robust float conversion for sound direction data, avoiding brittle casts.
  - Checkup tools and sensors now guard hardware calls with `getattr(...)/callable(...)` to prevent attribute errors on desktops.

### Notes
- See the full pre‑migration history in the original repository for entries prior to 2025‑10‑29.
