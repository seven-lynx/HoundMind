# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and adheres to semantic-ish sections.

Current Release: v2026.01.18

## [Unreleased]
- **`POST /api/v1/calibration/run` exists, and it cannot move the dog** (#17): the route was
  reserved rather than stubbed because a remote calibration that sweeps every servo is the most
  dangerous call in the product. Calibration in this tree only reads - servo trim, wall-follow
  distance error, the clearest scan angle, pose confidence - so the route is that read half: scope
  `config`, an allow-list of those four requests (`services/api.py::CALIBRATION_REQUESTS`), `400`
  for anything else and `503` when the runtime does not answer within a second. The safety is
  structural, not ceremonial: there is nothing for a physical confirmation to confirm, and a
  prompt that guards nothing teaches the operator to approve it reflexively. A calibration that
  *does* move servos needs its own route and its own arming step; it cannot dispatch through this
  one. `CalibrationModule` now dedupes on `(request, id)`, so the same reading can be asked for
  twice instead of being a silent no-op for the life of the process, and
  `tests/test_api_routes.py` proves a run leaves `FakeDogHAL.offsets_applied` empty. Writing a trim
  stays a device action (`python -m tools.calibrate_servos --apply`). `docs/CONTROL_API.md` §10,
  `docs/FEATURES_GUIDE.md` §16/§26 and the CHANGELOG follow.
- **No document promises a `houndmind doctor` command** (#23): it never existed, and two places
  still named it. The `pyproject.toml` packaging comment cited it as the B-08 example (it now cites
  `python -m tools.hardware_checkup`, which is the case that actually exercises the `tools*`
  include), and the support bundle's own `README.txt` told the user it "adds file logs (Phase 6)" -
  inside the zip a user is asked to attach to a bug report. That README now says what the bundle
  carries and where file logs actually are (`GET /api/v1/logs`, or
  `python -m tools.collect_support_bundle` on the device), and `tests/test_api_routes.py` asserts it
  stops naming the phantom. Fixed in the same sweep because it is the same class of claim and was
  contradicted by the very page it sat on: `FEATURES_GUIDE.md` §26 listed TLS under "not in v1"
  while §26 documents it and `services/tls.py` ships it.
- **Vilib no longer serves the camera on a port of its own** (#15): `optional/vision.py` called
  `Vilib.display(local=False, web=True)`, which asked the vendor library - not this repository - to
  run an HTTP stream on the Pi 3 path, outside the token gate, outside the audit trail and outside
  the interlock. A grep for `BaseHTTPRequestHandler` could never find it, because the listener lives
  in `vilib`. The argument is now `web=False`: the module republishes `Vilib.img` as `vision_frame`,
  which is what `services/camera.py` reads, so the stream had no consumer here. `local` stays
  `False` - a preview window needs a display a headless runtime does not have, and the capture
  thread `camera_start` owns does not depend on it. `tests/test_no_legacy_http.py` gains a
  source-level guard for the one surface an AST scan cannot reach. What `vilib` does with
  `web=False` is unobservable from the workstation; confirming it on the Pi belongs to the #26
  checklist.
- **The control plane says where it is** (#38): nothing advertised the device, so every client needed
  a hand-entered IP that DHCP could change on the next lease. `services/discovery.py` publishes one
  mDNS record - `houndmind._houndmind._tcp.local`, a `_houndmind._tcp` service with the host, the
  port and a TXT payload of `api_version`/`min_client`/`scheme` - announces it three times, answers
  a query that names it, and withdraws it with a zero TTL on a clean stop. Standard library only, so
  no dependency: `zeroconf` on every install, `lite` included, is not worth a few dozen lines of DNS
  wire format. The record is public information and is built from `plane.meta()`, which
  `tests/test_discovery.py` asserts; a blocked multicast group costs one log line and nothing else.
  `settings.api.discovery_enabled` (default `true`) and `discovery_name` follow, with
  `docs/INSTALL.md` §*Finding the device by name* and the address fallback.
- **A Pi 4 honours `--preset`** (#29): the installer forced `full` on a Pi 4 whatever the flag said,
  so `--preset lite` attempted dlib/opencv/rtabmap the user had just asked to skip. The choice moved
  into `resolve_preset()`: an explicit flag wins on every board, and `auto` keeps the documented
  defaults (`full` on a Pi 4, `lite` elsewhere). `tests/test_installer_preset.py` covers both halves.
- **The installer stops installing flask** (#30): it was a dependency of the four per-feature HTTP
  servers the control plane replaced, and no module imports it. Gone from `scripts/installer_core.py`,
  `requirements.txt` and the `full` extra - the extra because `tests/test_dependency_mirrors.py`
  holds the mirror and the extra to the same package set. The model downloader beside it stays.
- **One board rule, two callers** (#31): `scripts/installer_core.py` kept its own copy of the
  generation regexes, which is how a Pi 5 was installed as a Pi 4. The table now lives in
  `board/rules.py` - stdlib only - which `board/detect.py` imports and the installer loads by path,
  because it runs before the package exists. `tests/test_board_detect.py` keeps the agreement test
  and adds one that fails if a second table reappears in the installer.
- **`/meta` reports the raw device-tree model** (#32): `board: unknown` said only that detection
  failed. `board_model` carries the string verbatim, next to the `board` kind and the `profile`, and
  a support bundle picks it up for free. `docs/CONTROL_API.md` §2 and `tests/test_api_meta.py` follow.
- **The camera routes declare the scope they enforce** (#39): both rows were `None`, which everywhere
  else in `ROUTES` means "public on purpose", while the handlers demanded `state:read` through a
  single-use ticket. `HANDLER_SCOPE` names the second case, `None` keeps one meaning, and the test
  whitelist that used to excuse the camera is gone - replaced by one that proves removing the guard
  would be caught.
- **An exempt module is visible** (#25): `settings.watchdog.ignore_modules` ships as `["api"]`, so a
  wedged control plane was invisible - the one failure the API cannot report. `state.supervisor`
  now carries `exempt: {name: reason}` for the modules the watchdog deliberately will not restart,
  which keeps "exempt on purpose" distinguishable from "healthy" without restarting anything.

- **The architecture tree names every file** (#68): `docs/ARCHITECTURE.md` §2 had drifted from the
  package it documents. `kernel/actions.py` and `kernel/decisions.py` were missing - the half of the
  issue that matters most, since this file is the map a reader uses to decide where a rule belongs -
  and they were restored in `a5b7698` after the issue was filed. What was still absent is fixed
  here: `calibrate_servos.py`, added to `src/tools/` by #151, plus `main.py` and `__main__.py` at the
  package root. The tree now matches `src/houndmind_ai/` entry for entry, so a missing line is a
  real omission rather than a stale diagram.
- **How to stop and restart the runtime is documented** (#76): `docs/INSTALL.md` §Run showed two ways
  to start HoundMind and nothing about stopping it, while `docs/ROUTINES.md` told a user that a
  routine file edited since boot "appears after a restart" — and no document said how. With no
  service unit in the tree, `sudo systemctl restart houndmind` had nothing to restart. The section
  now carries a stop/restart table: `Ctrl-C`, start again, the health route to prove it is alive,
  where the device token lives and how to use it, the port, and one explicit line that no unit
  ships yet and why that is a decision rather than an omission. The routines doc links to it.
- **The LED strip has a `health` source, and the dead writes around it are gone** (#78, #163):
  `safety/sensor_health.py` published `led_request:health` into a source no configuration could
  name, and `behavior/habituation.py` published `led_request:habituation:<stimulus>` — a key family
  the selector's per-source walk can never address — plus a `telemetry:habituation:<stimulus>`
  snapshot nothing read. `health` is now a real source: in the schema's choices, in the shipped
  default order second after `safety`, with `settings.led.health_mode` choosing its effect. The
  module ships disabled, so the default only bites once a user turns it on — and when they do, the
  request carries a monotonic `until_ts` refreshed every tick while a sensor is unhappy and cleared
  when it recovers, so a reachable health colour cannot hold the strip after the problem is gone.
  Habituation keeps one output, `habituation:<stimulus>:habituated`, which `behavior/attention.py`
  reads. `docs/FEATURES_GUIDE.md` §7 and §15, `tests/test_led_manager.py`,
  `tests/test_sensor_health.py` (2 new cases) and `tests/test_habituation_multi.py` follow.
- **`wait` and `steps` reach the HAL on a posture or expression step** (#69): `config/actions.jsonc`
  declared no parameters for either class, and `hal/motors.py` forwarded a payload only for its
  `_PARAM_ACTIONS` set, so `{"action": "stand", "params": {"wait": true}}` was refused by the
  validator - and would have been dropped in silence had it got through. The canon's own worked
  example (section 8.1: `stand {wait: true}`, `stretch {wait: true}`, `wag_tail {steps: 6}`) could
  not be written down at all. Both halves now exist: the catalog declares `wait` for posture and
  expression (plus `steps` on `wag tail`), and the motor module forwards any step whose parameters
  are a subset of the three vendor knobs `speed`/`steps`/`wait`, which `hal/vendor.py::_direct`
  honours for every servo action - so the module keeps no second copy of the catalog to drift
  away from. A step that asks to wait now runs on the motor worker, because blocking on a pose is
  exactly what that worker is for. `tests/test_motor_params.py` (4 cases) plus
  `tests/test_routine.py`, the routine fixtures and `docs/ROUTINES.md` follow the change.
- **A refused routine start is the POST's own `409`** (#72): `POST /api/v1/routines/{id}/run`
  answered `202` before the runner ever saw the request, and the runner wrote its refusal into a
  `routine_rejection` context key nothing read - so a start it declined left the client holding an
  acceptance it could not cancel. The request now carries a `threading.Event` and a `refusal` slot;
  the runner answers on the request and the route waits for it in an executor (the same reason
  `submit()` waits that way), returning `409` with the runner's reason. `routine_rejection` is gone,
  and `services/api.py` covers the wait with a 0.5 s bound, which is two ticks of the shipped loop.
  `docs/CONTROL_API.md` §3 states both answers; `tests/test_api_routines.py` adds the refused start
  and the unanswered one, `tests/test_routine_runner.py` reads the answer off the request.
- **A routine run is stamped from the loop's clock** (#73): `RoutineRun.started_at` came from
  `time.time()` while everything a client compares it against is monotonic - the snapshot's `ts` is
  the loop clock - so `ts - started_at` produced a number in the region of 1.7 billion. The runner
  now stamps `time.monotonic()`, which makes the subtraction correct and removes the caveat
  `docs/CONTROL_API.md` §4 had to carry: `started_at` is a duration, not a wall-clock moment.
  `tests/test_routine_runner.py` asserts the stamp sits between two `time.monotonic()` readings and
  is decades away from the wall clock.
- **`nav.confidence` is a number the navigator measured** (#51): `services/state.py` read a
  `confidence` key the producer never wrote, so the field was `null` on every tick on every profile
  - indistinguishable from a build that does not report confidence at all, and it made the
  `confidence` field of the decision record (#44) permanently null too. `navigation/obstacle_avoidance.py`
  already computed the share of its confirm window that agreed on a direction and then dropped it;
  the value now travels with the decision, is `null` only on the paths that decided without a scan,
  and stays distinct from `score` (a ranking value, not a probability). `docs/CONTROL_API.md` §4
  documents the two fields; `tests/test_navigation_confidence.py` (6 cases) pins the measurement and
  both `null` cases.
- **The unused `publish_event_threadsafe` is gone** (#53): `services/stream.py` grew a second
  publish entry point for "another thread (the decision loop)" and never called it - a search of
  `src/`, `tests/` and `docs/` found the definition and nothing else. Left in place it documented
  an intent the code does not have, and read as the safe choice for a module `tick`, which runs on
  the decision thread and would have interleaved with the pump's own writes. The pump is now the
  one stated publish path (`docs/CONTROL_API.md` §5), the dead `_loop` attribute went with it, and
  the `decision` event of #44 already ships that way.
- **An injected `IntentBoard` is no longer replaced** (#58): `act/gateway.py` chose its board with
  `board or IntentBoard(...)`, and `IntentBoard` defines `__len__` - so a caller that passed a
  freshly built, still-empty board had it silently discarded and went on publishing into one
  nobody read. The gateway now tests `is None`. Producers read the board from the context, so no
  device was affected; the trap was a test or a replay tool that holds its own reference and looks
  green. `tests/test_gateway.py` asserts the identity instead of the ring, which is the check the
  old one could not make.
- **The `identity_guard` CI job is removed**: it failed any push or pull request whose commits were
  authored by an account other than the project's own, and it was one of the four required checks on
  `main`. The job and its required status context are both gone, so three job definitions and three
  required contexts remain (`Lint and Test (3.11)`, `Type checks (mypy) (3.11)`, `Packaging build`).
  The Dependabot exemption from #138 existed only so that job would not block a bump pull request,
  and left with it; `.github/dependabot.yml` and its test stay. The authorship rule itself is still
  checked locally - `check_rules.py` W6 warns over the unpushed range, `--audit-history` reports the
  published history, and `.githooks/pre-push` stops a foreign author before the push.
- **One producer for `energy_level`** (#85): the behaviour module and `optional/energy_emotion.py` each
  decayed the same number, applied the same boosts and clamped to the same bounds, under two different
  switches. With both on, the reading decayed twice per tick and the boosts stacked, so the rate
  depended on module order; with one on, the value was whichever ran last. The behaviour module is now
  the only writer - `settings.energy.enabled` is the switch, a stimulus an emotion model does not need
  cannot stall it, and the `boost_obstacle` term moved with it so nothing was lost. `energy_emotion`
  became the consumer it already half was: it derives `energy_speed_hint`, `emotion_state` and the LED
  request from the reading, and with no reading it publishes nothing and says once that
  `settings.energy.enabled` is what produces one. Four new cases in `tests/test_energy_state.py`,
  including "both switched on, one decay per tick"; `config/settings.jsonc` and
  `docs/FEATURES_GUIDE.md` now name the single owner.
- **`led_priority` is gone instead of honoured** (#87): four producers stamped `request["priority"]`
  from their own section's `led_priority` int, and the selector never read it - it walks
  `settings.led.priority` and takes the first live request, so the strip was decided by list order
  while four schema-validated knobs changed nothing. Honouring the ints would have let a mis-set
  `emotion.led_priority: 100` outrank safety, which is the one ordering the contract promises, so the
  four keys and the four reads are removed rather than wired up: the list stays the single lever, as
  the LED manager's own tests already pinned. `config/settings.jsonc`, the schema, and
  `docs/FEATURES_GUIDE.md` section 15 now say so; a config that still carries `led_priority` under
  `safety`, `navigation`, `attention` or `emotion` is reported as an unknown key at load, which is the
  point - it was only ever inert, and now the loader says so.
- **One owner for the cue warning** (#90): the FSM warned about every entry cue missing from the
  advisory `behavior.cue_sounds` list and played it anyway, which was the only signal available when
  it was written. Once the HAL learned to name a sound the vendor cannot find, that second opinion
  became the weaker of two: a custom build with its own effects got a `WARNING` on a healthy device,
  and a genuine typo was reported twice in two wordings. The FSM check is gone - it could only guess -
  and the HAL's report stands alone. `behavior.cue_sounds` stays as documentation of a stock build,
  `config/settings.jsonc` and the schema comment say so, and
  `tests/test_behavior_lifelike.py` now asserts the silence.
- **The Pi 3 vision path publishes frames** (#98): `optional/vision.py` started Vilib, published
  `{"status": "ready"}` and stopped there, so `vision_frame` stayed `None` and every detector behind
  it - `face_recognition`, `semantic_labeler`, and the occupancy `perception` derives from faces - was
  blind for the whole run while both modules reported healthy. The module now republishes the frame
  `Vilib.img` already holds as `vision_frame` + `vision_frame_ts`, once per new frame, which is the
  same contract `vision_pi4.py` publishes, so a consumer cannot tell the paths apart and occupancy can
  still age a frozen camera. `vision_status` becomes `{status, backend, frames}` for both paths; a
  build whose Vilib exposes no frame answers `frames: false` with a `reason` and keeps acting as a
  viewfinder instead of claiming to feed detectors. New `tests/test_optional_vision.py` (4 cases,
  `vilib` stood in through `sys.modules`), `docs/FEATURES_GUIDE.md` sections 17 and 20, and the
  context-key table in `docs/HOUNDMIND_PROGRAMMING_GUIDE.md`. `Vilib.img` is upstream behaviour read
  from SunFounder's own examples, not a device observation: the Pi 3 run is still the evidence this
  needs.
- **A face can be enrolled over the API** (#103): `GET /api/v1/people` reported a roster that nothing
  a client could reach could populate - enrolment existed only as a runtime-context command, so the
  one admin-scoped surface in the API could be read and never actioned. New `POST /api/v1/people`
  (`admin`) takes `{"name": ...}`, publishes the command the module already reads and answers `202`
  with the id the roster will show. Enrolment needs the next tick and exactly one face in frame, so
  the answer is the state a client polls: `GET /people` gains `last_enroll {name, ok, reason, ts}`,
  and every refusal that used to be a `WARNING` on the device - no frame, two faces, a backend that
  cannot enrol - now reaches the client in the module's own words. `400` for a name that slugs to
  nothing, `503` when identity is not running, and a paired phone still cannot enrol.
  `docs/CONTROL_API.md` section 9 documents the round trip, `docs/FEATURES_GUIDE.md` section 20 the
  route, and `tests/test_api_people.py` grows eight cases.
- **The web app's assets carry the version** (#102): `index.html` loaded `/static/app.js` with no
  version and `add_static` sent no `Cache-Control`, so a browser was free to apply heuristic
  freshness and keep an `app.js` from an older release. Once the camera minted its frames through
  `POST /camera/ticket`, that stale file asked with `?token=`, got a `401`, and the pane reported
  "enable a vision module" - a confident and wrong cause. `GET /` now stamps `?v=<package version>`
  into both asset URLs (`services/api.py::_asset_version`; empty in an uninstalled tree, which is
  simply the old bare path) and `/static/` answers `Cache-Control: no-cache` from one
  `on_response_prepare` hook, so a returning browser revalidates instead of trusting its copy.
  `docs/CONTROL_API.md` states the asset contract and `tests/test_api_routes.py` holds it.
- **Documentation sections are links** (#116): `§N` references were plain text, so a reader had to
  find a numbered section by eye and `docs/README.md`'s promise of one index meant less than it
  looked. 272 of them are anchors now - in-page `[§4](#4-context-keys)` and cross-page
  `[§6](pidog/HARDWARE.md#6-what-lives-on-disk)` - each resolved from its own sentence: a bare `§N`
  means the page it is on, a page named on the line (before or after the number) wins, and the
  heading must exist or the reference is left as text. New `tests/test_docs_anchors.py` holds every
  `#anchor` in `docs/` to a heading. It immediately found five links that were already broken and
  they are fixed here: `FEATURES_GUIDE.md` §27 (its heading had been renamed), the three
  `PIDOG_PROGRAMMING_GUIDE.md` contents links (emoji headings, so the hand-written slugs missed),
  and `QUICKSTART.md` §4. Left alone on purpose, and stated rather than guessed: references that
  name a section by title (`§TLS`, `§profiles`), the ones inside code spans or fences, and
  `CONTROL_API.md`'s "(design §6.4)", which points at a design document that is not in `docs/`.
- **Servo trim has a step of our own** (#142): the only way to *save* a trim was the vendor's
  interactive curses script - outside the HAL, outside the interlock, outside any test - while
  `POST /api/v1/calibration/run` stayed reserved. New `python -m tools.calibrate_servos` prints the
  twelve joints in `SERVO_GROUPS` order with the offset the dog has loaded, takes repeatable
  `--set joint=deg` (clamped to ±20) and writes only with `--apply`, through `DogHAL.apply_offsets`:
  merged over the loaded values, never with the vendor's `reset_list`, so saving a trim does not pose
  the dog. A joint the HAL could not read prints `unread` and is never written; a value that does not
  read back after the save exits 1. There is no interactive preview on purpose - that needs a raw
  per-group angle write, which stays out of the runtime's reach. New
  `tests/test_calibrate_servos.py` (8 cases, fake only, no motion), `docs/TOOLS.md` §12, guide §9/§16,
  and `docs/pidog/HARDWARE.md` §6.1 (the vendor key map, `OFFSET_STEP`, `reset_list`, and why
  `servo_zeroing.py` is not a trim).
- **Action pins are proposed instead of discovered** (#138): `.github/workflows/ci.yml` is the only
  workflow and its `uses:` pins were maintained by hand, so nothing proposed a bump until a GitHub
  runtime deprecation broke a run - the annotation on the broken run was the first signal. New
  `.github/dependabot.yml` asks for weekly, grouped `github-actions` updates, and `identity_guard`
  now passes for a `dependabot[bot]` pull request on `pull_request` events only: those commits cannot
  match a human account, so without the exemption no bump pull request could merge the required
  check. Every human commit stays gated, and `.github/CONTRIBUTING.md` states the exemption.
- **Section 4 of the programming guide now holds the keys modules actually use** (#115): 30 context
  keys were set in the tree and absent from the table every module author reads, among them
  `battery_voltage` (three consumers), `sensor_service`, `energy_level`/`energy_speed_hint`,
  `pose_hint`, `health_high_water`, `device_id`/`board_model` and the optional modules' own
  `*_status` dicts. A half-published contract is worse than an unpublished one: a reader concludes
  the key does not exist and writes a second producer. The keys a module keeps for itself are listed
  in a new "internal bookkeeping - not a contract" subsection instead of being silently missing.
- **The install path matches the range and the vendor set it documents** (#113, #114): both wrappers
  accepted only `python3.10`/`python3.11` and preferred the 3.10 that `pip` refuses, so the first
  command in the guide exited 2 on Trixie (3.13) and silently chose 3.10 on a machine that had both.
  They now probe `python3.13`, `python3.12`, `python3.11` in that order, validate a `PYTHON` override
  against the same range, and use it for the venv-mismatch check too. `--robot-hat-branch` defaults
  to `2.5.x` instead of `v2.0` - every page in `docs/pidog/` is verified against 2.5.x, and the v2.0
  tree has no `robot_hat.device` - and the installer probes `from robot_hat import Robot, Pin,
  Ultrasonic, utils, Music, I2C` after installing it, failing with the missing sub-dependency named
  instead of leaving a dog that cannot stand until the first action fails. `docs/INSTALL.md` clones
  `2.5.x` in both places, `docs/pidog/INDEX.md` and `ROBOTHAT.md` describe a pre-2.5 install instead
  of a guide that contradicts itself, and the `QUICKSTART.md`/`TROUBLESHOOTING.md` notes about the
  wrapper are gone.
- **A device tool's exit code can be trusted** (#109, #111): `tools.hardware_checkup` returned 0
  whether a sensor answered or not, so a scripted verify, a gate and the bench checklist all read a
  dead ultrasonic as a pass. It now exits 1 when any of the four sensors did not answer, prints
  `[checkup] sensors: all answered` or `[checkup] no reading from: <names>`, and keeps 0 for "all
  answered" and 2 for "no dog could be opened"; a failed motion step still only reports on stderr.
  `tools.installer_verify` checked for Python 3.10 and merely warned on 3.12+, certifying an
  interpreter `pyproject.toml` refuses and the next `pip install` rejects. Both use the declared range
  now (3.11-3.13); the verifier's copy is held to `scripts/installer_core.py::is_supported_python` and
  to `requires-python` by the new `tests/test_python_support.py`, and `scripts/installer_core.py` no
  longer looks for a verifier under the root `tools/` package that was removed. `docs/TOOLS.md`,
  `docs/HARDWARE_TEST.md`, `docs/QUICKSTART.md` and `docs/TROUBLESHOOTING.md` had recorded all of it
  as known defects and now describe the fixed behaviour.
- **The device token has one owner, and it is the runtime** (#16): `services/auth.py::TokenStore`
  has always written `~/.houndmind/api_token` on first start, but three pages said otherwise —
  `FEATURES_GUIDE.md` claimed the installer pre-created it "(Phase 6)", and that page plus
  `GLOSSARY.md` called it "install-issued". `scripts/installer_core.py` has never referenced the
  file, and it runs steps under `sudo`, so an installer-owned token would land in the wrong home
  or with the wrong owner. `FEATURES_GUIDE.md`, `GLOSSARY.md`, `ARCHITECTURE.md` and
  `HARDWARE_TEST.md` now describe first-start creation, and `tests/test_docs_contract.py` fails if
  the installer claim returns.
- **The checkup is behind the HAL** (#11): `tools/hardware_checkup.py` constructed its own `Pidog()`, so
  the documented device check bypassed the HAL's sensor conditioning, its bus lock and its ownership of
  the dog, could not run against `FakeDogHAL`, and was the last `import pidog` in `src/` outside `hal/`.
  It now opens `PidogHAL` (or an injected `DogHAL`), prints a value only when its validity flag is true
  plus a `[checkup] valid:` verdict line, and issues the motion sequence as `hal.action(...)` in the
  same stand / turn-left / turn-right / head-sweep order behind the same `--skip-motion` gate. New
  `--config` hands `settings.sensors` to the HAL so the readings are the conditioned ones the loop
  sees. `FakeDogHAL.set_sound()` can now express "the sensor answered and heard nothing", which is the
  normal quiet-room state. New `tests/test_hardware_checkup.py` (six cases, fake only, no motion) and
  an AST guard in `tests/test_imports.py` confining `import pidog` to `hal/vendor.py` and
  `optional/voice.py`; `docs/TOOLS.md`, `docs/HARDWARE_TEST.md` and `docs/TROUBLESHOOTING.md` updated.
  Exit codes are unchanged (#109), and the vendor's `-1`/`-2` distance placeholders no longer reach the
  output (#108).
- **Calibration is behind the HAL** (#10): `calibration/workflow.py` read `context["pidog"]`, a raw
  vendor handle `HalModule` published for it alone, so the one workflow that reports user-visible
  servo trim was the one path `FakeDogHAL` could not reach. `DogHAL` gains `read_offsets()` and a
  working `apply_offsets()` — the old helpers called `set_servo_zero` / `get_servo_zero`, which
  `Pidog` does not have, so both directions were silent no-ops on a real dog, `auto_apply_servo_offsets`
  included. Offsets are keyed by joint name in the vendor's list order (`lf_shoulder` … `tail`); a
  write merges over the values already loaded and clamps to ±20 rather than replacing a list with
  zeros, and never passes the vendor's `reset_list` (saving a trim must not pose the dog).
  `context["pidog"]` no longer exists, `calibration/servo_calibration.py` is deleted, and the name
  table lives in `hal/iface.py`. New `tests/test_hal_offsets.py` and
  `tests/test_calibration_workflow.py` cover it on the fake, with no motion. Also: a
  `persist_path` that cannot be created is now logged instead of raising out of the tick. The
  vendor's interactive script is still the only way to *measure* a trim (#142).

- **`docs/` audited end to end**, and seven documents added where a reader had nowhere to go:
  `QUICKSTART.md` (flashed card to running dog, no motion), `REPERTOIRE.md` (all 43 actions with
  class, parameters and buckets — 23 of the names appeared in no page before), `TOOLS.md` (the nine
  device CLIs, their flags, and which can move the dog), `TROUBLESHOOTING.md` (one symptom table
  instead of three competing ones), `GLOSSARY.md`, `SECURITY.md` (token, scopes, tickets, TLS,
  exposure checklist, and how to report a vulnerability) and `BOARD.md` (Pi/HAT support, profile
  resolution, and what each profile actually changes). `docs/README.md` gains a Look-ups table and
  `README.md` gains rows for the hardware test, routines and the new pages.
- **Corrected against the tree**: `settings.habituation.led_color` and `led_priority` were documented
  but exist in no schema and no module — copying them was a load-time error. The vision inference
  scheduler, `preprocessing.normalize` and `preprocessing.mean`/`std` were documented as on and
  ImageNet-normalised while the file ships them off and identity. `loop.tick_hz` is `5` in the base
  file and `10` only through the `pi4`/`pi5` profiles. The README feature table said Calibration was
  enabled (it is `false`) and omitted Habituation and Energy & Emotion; `LOGGING.md` cited
  `services/api.py:210` for `/support-bundle`; `ARCHITECTURE.md` §2 was missing six modules. The
  habituation section now also records that the LED priority list cannot address its namespaced
  request ([#78](https://github.com/seven-lynx/HoundMind/issues/78)).
- **Motion safety in the front door**: `README.md` recommended `python -m tools.hardware_checkup`
  first and mentioned `--skip-motion` second. Left off, that flag is a motion run — it stands the dog,
  turns it both ways and sweeps its head. The read-only form is now the one shown.
- **Rendering**: two reference pages had language-tagged fences inside open blocks
  (`pidog/API-REFERENCE.md` §3 and `pidog/PIDOG-EXPRESSION.md` §2), which rendered their headings as
  code; `INSTALL.md` had a prose line trapped inside a bash block; `LOGGING.md` had no headings at
  all. Fences close, headings exist, and `LOGGING.md` says plainly that the decision JSONL is off by
  default so nobody hunts for a file that is not written.
- **Navigation**: a `## Contents` block on the six longest pages, anchor links in them, and the 249
  `§` references are at least reachable through the page's own contents. `docs/pidog/PATTERNS.md` no
  longer cites three gitignored `.clinerules/` files.
- **`tests/test_docs_contract.py`** holds all of the above from here: a page must declare a `Status:`
  header and appear in an index, its relative links must resolve, its fences must close, it must not
  cite a local-only path, and every `settings.<section>.<field>` it names must exist in
  `config/settings.jsonc` or the schema.
- **Deleted `RELEASE.md`** (fixes #110). It listed the smoke test four times with three different paths
  (two of them wrong), used `v0.1.0` as the tag example against a `vYYYY.MM.DD` scheme, and omitted
  the three-file version bump and the changelog section. The release procedure lives in the phase plan
  and `CHANGELOG.md`; a second, wrong copy is worse than none.
- **Note:** `scripts/install_houndmind.sh` and `.ps1` still accept only `python3.10`/`3.11` and
  prefer 3.10, while `installer_core.py` and `docs/INSTALL.md` support 3.11–3.13 — so a Trixie image
  fails at the first command. Documented as a known defect in `docs/QUICKSTART.md` §4 and
  `docs/TROUBLESHOOTING.md`, not fixed here: it is an installer change, not a doc change.
- **`DELETE /api/v1/people/{id}`** (`admin`): forgets one person — the embeddings, the reference images
  and the trained model, not just the name, because an LBPH model built from images you deleted still
  recognises the person. A `404` on a second call, never a silent success; `503` when no identity module
  is running. `id` is matched by slug against every raw name, so two enrolments that slug alike are one
  delete. With the last person gone the model is removed and LBPH is left untrained: faces are still
  detected, nobody is named. This is the design's *"Deletable"* requirement — see `docs/CONTROL_API.md`
  §9, which also states plainly that thumbnails do not exist and are therefore not removed.
- **Face data moved to `~/.houndmind/face/`** (fixes #104): `settings.face_recognition`'s
  `embeddings_path` and the three `lbph` paths were inside the install tree, where the service user may
  not be able to write and a reinstall takes enrolled people with it. `_resolve_path` now expands `~`
  the way `PlaceStore` does. Notes: an existing `data/face_*` directory is **not** migrated and is no
  longer read — identity has never shipped enabled, so remove it by hand or re-enrol.
- **An identity mutation is safe across threads**: the control plane runs on its own thread
  (`services/module.py:73`), so `optional/face_recognition.py` takes one lock to keep
  `_known_names`/`_known_embeddings` a consistent pair for the detector and to make a forget atomic
  against a frame in flight. Reads snapshot under the lock and never hold it across dlib or cv2.
- **`GET /api/v1/people`** (`admin`): who the dog has been taught, as `[{id, name}]` where `id` is the
  slug of the name — the rule places already follow, so two enrollments under one name are one person.
  Nothing biometric is in the response: no embedding, no dataset image, no box, only the `path` of the
  file the identities live in. `admin` rather than `state:read` because an enrolled face is biometric
  data, and `/meta` deliberately does not advertise the roster since it is unauthenticated. Identity
  ships disabled, so the answer while it is off is `identity.reason` — the module's own
  `disabled_reason` when it has one — and not an empty roster to be misread as "nobody is enrolled".
  `optional/face_recognition.py` publishes it (`identity_roster`) from whichever backend holds the
  names: dlib from its embeddings, OpenCV from its LBPH label map. Enrolment is still a runtime
  command, not a route — filed as #103.
- **The camera takes a ticket, not the device token** (`#18`): `POST /api/v1/camera/ticket` mints a
  single-use, 60-second ticket that `/camera/stream` and `/camera/snapshot` accept as `?ticket=`, and
  `?token=` on those two routes is refused with a `401` that names the replacement. The ticket grants
  `state:read` on one frame and cannot be used as a bearer token anywhere else, so a URL that leaks
  from browser history or an access log no longer carries the credential for `move` and `config`. The
  bundled web app mints one when it starts the stream. **Breaking** for any client that built the old
  URL by hand; clients that set headers are unaffected.
- **TLS is optional, and off** (`#18`): `settings.api.tls_enabled` serves HTTPS on the same port with a
  self-signed certificate generated on first start (hostname plus every local address, 10 years, key
  `0600`, generated only while the feature is already on). `services/tls.py` builds the
  `SSLContext` and shells to `openssl` rather than taking a new dependency; a missing binary or an
  unreadable pair disables the control plane with a message naming the cause instead of failing the
  runtime, so the dog keeps walking without an API. Each client trusts the certificate once —
  `docs/INSTALL.md` §*TLS* has the browser, phone and `curl` steps, and says plainly that an Android
  client rejects a self-signed certificate until it carries its own trust configuration.
  `GET /api/v1/meta` now reports `scheme`.
- **The control plane's exposure is written down** (`#18`): it speaks plaintext HTTP on port 8420, so
  the device token, every command and every camera frame cross the LAN in the clear, and the MJPEG
  route accepts that token in a query string. `docs/CONTROL_API.md` §1, `docs/FEATURES_GUIDE.md` §26
  and the `settings.api.host` comment now say so, and name the three workarounds that exist today:
  `host: "127.0.0.1"` plus an SSH tunnel, a firewall rule, or a TLS-terminating reverse proxy.
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
- **A missing sound is no longer silent.** The vendor returns `False` for a name that is not in its
  `sounds/` directory and the adapter discarded it, so a typo'd effect and a working one looked
  identical from every surface — `sound()` and `speak()` return `None` either way. The HAL now warns
  once per name (`#81`).
- **Places** (`kernel/place.py`, `kernel/place_store.py`): the named poses a dog can be asked to go
  to. A place is a heading and a distance from a named anchor, with a confidence, a timestamp and a
  visit count — polar, because that is the pose this stack can produce and use. They live in one JSON
  file at `settings.places.path` (`~/.houndmind/places.json`), and loading quarantines entry by entry:
  one bad place does not cost the others, and a write over a partly-refused file copies the previous
  contents to `<path>.bak` first.
- **A dog can now walk to a place.** `navigation/place_navigator.py` turns a `place_request` into
  ordinary motion — orient to the place's heading, then advance its distance one accepted `forward`
  at a time — and stops on arrival, which is the one moment a trip writes: `visits + 1` and a bounded
  confidence nudge (`Place.after_visit`, `PlaceStore.record_visit`). `Source.PLACE = 17` is a slot of
  its own, under `navigation` (20) so an obstacle always wins the tick and over `routine` (15) so a
  goal beats a script; two producers were never put in one slot. Distance is dead reckoning —
  `settings.places.step_cm` per accepted command — because nothing measures travel, and the request
  must confirm the dog is at the anchor (`at_anchor: true`) because nothing can verify that pose.
  No route yet: `POST /api/v1/places` and the rest are the next segment.
- **Occupancy** (`perception/fusion.py`, `behavior/fsm.py`): the fused snapshot now answers "is
  somebody in front of the dog?" with `occupancy`, `occupancy_valid` and `occupancy_frames`, read from
  the `faces` payload a detector publishes. No detector, no frame and a stale frame all read as
  *unknown* — never as an empty room — because the failure that matters is a dropped frame talking
  the dog into believing it is alone. Claiming presence needs `settings.perception.occupancy.min_frames`
  consecutive frames and dropping it needs `release_frames`, so a blink does not flap it. Behaviour
  turns a valid reading into a bias on the `interact` weight in the autonomy draw, decaying over
  `social_decay_s`. It ships dark: `modules.face_recognition` is still `enabled: false`, so with the
  shipped config occupancy is unknown and the bias is inert — enabling presence is a config change,
  not a consequence of updating.
- **A place has an HTTP surface** (`P4 PL5`): `GET /api/v1/places` lists the catalogue and the walk in
  progress, `POST` creates one, `DELETE /{id}` forgets one by id or name, and
  `POST /{id}/go` asks the dog to walk there — which closes a gap that had no entry point at all:
  until now the only writer of `place_request` in the tree was a test. Refusals keep the shapes the
  store already produced: a bad body is `400` with `problems[]`, an unknown handle is `404` with a
  `suggestion`, and a second walk while one is in flight is `409`. A JSON `true` is refused where a
  number is required, and a string is never coerced into one.
- **One store, one lock** (`kernel/place_store.py`): `places.json` now has two writers — an arrival on
  the tick thread, a create or delete on the event loop — so `add`, `remove` and `record_visit` hold a
  lock across their read-modify-write pair, and the navigator publishes its store as `place_store` so
  the routes use that instance rather than building a second one over the same file.
- **Identity stays off a Pi 4** (`tests/test_imports.py`): "a Pi 4 run imports no dlib" is now
  structural rather than inspection. An AST guard fails on any module-scope import of `pidog`,
  `robot_hat`, `vilib`, `dlib`, `cv2` and friends in `hal/` or `optional/` — including one hidden
  inside a `try/except`, which is the shape that loads dlib on a Pi and stays invisible on CI — and a
  `sys.modules` check proves that constructing the runtime loads none of them.
- **A missing wheel is a reason, not silence** (`optional/face_recognition.py`): enrolment and
  detection used to `return` on `ImportError` with nothing logged and nothing reported, so a saved face
  could be a file that was never written. Both now `disable("missing dependency: face_recognition …")`.
  The face payload also carries the **frame's own capture time** (`vision_frame_ts`) instead of the
  detector's tick, which is the value `settings.perception.occupancy` measures staleness against — a
  frozen frame ages out now instead of reading as presence for ever.
- The source of that occupancy is the design's missing half, tracked in `#96`: §5.4 promises a drive
  set (energy, curiosity, social) and only the energy *band* ever landed, so `social` here is a bias
  on an existing weight table rather than a drive.
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
- `behavior.state_expressions`: one expression per state, played **once when the FSM enters it**
  rather than every tick — a head tilt on `alert`, a tail wag on `play`. The beat is applied after the
  cooldown and micro-idle blocks, which both rewrite the tick's action, so entering `idle` could
  otherwise be swallowed by micro-idle (it ships enabled). It is refused with one warning when the
  action is one the repertoire cannot classify, or when it is `locomotion` — the table is not a
  second way to walk the dog — and it is skipped when the state's own action for that tick is a step.
  A misspelled state or entry key is a load-time error, and a state left out has no beat.
- `behavior.state_expressions.<state>.sound`: a state entry can name a sound effect, played on the same
  tick as the beat. The cue **rides the entry command** rather than taking an intent slot of its own,
  so it costs neither the beat nor the step it rides — the gateway resolves one winner per tick, and a
  cue on its own source would have taken that tick. `hal_motors` plays it once per command, strips it
  before the vendor call, and excludes it from the action fingerprint, so a cue can never turn a
  repeat into a second step. `behavior.cue_volume` (ships `60`) sets the volume, `behavior.cue_sounds`
  lists the vendor's twelve effects — advisory, a name outside it is warned once and still played —
  and `quiet_mode` suppresses cues entirely while the beat keeps playing.
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
- `PATCH /api/v1/config` says what it does: every response now carries `persisted: false`, and
  §2 of the contract states that the change is process-local and that a restart reloads
  `config/settings.jsonc`. An operator who edited `navigation.safe_distance_cm` from a phone and
  restarted the service used to find the old value back with nothing having warned them (#128).
- `/state` carries four blocks it had the data for and never published: `safety` (`active`,
  `emergency_stop`), `nav.heading_calibrated`, `health.high_water`, and `perf` — the loop's
  `tick_hz_actual`, `tick_ms`, `tick_overrun_ms` and `loop_delay_ms`, which `core/runtime.py` was
  computing every tick and dropping on the floor (#124, #125). The dashboard gains a Loop readout
  and `docs/CONTROL_API.md` §4 documents all four, including which are `null` before the first tick.
- Idle is no longer a constant: `behavior/library.py` draws from the whole bucket with a recency weight
  instead of returning `idle_actions[0]` nineteen times in twenty (#37). Three knobs set it —
  `behavior.action_reuse_cooldown_s` (ships `20`: how long an action stays out of its bucket before it
  fades back in), `behavior.idle_variety_interval_s` (ships `8`: how often `idle` may change at all) and
  `behavior.random_idle_chance` (now `0.6`, checked once per interval, `0` = never — it used to mean
  "draw from the bucket instead of returning the first entry", at `0.05`). `action_cooldown_s` is
  untouched: it holds every behaviour change including a reaction to touch, so it was never the right
  pacer for variety.
- The idle pool opens up when the dog is tired: with an `energy_level` reading below
  `behavior.energy_bias_start` (ships `0.5`), the `rest` actions join `idle` and outrank it, saturating
  at `autonomy_rest_energy_max` (0.35) — `doze off` and `nod lethargy` become reachable while idle,
  where before they needed autonomy to switch the state. Inert with no reading, with the band at `0`,
  and above the band. No high-energy mirror: `idle` and `play` share no action, so it would be config
  that does nothing.
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
- `PATCH /api/v1/config` stored any value for a live key without running the schema, so
  `{"led.brightness": "high"}` answered `200` and then made `led_manager.tick` raise on every tick
  for the life of the process — the module reported `failed` and no restart cleared it, because the
  bad value stayed in the settings dict (#123). The write is validated against the same section spec
  a config file is loaded against (`validate_settings_section`), a refusal is a `400` carrying
  `invalid[].problems[]` and stores nothing, and `led_manager` reads its brightness through
  `_safe_float` so a hand-edited file cannot do it either.
- A navigation retreat ran once per command and outside the interlock: `obstacle_avoidance` wrote
  `navigation_followup` and nothing retracted it, so `hal_motors` re-ran the same backward-and-turn
  after **every** later command, inline on the 5 Hz loop (the closed-loop turn waits up to
  `orientation.turn_timeout_s`) and past the gateway, the command TTL and every interlock veto
  (#120). The key is retracted as soon as the followup has been handed over, a payload older than
  `movement.followup_ttl_s` (ships `1.0`) is dropped instead of run late, and the sequence travels
  with its step on the motor worker. Routing retreats through the intent board so the interlock
  judges each step is the remaining half, tracked on #26.
- The battery feed was empty end to end: `PidogHAL.read` never filled `SensorSnapshot.battery_v`,
  `SensorReading` had no field to carry it, and nothing published `battery_voltage`, so the
  interlock's low-voltage veto (6.4 V) and the `battery` section of `behavior` were both unreachable
  on hardware while `ARCHITECTURE`, `CONTROL_API` and `FEATURES_GUIDE` all promised them (#119).
  `hal/vendor.py` reads `Pidog.get_battery_voltage` on its own cadence (`sensors.battery_poll_s`,
  ships `2.0`; the read is an ADC transaction on the servo bus), the value survives to `/state` and
  to both consumers, and a reading outside 3-60 V is reported as **no reading** rather than a flat
  pack, so a disconnected sense line cannot veto every motion for the life of the process.
  `battery_percent` stays unpublished: nothing measures state of charge.
- `runtime_tick` was whitelisted into every JSON record (`core/logging_setup.py:15`) and published
  by nobody — the loop set `tick_ts` and never the tick index, so no production line could be matched
  to a tick while three log tests asserted the field by injecting it themselves (#126). The loop sets
  it beside `tick_ts` now, and `docs/LOGGING.md` lists the four fields every record carries.
- The `requirements*.txt` mirrors had drifted from the extras they mirror: `requirements.txt` was
  missing `pyttsx3` and `vosk`, so an install that followed it got a voice stack that could neither
  speak nor listen, and `requirements-dev.txt` carried a bare `ruff` against the exact pin
  `pyproject.toml` keeps on purpose (#127). `tests/test_dependency_mirrors.py` compares both mirrors
  with `pyproject.toml`, so the next drift fails CI instead of a device install.
- `behavior.autonomy_modes` never left `idle`: `_select_autonomy_mode` handed the mode names to a
  registry keyed by `<mode>_behavior`, so `pick_weighted` found no item, returned `None`, and the
  fallback won on every tick — `patrol`, `explore` and `interact` were unreachable through autonomy,
  and `autonomy_weights` plus the `personality` multipliers were dead config for them (#82).
  `BehaviorRegistry.pick_mode` owns that translation now, and `tests/test_personality_bias.py` — which
  registered the bare mode names, the same mistake in a fixture — uses the real ones.
- An empty behaviour bucket raised `IndexError` inside the tick. It falls back to the FSM's own default
  for that bucket (`stand`, `lie`, `forward`, …) now, and a bucket whose actions are all inside their
  reuse cooldown returns the least recently used one rather than nothing.
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
- `settings.voice_assistant.tts` was shipped, documented and schema-validated, and nothing read it:
  `optional/voice.py::_speak` picked an engine by itself, so `backend: "pyttsx3"` still used the
  robot voice and `enabled: false` still spoke (#8). `_speak` now reads the table - `enabled` gates
  every utterance, `auto` keeps the historical vendor-first order, and an explicit `backend`
  disables the other path. A config with no `tts` table keeps the old order rather than going
  silent. `tests/test_voice_tts.py` (6 cases) drives a `voice_text` through `tick`; FEATURES_GUIDE
  section 19 and the `settings.jsonc` comment state the semantics. Wiring was chosen over deleting
  the keys because both engine paths already existed, and `enabled: false` adding speech is the
  worse of the two failures.

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
- `navigation/local_planner.py` and its three `navigation.*` keys. The module published `local_plan`
  and `mapping_recommendation` and nothing read either; what it computed — `mapping_openings.best_path`
  above a confidence floor, turned into a left/right hint — `obstacle_avoidance._apply_mapping_bias`
  already does on the same data, with a cooldown, a weight and a consumer (#122). It shipped enabled,
  had no test, and carried an unused `_safe_int`, so `/modules` reported a running component that
  produced nothing. Goal-directed walking is `place_navigator`; short-range steering is the avoidance
  module.
- The A* path-planning hook, and the two keys that were supposed to feed it.
  `default_path_planning_hook` read `mapping_state["grid_map"]`, `mapping_state["current_cell"]` and
  `settings["goal"]`; the mapper writes `grid` (a cell map, not a 2-D array), nothing in the tree
  estimates a position, and `goal` was never in the schema — so the hook returned
  `{"path": [], "success": false}` on every tick, its `path_planning` output had no consumer, and
  following `README`/`FEATURES_GUIDE` to set `goal` made the runtime exit at load (#121).
  `path_planning_enabled`, `path_planning_hook`, the `path_planning` context key and the hook are
  gone; `mapping/path_planner.py::astar` stays as a documented library helper with its own tests, and
  goal-directed walking remains `place_navigator`.
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