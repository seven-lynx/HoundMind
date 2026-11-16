# HoundMind Features Guide

Status: **reference** — what each module does, its default, and how to turn it off. Not a tutorial.
Pairs with: `config/settings.jsonc` (every default quoted here), `docs/CONTROL_API.md` (the wire
contract), `docs/ARCHITECTURE.md` (why the modules are shaped this way)

Every feature is configured in `config/settings.jsonc`. Simulation mode is not supported: all features
require real PiDog hardware, and `lite` on a workstation imports cleanly but moves nothing.

> **Rule of thumb:** if a feature is misbehaving, set its module `enabled` to `false` and restart.
> [§29](#29-how-to-disable-any-feature) is the procedure; [§30](#30-troubleshooting) is the list of
> things that usually caused it.

Section numbers are stable references — other files cite them. Append, do not renumber.

---

## Contents

**Always on** — these run on a fresh install.

- [§1 Core Runtime](#1-core-runtime) · [§2 HAL: sensors and motors](#2-hal--sensors--motors) ·
  [§3 Perception](#3-perception) · [§4 Scanning](#4-scanning) ·
  [§5 Navigation and obstacle avoidance](#5-navigation--obstacle-avoidance) · [§6 Mapping](#6-mapping)
- [§7 Behavior](#7-behavior) — the biggest section: buckets, entry beats, cues, routines, personality
- [§8 Attention](#8-attention) · [§14 Event logging](#14-event-logging) ·
  [§15 LED manager](#15-led-manager) · [§26 Control plane](#26-control-plane--rest-websocket-camera-web-app) ·
  [§27 Path planning (A*)](#27-path-planning-a-helper) · [§28 Profiles](#28-profiles)

**Off by default, opt-in** — nothing here is running until you enable it.

- [§9 Safety](#9-safety) · [§10 Watchdog](#10-watchdog) · [§11 Sensor health](#11-sensor-health) ·
  [§12 Health monitor](#12-health-monitor) · [§13 Balance](#13-balance) · [§16 Calibration](#16-calibration)
- [§17 Vision (legacy vilib)](#17-vision-legacy-vilib) · [§18 Voice (legacy input)](#18-voice-legacy-input) ·
  [§19 Voice Assistant (Pi4)](#19-voice-assistant-pi4) ·
  [§20 Face recognition (Pi4)](#20-face-recognition-pi4) ·
  [§21 Pi4 vision feed](#21-pi4-vision-feed-pi4) ·
  [§21a Inference scheduler](#21a-vision-inference-scheduler-pi4) ·
  [§21b Preprocessing](#21b-vision-preprocessing-pi4) ·
  [§22 Semantic labeler](#22-semantic-labeler-pi4) · [§23 SLAM](#23-slam-pi4)

**Removed, and how to migrate** — an old config that still names these fails to load.

- [§24 Telemetry dashboard](#24-telemetry-dashboard--removed) ·
  [§25 WiFi localization](#25-wifi-localization--removed)

**Help**

- [§29 How to disable any feature](#29-how-to-disable-any-feature) ·
  [§30 Troubleshooting](#30-troubleshooting) · [`docs/README.md`](README.md) (the doc index)

---

## 1) Core Runtime
**What it does:** Runs the main loop and coordinates all modules.

**How to use:** Start HoundMind from the install venv. For example, activate the venv and run:

```
source .venv/bin/activate
python -m houndmind_ai
```

Or run directly with the venv Python: `.venv/bin/python -m houndmind_ai`.

**How to disable:** Not applicable (core runtime is always required).

---

## 2) HAL — Sensors & Motors
### HAL (`modules.hal`)
**What it does:** Opens the dog and publishes it as the runtime context key `hal`. It is the only
place that imports `pidog`; every other module asks for `hal` and disables itself with a reason
if it is absent. On a workstation or in CI a `FakeDogHAL` is injected instead, so the sensor,
scan, LED, head and posture paths run without hardware.

**Audio and LED primitives:** the HAL owns `sound(name, volume)` (one of the dog's built-in sound
effects), `speak(text, volume)` (the vendor's speech path, so a routine can talk without the optional
`voice` module being enabled) and `rgb(style, color, brightness, bps)`. Audio is dispatched on its own
worker, so a gait never waits for a sound, and `bps` is the LED effect's animation rate — it used to be
dropped, which is why every effect ran at the vendor's default speed. The vendor answers `False` for a
name it cannot find, and the HAL reports that once per name at `WARNING`: before
[#81](https://github.com/seven-lynx/HoundMind/issues/81) a typo'd effect and a working one were
indistinguishable from every surface, because `sound()` returns `None` either way.

**Disable:** `modules.hal.enabled = false` — with it off nothing can move and no sensor is read.

### Sensors (`modules.hal_sensors`)
**What it does:** Polls the HAL at `sensors.poll_hz` and publishes `sensor_reading`, `sensors`,
`sensor_history` and `sensor_health`. The multi-sample distance, debounce, EMA and IMU low-pass
live in the HAL, next to the reads they belong to.

It also publishes `battery_voltage`, which is the key the interlock's low-voltage veto and the
`battery` section of `behavior` both read. The pack is an ADC read on the bus the servos share, so
it is polled at `sensors.battery_poll_s` (ships `2.0`; `0` = every poll) and the last good value is
reported in between. A reading outside 3-60 V is treated as **no reading**, not as a flat pack: a
sense line that is not connected reads near 0 V, and a veto on that would freeze the dog for good.
Nothing measures the pack's state of charge, so `battery_percent` is never published.

**Disable:** `modules.hal_sensors.enabled = false`

### Motors (`modules.hal_motors`)
**What it does:** Executes the one `motion_command` per tick that `motion_gateway` produced after
the interlock, plus the action cooldown, quiet mode, retreat/turn followups and the closed-loop
turn that reads the heading between steps. It performs no vendor call of its own.

A retreat (`navigation_followup`, written by `obstacle_avoidance`) runs **once**, behind the step it
belongs to, on the module's worker rather than the decision loop. It is retracted as soon as it has
been handed over, and one older than `movement.followup_ttl_s` (ships `1.0`) is dropped instead of
executed late: a retreat describes the step that just happened, so a stale one is a wrong step.

**Disable:** `modules.hal_motors.enabled = false`

---

## 3) Perception
**What it does:** Lightweight sensor fusion and obstacle signals.

The fused snapshot is the `perception` context key: `obstacle`, `touch`, `sound`,
`sound_direction`, `distance`, and — since P4 PL3 — occupancy. Every key in it is a measurement, so
every key can fail, and the failed read has to stay distinguishable from a real one.

**Occupancy** answers one question: is somebody in front of the dog? It is read from the `faces`
payload a detector publishes (`modules.face_recognition`, `opencv`/Haar backend — presence, no
biometrics), and it is a *fact*, not a mood: behaviour turns it into a bias, not the other way round.

| Key | Default | Meaning |
|---|---|---|
| `settings.perception.occupancy.max_age_s` | `1.0` | A frame older than this says nothing about now. |
| `settings.perception.occupancy.min_frames` | `3` | Consecutive frames needed to claim somebody is there. |
| `settings.perception.occupancy.release_frames` | `5` | Consecutive empty frames needed to drop the claim. |

`perception` carries it as `occupancy` (`true`/`false`/`null`), `occupancy_valid` and
`occupancy_frames`. Three of those are unknowns on purpose: **no detector, no frame, and a stale
frame all read `occupancy: null` with `occupancy_valid: false`**. A dropped frame is never an empty
room, and an empty room from an unknown start is believed at once, because claiming nobody is there
is not a claim about a person.

**This ships dark.** `modules.face_recognition` is `enabled: false`, so with the shipped config
occupancy is always unknown and the bias below does nothing. Turning presence on is a config change
with its own install cost, not a consequence of the update.

**Social bias** (`settings.behavior`, [§7](#7-behavior)): while occupancy is valid and true, the `interact` weight in
the autonomy draw is multiplied by `social_bias_peak` beside `personality.sociability`, and it decays
over `social_decay_s` when the sight is lost. Only a mode the table already offers can be biased —
`autonomy_modes` has to list `interact`, which the shipped config does.

| Key | Default | Meaning |
|---|---|---|
| `settings.behavior.social_bias_enabled` | `true` | `false` leaves the weight table exactly as it was. |
| `settings.behavior.social_bias_peak` | `2.5` | Multiplier on `interact` at full presence. |
| `settings.behavior.social_decay_s` | `5.0` | How long the interest survives without a reading. |

**Disable:** `modules.perception.enabled = false`

---

## 4) Scanning
**What it does:** Moves head and performs scans for navigation. The scan runs on an owned
background worker (`kernel/scheduler.py`), so a sweep never blocks the decision loop; while one
is in flight `scan_in_flight` is true and a second request is dropped rather than queued.
`scan_continuous: true` scans on a timer; `false` scans only while a motion is being executed.
The measured sweep duration is published as `scan_duration_s`, which the watchdog uses to decide
what "stale" means for this board - and the navigator reads the resulting window from
`scan_stale_after_s`, so a direction is never chosen from a reading the watchdog would not move on
(#22).

**Disable:** `modules.scanning.enabled = false`

---

## 5) Navigation & Obstacle Avoidance
**What it does:** Makes decisions from scans and triggers safe actions.

**Disable:** `modules.navigation.enabled = false`

---

## 6) Mapping
**What it does:** Analyzes scan openings and saves lightweight home-map snapshots.

**Disable:** `modules.mapping.enabled = false`

### Places

A **place** is a named pose the dog can be asked to go to — the kitchen, your bed, the door. Places
are **taught, never inferred**: no scan creates one, because a place the dog invented is a place it
can be confidently wrong about.

| Key | Default | Meaning |
|---|---|---|
| `settings.places.path` | `~/.houndmind/places.json` | One JSON file holding every place. `~` is expanded at startup; a missing file is an empty list, not an error, and nothing creates it on a read. |
| `settings.places.anchor` | `sonar_baseline` | The anchor this run navigates in. A place taught against a different one is refused by name instead of being walked on a stale vector. |
| `settings.places.tolerance_cm` | `15` | Arriving inside this many cm of the stored distance counts as arrived. |
| `settings.places.turn_tolerance_deg` | `8` | How far off the heading the dog may be and still count as facing the place. |
| `settings.places.step_cm` | `25` | Dead reckoning: how far one accepted `forward` is believed to carry the dog. Nothing measures travel, so this is a guess until it is measured on the device. |
| `settings.places.timeout_s` | `120` | Give up after this long. `0` means never. |
| `settings.places.confidence_step` | `0.1` | How much one arrival raises a place's confidence, and one failed approach lowers it. |

Each place is a pose **polar from an anchor** — `heading_deg` and `distance_cm` from a named
`anchor` — with a `confidence` (`null` when nobody has confirmed it yet), `created_ts` and `visits`.
That is what this dog can actually measure: it has a heading and a sonar, and no map coordinates to
spare. Reaching a place is a local sequence (turn to the heading, walk, re-scan, correct), not a
global path plan, which is why the stored pose is a bearing and a range.

- **One bad entry never costs the others.** A heading outside −180..180 or an unreadable number is
  refused by index (`places[2].distance_cm`) and the rest of the file still loads. A file that is not
  JSON at all is one refusal, and its bytes are left untouched for the user to fix.
- **A write cannot destroy a typo.** Before writing over a file that had refused entries, the
  previous contents are copied to `<path>.bak`, and the write itself is a temporary file plus a
  rename, so a power cut leaves the old file or the new one and never half of either.
- **Ids are stable.** A place's id is a slug of its name at creation (`The Kitchen` → `the_kitchen`)
  and never changes, so renaming the display name does not break a client that stored the id. Two
  names that differ only in case or spacing are the same place to a person, and the second is
  refused.
- **Going there is one intent at a time.** `navigation/place_navigator.py` turns a request into
  ordinary motion: it orients to `heading_deg`, walks `distance_cm` one accepted `forward` at a
  time, and stops on arrival. Every step passes the gateway, the interlock and the obstacle stop
  exactly as a command from a hand does, and the intent's priority is **17** — under `navigation`
  (20), so an obstacle always wins the tick, and over `routine` (15), so a goal beats a script.
- **The anchor is a precondition.** A stored distance was measured from the pose the dog stood at
  when the place was taught, and nothing at this tier can verify that pose, so the request has to
  say the dog is there (`at_anchor: true`). Without it, or when the place was taught against another
  anchor, the navigator refuses and names the reason instead of walking a vector it cannot confirm.
- **Arrival is dead reckoning, and it is written down as such.** Each accepted `forward` counts
  `step_cm`; arriving inside `tolerance_cm` of the distance counts as a visit, which is the one write
  a trip makes (`visits + 1`, confidence up by `confidence_step`). A goal that cannot get there — a
  wall, a veto, a timer — ends as `abandoned` with its reason and, if a confidence was ever measured,
  a decay instead of a rise.
- **The HTTP surface is `/api/v1/places`** (`docs/CONTROL_API.md` [§8](CONTROL_API.md#8-places)): `GET` lists the catalogue and
  the walk in progress, `POST` creates one (a refused body comes back as `400` with `problems[]`),
  `DELETE /{id}` forgets one by id or name, and `POST /{id}/go` asks for a walk. The last one writes
  `place_request` for the next tick — the route asks, the navigator decides — so a client that gets
  `202` should read `goal` from `GET /places` for the navigator's answer, which is also where
  `anchor_mismatch` and the other refusals appear. All four answer `503` when
  `modules.place_navigator.enabled` is off, because nothing then owns the file.
- **One store, one lock.** The navigator builds the store and publishes it as the `place_store`
  context key; the routes write through that instance. Two writers touch `places.json` — an arrival on
  the tick thread, a create or delete on the event loop — so `add`, `remove` and `record_visit` hold a
  lock across their read-modify-write pair (`kernel/place_store.py`). A second store over the same
  path would be a second writer holding a second lock.

---

## 7) Behavior
**What it does:** Picks actions based on state and rules.

### The action repertoire and its classes

Every action belongs to a **class**, and the class — not the name — decides which safety limits apply
to it. The classes are data in `config/actions.jsonc` (`actions`), so a user who adds an action
classifies it in the same file they added it to:

| Class | Tilt latch | Obstacle stop | Battery floor | Deadman | Examples |
|---|---|---|---|---|---|
| `locomotion` | yes | forward family | yes | yes | `forward`, `backward`, `turn_left`, `trot` |
| `posture` | yes | no | yes | yes | `sit`, `lie`, `stretch`, `high five` |
| `expression` | yes | no | yes | yes | `wag_tail`, `bark`, `shake_head`, `pant` |
| `non_motion` | no | no | no | yes | `rgb`, `sound`, `speak`, `head`, `rpy` |

- Every action a catalog bucket lists must be classified, or the runtime refuses to start and names
  the action it could not place. That is deliberate: an action the behavior module can pick and the
  interlock has to refuse is a bug, not a configuration style.
- `forward`, `backward`, `turn_left` and `turn_right` are `locomotion` in every repertoire; the file
  cannot weaken one, so the obstacle stop cannot be switched off by editing the catalog.
- `non_motion` is never refused for a tilt, a flat battery or something 8 cm ahead. It still expires
  like everything else, so a stale LED request does not run late.
- **Adding your own action:** add it to a bucket **and** to the `actions` table with a class, then
  restart. It becomes commandable over `POST /api/v1/command`, and `GET /api/v1/repertoire` lists
  what this device can actually run, with each action's class and parameters.

### Entry beats

Each FSM state may name **one expression** to play when the dog enters it — a head tilt on `alert`, a
tail wag on `play` — in `settings.behavior.state_expressions`:

```jsonc
"state_expressions": {
  "alert": { "action": "head_up_down" },
  "play":  { "action": "wag tail" }
}
```

- It fires **once, on the transition**, never every tick, and it wins the entry tick; the state's own
  action resumes on the next one. `behavior.action_cooldown_s` decides how long the beat is held (it
  ships `0.0`, so the beat is one tick and the vendor plays the action once).
- Refused, each with a warning in the log, never silently:
  - an action nothing classifies — a beat is not published on the strength of a spelling;
  - a `locomotion` action — a beat is an expression, not a second way to walk the dog.
- A beat is also **skipped** when the state's action for that tick is itself `locomotion`: the dog
  keeps moving and the beat waits for the next transition. That is why the locomotion states
  (`avoiding`, `patrol`, `explore`) ship with no beat.
- A state left out has no beat. A misspelled state name or entry key is a **load-time error** with a
  suggestion, so a table that could never fire cannot load.
- The beat is an ordinary expression through the gateway: the interlock judges it by its class (tilt
  latch and battery floor), and it is the lowest-ranked intent on the board
  (`Source.BEHAVIOUR = 10`), so a navigator, a routine, a client, the watchdog or the system all
  outrank it.

### Entry cues (the transition sound)

The same table carries a sound: `<state>.sound` names one of the dog's effects, played on the tick the
dog enters the state.

```jsonc
"state_expressions": {
  "alert": { "action": "head_up_down", "sound": "single_bark_1" }
}
```

- It is a **cue on the command**, not an action of its own. The gateway resolves exactly one winner per
  tick, so a cue published as its own intent would take that tick from the beat — and from the step,
  on entry to `patrol` or `explore`. Attached to the entry command, it costs neither: `hal_motors`
  plays it and strips it before anything reaches the vendor.
- A state with **no** beat still gets its cue, and a cue never turns a repeated step into a second
  step — it is excluded from the action fingerprint that decides what counts as a new command.
- `behavior.cue_volume` (0–100, ships `60`) sets the volume, and `quiet_mode` suppresses the cue
  outright; the beat still plays.
- `behavior.cue_sounds` lists the twelve effects a stock PiDog ships
  (`docs/pidog/PIDOG-EXPRESSION.md`). It documents a stock build; nothing validates a cue against it,
  so a custom build's own effects play without a complaint. The question worth asking is whether the
  file exists, and the HAL answers it — once per name, at `WARNING`: `Sound '…' not found in the
  vendor's sounds directory` ([#81](https://github.com/seven-lynx/HoundMind/issues/81)).
- Audio never blocks the loop: `hal.sound` queues onto the HAL's audio thread.

### Choosing an action

Every behaviour bucket (`idle`, `alert`, `avoid`, `play`, `rest`, `patrol`, `explore`, `interact`) is
filled by one **recency-weighted draw** — not by `random.choice`, and no longer by a fixed first entry.

- **Recency.** An action used within `behavior.action_reuse_cooldown_s` (ships `20`) is out of the
  pool; past the window it fades back in from a 5 % weight over one more window. If everything is
  inside its cooldown the least recently used action is returned, so a one-action bucket answers
  instead of hanging, and an empty bucket falls back to the FSM's own default (`stand`, `lie`,
  `forward`, …) instead of raising inside the tick.
- **Pace.** `behavior.idle_variety_interval_s` (ships `8`) is how often `idle` may change its action,
  and `behavior.random_idle_chance` (ships `0.6`, checked once per interval, `0` = never) decides
  whether it does. Both are separate from `action_cooldown_s`, which holds *every* behaviour change
  including a reaction to a touch — raising that one to slow idle down would slow the dog's reflexes
  with it.
- **Autonomy.** `behavior.autonomy_modes` and `autonomy_weights` pick the *mode* every
  `autonomy_interval_s`, and `personality` multiplies those weights (`curiosity` → `explore`,
  `sociability` → `interact`, `activity` → `patrol`/`play`). Modes are registered as
  `<mode>_behavior`; the translation happens in one place, `BehaviorRegistry.pick_mode`.
- **Energy.** When an `energy_level` reading exists (from `settings.energy`, which ships off), a
  reading below `behavior.energy_bias_start` (ships `0.5`)
  lets the `rest` actions join the `idle` pool and outrank it, saturating at
  `autonomy_rest_energy_max` (0.35): a tired dog starts to doze off while idle instead of only once
  autonomy moves it to `rest`. With no reading, `energy_bias_start: 0`, or a reading above the band,
  the draw is exactly the one described above. There is deliberately no high-energy mirror: `idle` and
  `play` share no action, so boosting play actions inside `idle` would be config that does nothing,
  and a refreshed dog reaches the `play` state through autonomy anyway.
- `behavior.behavior_selection_mode: "sequential"` still applies to the idle *behaviour items*
  (`idle_choices`), which is how a test gets a deterministic order.

### Routines and their directory

A routine is a user-authored list of steps, one JSON file per routine. The files sit outside the
tracked tree, so editing one is not a dirty worktree, and a broken file is skipped by name rather
than stopping the runtime.

| Key | Default | What it does |
|---|---|---|
| `settings.routines.dir` | `~/.houndmind/routines` | Directory the routine runner reads and `POST /routines` writes into. `~` is expanded at startup; a missing directory is an empty list, not an error, and it is created only when a routine is written. |

Three routes expose them: `GET /api/v1/routines` lists what the runner loaded and which files it
refused, `POST /api/v1/routines` writes one file judged by that same loader validation
(`?replace=true` to overwrite an existing id), and `POST /api/v1/routines/{id}/run` starts one,
optionally as a rehearsal (`{"dry_run": true}`). All the shapes and status codes are in
`docs/CONTROL_API.md` [§3](CONTROL_API.md#3-commands). A written routine carries
`reload_required: true`: the runner reads the directory once at start, so the new file is playable
after the next start.

The run in progress is also in every state snapshot (`state.routines`, the same object the route calls
`current`) and is pushed as a `routine` event whenever it moves — a new step, a new state, a veto — so
a client that started one follows it without polling, and a client that only watches the socket still
sees it finish.

**The runner (`modules.routine_runner`).** On by default. Each tick it publishes the next step to the
intent board as `Source.ROUTINE`, so the mode gate, the interlock and the obstacle stop decide each
step exactly like a command from a hand — a routine cannot bypass a limit that applies to one. The
first refusal ends the run (`stopped` after `POST /stop`, `refused` on a veto) rather than skipping the
step. Disable the runner and `/api/v1/routines` answers `503`, `/meta` drops `routines` from
`capabilities`, and `state.routines` stays `null`; the rest of the runtime is unaffected. The file
format is `docs/ROUTINES.md`.

**Micro-idle behaviors (lifelike idle):** When enabled, the robot occasionally performs small idle actions (e.g., `"shake head"`, `"wag tail"`, `"stretch"`) to feel more lifelike. These are safe, optional actions that do not affect navigation or safety logic.

**Settings:**
- `settings.behavior.micro_idle_enabled` (default: true)
- `settings.behavior.micro_idle_actions` (list of action names from your action catalog)
- `settings.behavior.micro_idle_interval_s` (minimum seconds between micro-idle actions)
- `settings.behavior.micro_idle_chance` (probability per eligible interval)

**Habituation (suppress repeated stimuli):**
When enabled, habituation reduces repeated reactions to identical stimuli (touch or sound). The `HabituationModule` tracks recent stimulus counts and sets a runtime flag `habituation:<stimulus>:habituated` when the count exceeds the configured threshold. Other modules (for example `AttentionModule`) consult that flag and may suppress reactions while habituated. Habituation automatically recovers after a quiet period.

**Settings (top-level `settings.habituation`):**
- `settings.habituation.enabled` (default: true) — enable/disable habituation module
- `settings.habituation.stimuli` (default: `["sound","touch"]`) — list of stimulus keys to monitor
- `settings.habituation.window_s` (default: 1.0) — window (seconds) used to count repeated events
- `settings.habituation.threshold` (default: 3) — number of events within `window_s` to trigger habituation
- `settings.habituation.recovery_s` (default: 6.0) — quiet period (seconds) to reset habituation

**Output:**
- The flag is the whole output. `habituation:<stimulus>:habituated` is what other modules read
  (`behavior/attention.py` consults it), and it is deliberately the only channel: a habituation is a
  fact about a stimulus, not an expression, so it does not take the LED strip.
- Earlier builds also published an LED request under `led_request:habituation:<stimulus>` and a
  snapshot under `telemetry:habituation:<stimulus>`, and neither had a reader — the LED selector
  walks `settings.led.priority` and can never address a namespaced key family. Both were removed
  ([#78](https://github.com/seven-lynx/HoundMind/issues/78),
  [#163](https://github.com/seven-lynx/HoundMind/issues/163)).

**Disable:** `settings.habituation.enabled = false`. Habituation is the one module with no
`modules.habituation` entry in the shipped config — the runtime constructs it enabled and the
`settings` flag is the switch.

**Energy (internal state)**
The runtime can maintain a lightweight `energy_level` that persists in the runtime context, decays over
time, and increases briefly in response to stimuli (touch, sound, an obstacle). This is an optional
internal state used by autonomy selection (play/rest bias) and by the idle energy band.

**One producer.** `behavior/fsm.py` owns the reading and `settings.energy.enabled` is its switch.
`modules.energy_emotion` is a *consumer*: it derives `energy_speed_hint`, `emotion_state` and an LED
request from the reading, and with `settings.energy.enabled: false` there is nothing to read, so it
publishes nothing and warns once. Two modules used to decay the same number, which made the rate depend
on module order rather than on either config section
([#85](https://github.com/seven-lynx/HoundMind/issues/85)).

**Settings:**
- `settings.energy.enabled` (default: false) — the switch; nothing else produces `energy_level`
- `settings.energy.initial` — starting energy on the first tick
- `settings.energy.decay_per_tick` — amount to reduce energy each tick
- `settings.energy.boost_touch` / `boost_sound` / `boost_obstacle` — per-stimulus boosts
- `settings.energy.speed_slow_threshold` / `speed_fast_threshold` — where `energy_speed_hint` turns

Enable with:

```jsonc
"settings": {
    "energy": { "enabled": true }
}
```

When disabled, `energy_level` is not updated at all, and every consumer behaves as it does with no
reading.

---

### Personality & Behavior Tuning

The runtime provides lightweight personality tuning to bias autonomous behavior selection. This is purely a behavior-level tuning — disabling it will not affect navigation, safety, or core runtime modules.

Where to configure:
- Edit `config/settings.jsonc` and add or modify the `personality` section.

Keys:
- `personality.curiosity` (float): Multiplier applied to exploratory/autonomy selection (default: 0.5).
- `personality.sociability` (float): Multiplier applied to interaction/autonomy selection (default: 0.5).
- `personality.activity` (float): Multiplier applied to patrol/play/autonomy selection (default: 0.5).
- `personality.apply_to_autonomy` (bool): When `true` the personality multipliers bias autonomy mode selection; when `false` personality settings are ignored (default: true).

How to disable personality effects:
- To fully disable personality influence on autonomy selection, set:

```jsonc
"personality": { "apply_to_autonomy": false }
```

Notes:
- The personality feature is implemented in `src/houndmind_ai/behavior/fsm.py` and covered by `tests/test_personality_bias.py`.
- Disabling `personality.apply_to_autonomy` is safe and will not break other functionality; other behavior features (habituation, micro-idle, energy) remain independently configurable.


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
**What it does:** Holds motion when the sensor or scan data it depends on goes stale, and asks
the runtime to restart modules whose heartbeat stopped. Recovery is always **stop and report**:
a stale reading publishes a `stop` command through the same interlock as everything else, it
never poses the dog, and only modules that are enabled *and* started are candidates. Restarts
back off exponentially (`restart_cooldown_s` × `restart_backoff_factor`, capped by
`restart_max_delay_s`) and stop after `max_restarts`; a module that stays up for `healthy_after_s`
earns a fresh budget.

The scan staleness window is the larger of `scan_timeout_s` and 1.5× the measured scan duration,
because a sweep takes seconds and a fixed sub-second window called a healthy scan stale. It is one
rule, in `navigation/scanning.py::scan_freshness_window_s`, and the watchdog publishes the number it
used as `scan_stale_after_s`: the navigator picks a direction from the same reading, so it reads
that key instead of deriving a second window, and applies it to the `scan_service.latest()` fallback
too. `navigation.scan_stale_s` was retired with it — a second knob for one question is how the two
came to disagree about the same timestamp (#22).

**The control plane is exempt, and says so.** `ignore_modules` ships as `["api"]`: restarting the
control plane re-binds the port and drops every connected client, and a restart triggered by a
heartbeat lag looks to a phone exactly like the dog going offline. The cost of that choice is a
blind spot, because the API is the only way anyone sees the dog - so `/state` reports the exemption
in `supervisor.exempt` with its reason. A wedged control plane therefore reads as `exempt`, never
as healthy, and an operator with a client still connected can see it. Anything else in
`ignore_modules` is reported the same way.

**Default:** Enabled (it does nothing unless the dog is asked to move on stale data).

**Disable:** `modules.watchdog.enabled = false`

---

## 11) Sensor Health
**What it does:** Paints a per-sensor staleness badge through `led_request:health`, using the
validity flags the HAL already publishes. It is a display, not a gate: the raw `distance_valid`,
`touch_valid`, `sound_valid`, `imu_valid` and `battery_valid` flags are published whether this module
runs or not, and the interlock reads those, never this.

**Default:** Disabled (`modules.sensor_health.enabled = false`), like the other safety-adjacent
modules. `SensorHealthModule` also starts life outside `main.build_registry`, so enabling it in config
is necessary but not yet sufficient — it must be registered before it ticks.

**Settings** (`settings.sensor_health`): the staleness windows per sensor family and the LED colour
used for the badge.

**Disable:** `modules.sensor_health.enabled = false`

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

### Decision feed (`decision_log`)
**What it does:** Keeps the last decision records in memory for `GET /api/v1/decisions` and the
`decision` socket event, and can mirror them to JSONL. One record per tick — including the ticks
where the dog did nothing, because "did nothing" is also a decision.

**Defaults:** the ring holds `logging.decision_log_max_entries` records (200). The JSONL is
**off** (`logging.decision_log_file_enabled: false`): at 10 Hz it would write about 9 MB an hour,
so turn it on for a post-mortem or a replay run. When on, it rotates to `.1` at
`logging.decision_log_max_mb` — one generation, the same rule as the event log.

**Independent of the event log:** `modules.event_log.enabled: false` does not stop the ring. The
two are separate keys because `/decisions` is a live surface, not a diagnostic.

**Disable:** `modules.decision_log.enabled = false`

**Replay:** `python -m tools.replay_decisions logs/houndmind_decisions.jsonl --check` validates a
recorded file and prints what is in it; the same command without `--check` serves it through the
control plane. See `docs/HOUNDMIND_PROGRAMMING_GUIDE.md` [§16](HOUNDMIND_PROGRAMMING_GUIDE.md#16-developer-commands) — a replay has no touch or sound
reading and cannot accept commands.

---

## 15) LED Manager
**What it does:** Centralized LED priority handling. It picks the highest-priority live request from
`led_request:<source>` and applies it through the HAL's `rgb`, so a colour and its animation rate come
from one place instead of from whichever module wrote last. The order is `settings.led.priority`
(default `["safety", "health", "navigation", "attention", "emotion"]`), and **the order is the
precedence**: the list is walked front to back and the first source with a live request owns the
strip, so `safety` first is a guarantee rather than an accident of the default. Reordering that list
is the one way to override it — put `emotion` ahead of `safety` and an expression does take the
strip. There is deliberately no
second lever: a request is `{mode, color?, bps?, until_ts?}`, and a numeric priority stamped on the
request would be config that loads and decides nothing
([#87](https://github.com/seven-lynx/HoundMind/issues/87)).

**Sources.** One module per slot, and each key is exactly `led_request:<source>`:
`safety/supervisor.py` (`safety`), `safety/sensor_health.py` (`health`, which ships disabled),
`navigation/obstacle_avoidance.py` (`navigation`), `behavior/attention.py` (`attention`) and
`optional/energy_emotion.py` (`emotion`). A producer whose key is not in the list — or that names a
key family rather than one source — is publishing something nothing can select, which is what #78
found and removed.

**Requests can expire.** A request is `{mode, color?, bps?, until_ts?}`. `until_ts` is a deadline on
the runtime's monotonic clock; once it passes, the request stops winning and its key is cleared, so the
next source in the priority list takes the strip. A request with no `until_ts` stands until it is
replaced — that is what every producer in this tree writes, and their behaviour is unchanged. When the
request that owned the strip expires and nothing else is live, the strip returns to
`settings.led.default_color` with `settings.led.idle_mode` (default `breath`), once.

**Rate.** `bps` is the effect's animation rate. A request may carry its own; otherwise
`settings.led.bps` maps a source name to a rate (`{"safety": 4}`). Absent from both, the key is not
sent and the HAL's own default applies — the rate every effect ran at before this existed.

**Disable:** `modules.led_manager.enabled = false`

---

## 16) Calibration
**What it does:** Reports the servo trim the hardware already has (`servo_zero`) and runs the
range/localisation requests (`wall_follow`, `corner_seek`, `landmark_align`). The trim is read
through the HAL (`DogHAL.read_offsets`) and written through `DogHAL.apply_offsets`, clamped to ±20°
and merged over the values already on the dog — nothing here invents an offset, and saving one does
not move the dog. Keys are the joint names in `hal/iface.py::SERVO_GROUPS`.

The read half runs from a config request or from `POST /api/v1/calibration/run`
([`CONTROL_API.md` §10](CONTROL_API.md#10-calibration)), which can only dispatch the four read-only
requests. The write half is the device CLI: `python -m tools.calibrate_servos` prints the trim,
`--set joint=deg` prints what it would write, and only `--apply` saves it.

**Disable:** `modules.calibration.enabled = false`

---

## 17) Vision (legacy vilib)
**What it does:** Uses Vilib for camera output and preview, and republishes the frame Vilib already
holds as `vision_frame` + `vision_frame_ts` — the same two keys [§21](#21-pi4-vision-feed-pi4) publishes,
so a detector does not care which camera path is running. One publish per new frame, not per tick: a
frozen camera has to look frozen to occupancy.

**What it publishes:** `vision_status = {"status": "ready", "backend": "vilib", "frames": true}`. On a
build whose Vilib exposes no frame the same key answers `frames: false` with a `reason`, once, and the
module stays a viewfinder rather than claiming to feed detectors.

**Disable:** `modules.vision.enabled = false`

---

## 18) Voice (legacy input)
**What it does:** Wires the voice subsystem into the runtime. It is the *input* side only — speech
recognition fills `voice_text` / `voice_command`, which `§19` then maps to actions.

**Default:** Disabled. Enable it only after the microphone works at the OS level.

**Enable:**
- `modules.voice.enabled = true`

**Audio dependencies first.** `pyaudio` needs the PortAudio headers and `sounddevice` needs ALSA, so
install the system audio stack before the wheel, then the vendor helper that configures the PiDog's
I2S microphone:

```bash
sudo apt update && sudo apt install -y portaudio19-dev libasound2-dev
sudo bash .cache/houndmind_deps/pidog/i2samp.sh
```

The guided installer can run that helper for you: `bash scripts/install_houndmind.sh --run-i2samp`,
or `RUN_I2SAMP=1 bash scripts/install_houndmind.sh` for a non-interactive run.

**Test it:** start the runtime and check that the module reports ready in the log rather than
`disabled`. A module that could not open the microphone disables itself with a reason — it does not
crash the runtime.

**Troubleshooting:**
- If the mic is missing, the module disables itself and logs why. Fix the device, not the config.
- Confirm the microphone is visible to the OS (`python -m tools.list_audio_devices`) before enabling.
- Voice never reaches the dog over HTTP: there is no port-8091 endpoint. A client drives motion with
  `POST /api/v1/command` (`§26`), through the interlock and the audit log.

**Disable:** `modules.voice.enabled = false`

---

## 19) Voice Assistant (Pi4)
**What it does:** Maps voice text/commands into PiDog actions via `behavior_override`.

**How it works:**
- Provide `voice_text` or `voice_command` in runtime context.
- The module maps phrases to actions using `settings.voice_assistant.command_map`.

**Speech output.** The TTS table is honoured, not decorative: `settings.voice_assistant.tts.enabled`
(ships `false`) is the switch - while it is off the module maps commands and answers questions
silently. `settings.voice_assistant.tts.backend` picks the voice: `auto` tries the PiDog speaker
first and falls back to `pyttsx3`, `pidog` uses only the vendor voice, and `pyttsx3` uses only the
local engine. A named backend never borrows the other one, so a missing vendor speaker is a dropped
answer rather than an unexpected voice. A config with no `tts` table keeps the `auto` order.

**Enable:**
- `modules.voice.enabled = true`
- `settings.voice_assistant.enabled = true`

**Driving it:** there is no `/say` or `/command` HTTP endpoint. The legacy port-8091 server was an
unauthenticated path to `behavior_override`, so it is gone; a client sends
`POST /api/v1/command` ([§26](#26-control-plane--rest-websocket-camera-web-app)), which goes through the interlock and is audited. Speech
recognition (`settings.voice_assistant.stt.enabled`) is the input that replaces it. The
`python -m tools.voice_cli` helper was deleted with the port.

**Disable:**
- `modules.voice.enabled = false` or `settings.voice_assistant.enabled = false`

---

## 20) Face Recognition (Pi4)
**What it does:** Detects faces and optionally recognizes identities. Supports lite (OpenCV) and heavy (face_recognition) backends.

**Enable:**
- `modules.face_recognition.enabled = true`
- `settings.face_recognition.backend = "opencv"` or `"face_recognition"`

**Enrolling a face:** `POST /api/v1/people` with `{"name": "Alice"}` (`admin`, see
[§26](#26-control-plane--rest-websocket-camera-web-app)) answers `202` with the handle to poll; the
outcome is `last_enroll` on `GET /api/v1/people`, which is also where a refusal is reported — the frame
held no face, two faces, or the backend cannot enrol. Underneath, the route publishes the same runtime
command, so a routine step or a tool can do it with no client:

```python
context.set("face_recognition_command", {"action": "enroll", "name": "Alice"})
```

The next tick enrolls against the newest `vision_frame` (it requires exactly one face in frame).
The legacy port-8088 server is gone: `/status` is now `GET /api/v1/modules`, the roster of enrolled
people is `GET /api/v1/people`, and `python -m tools.face_recognition_cli` was deleted with the port.

**It needs a frame, and two modules publish one.** `vision_frame` comes from
[§21](#21-pi4-vision-feed-pi4) on a Pi 4/5 or from [§17](#17-vision-legacy-vilib) on a Pi 3, and both
stamp `vision_frame_ts`, so the detector has something to look at on either board. With neither
running it publishes nothing at all — not "nobody there".

**What it publishes.** `faces` = `{timestamp, backend, detected}`. `timestamp` is the **frame's own
capture time** (`vision_frame_ts` from [§21](#21-pi4-vision-feed-pi4)), falling back to the tick only when a producer does not
stamp its frames. That distinction is load-bearing for [§3](#3-perception)'s occupancy: a frozen frame has to age,
or a dead camera reads as a person standing there for ever.

**A missing wheel is a disabled module with a reason.** The `face_recognition` (dlib) backend needs
a wheel that is not on PyPI; when it is absent the module logs
`missing dependency: face_recognition` into `disabled_reason` instead of failing at enrolment or
reporting an empty room. Nothing is imported at module scope, which
`tests/test_imports.py::test_no_vendor_wheel_is_imported_at_module_scope` enforces.

**Who it knows** — `GET /api/v1/people`, `admin` scope, ids and names only:
`{"identity": {"enabled", "backend", "reason"}, "path", "people": [{"id", "name"}]}`. `id` is the
slug of the name (`"Alex Kim"` → `alex_kim`), the rule places already follow, and two enrollments
under one name are one person with two reference faces. Both backends report their own roster —
`face_recognition` from its embeddings, OpenCV from its LBPH label map; the two keep their identities
in different files, and `path` says which one is in use. No embedding, dataset image or face box is
ever in a response: `path` is there so a user can find the file and delete it.

Identity ships `enabled: false`, so the answer while it is off is a **reason**, not an empty roster:
`"reason": "identity is disabled; enable modules.face_recognition"`, or the module's own
`disabled_reason` when it has one (`missing dependency: face_recognition (dlib)`). `people: []` next
to `identity.enabled: false` is never "nobody is enrolled".

**Where it is stored.** Enrolment writes under `~/.houndmind/face/`, beside the API token, places and
routines: `face_embeddings.json` for the dlib backend, and `dataset/<name>/*.png` (the reference
images), `face_model.yml` and `face_labels.json` for LBPH. That directory is the biometric data — copy
none of it off the device, and delete it if the dog is passed on. Older builds wrote `data/face_*`
inside the install tree; that directory is left untouched and is not read any more (#104).

**Forgetting someone** — `DELETE /api/v1/people/{id}`, `admin` scope ([§9](CONTROL_API.md#9-people) of `docs/CONTROL_API.md`).
The id is the slug of the name, and the call removes the embeddings, the reference images and the
trained model rather than just the name: a model trained on images you deleted still recognises the
person. The last person to go leaves LBPH untrained — faces are still detected, nobody is named.

**Disable:** `modules.face_recognition.enabled = false`

---

## 21) Pi4 Vision Feed (Pi4)
**What it does:** Captures frames and publishes `vision_frame` (the raw array, read by face
recognition, the semantic labeler and SLAM) and `vision_frame_jpeg` (encoded bytes, served by the
control plane's camera routes) for other modules.

**Enable:**
- `modules.vision_pi4.enabled = true`
- `settings.vision_pi4.backend = "picamera2"` (or `"opencv"` fallback)

**Camera stream:** there is no dedicated stream port. With this module enabled, the control plane
serves the frames it publishes:

- `GET /api/v1/camera/stream` — MJPEG, requires the API token
- `GET /api/v1/camera/snapshot` — single JPEG

See [§26](#26-control-plane--rest-websocket-camera-web-app) for the auth story. The old `settings.vision_pi4.http` block and its port 8090 server were
removed; a config that still contains it fails to load with a suggestion to delete it.

**Camera check tool:**
```bash
python -m tools.camera_check --list-devices --max-index 5
python -m tools.camera_check --index 0 --save frame.jpg
```

**Disable:** `modules.vision_pi4.enabled = false`


## 21a) Vision Inference Scheduler (Pi4)
**What it does:** Runs vision model inference in a background thread for Pi4/5 hardware. Accepts preprocessed frames, schedules inference, and returns results asynchronously for downstream modules.

**Enable:**
- Requires `modules.vision_pi4.enabled = true`. The scheduler itself ships **off**
  (`settings.vision_pi4.inference_scheduler_enabled`, default `false`); turning it on with no model
  wired reports `vision_inference_status: unconfigured` instead of starting a placeholder.

**Configuration:**
- `settings.vision_pi4.inference_scheduler_enabled`: run the worker on each frame (default: `false`)
- `settings.vision_pi4.preprocessing`: frame preparation, applied only while the scheduler runs

**Disable:** Set `settings.vision_pi4.inference_scheduler_enabled = false`

**Notes:**
- Results are published to `vision_inference_result`, and the worker's state to
  `vision_inference_status` — one of `disabled`, `unconfigured`, `pending`, `ready`, `failed`.
- There is no placeholder model. A real one is passed in as `inference_fn` when the module is
  constructed; with nothing wired the scheduler stays off and says `unconfigured`.

## 21b) Vision Preprocessing (Pi4)
**What it does:** Preprocesses camera frames before inference (resize, normalize, ROI selection). Hardware-friendly and configurable for Pi4/5 vision tasks.

**Enable:**
- Runs inside the vision feed whenever `modules.vision_pi4.enabled = true`, and only while the
  inference scheduler is on — at the scheduler's default (`false`) nothing is preprocessed.

**Configuration:**
- `settings.vision_pi4.preprocessing.resize`: Target size, e.g. `[224, 224]` (default `[224, 224]`)
- `settings.vision_pi4.preprocessing.normalize`: Enable normalization (default: `false`)
- `settings.vision_pi4.preprocessing.roi`: Region of interest, e.g. `[x, y, w, h]` (default: `null`)
- `settings.vision_pi4.preprocessing.mean`: Mean for normalization (default: `[0.0, 0.0, 0.0]`)
- `settings.vision_pi4.preprocessing.std`: Std for normalization (default: `[1.0, 1.0, 1.0]`)

Set `mean`/`std` to your model's values when you turn `normalize` on; the shipped `[0.0, …]` /
`[1.0, …]` pair is the identity, not an ImageNet preset.

**Disable:** Nothing to do — it is inert until the scheduler runs.

## 22) Semantic Labeler (Pi4)
**What it does:** Adds object labels from camera frames (lite stub or OpenCV DNN).

**Enable:**
- `modules.semantic_labeler.enabled = true`
- `settings.semantic_labeler.backend = "opencv_dnn"` (or `"stub"`)

**Basic model (recommended first):**
Run the downloader once to fetch a lightweight MobileNet-SSD model and labels:

```bash
python -m tools.download_opencv_models
```

This populates `models/` with:
- `ssd_mobilenet_v1_coco.pb`
- `ssd_mobilenet_v1_coco.pbtxt`
- `coco_labels.txt`

The three paths `settings.semantic_labeler` ships with already point at those names, so on a fresh
install only `backend` (and `modules.semantic_labeler.enabled`) has to change.

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

## 24) Telemetry Dashboard — removed
`modules.telemetry_dashboard` and `optional/telemetry_dashboard.py` are gone, together with the
port-8092 `ThreadingHTTPServer` they wrapped. It was a second, unauthenticated dashboard that
re-served data the control plane already publishes over one authenticated port.

What replaces each part of it:

| Dashboard endpoint | Now |
|---|---|
| `GET /` (HTML dashboard) | The web app at `GET /` on port 8420 ([§26](#26-control-plane--rest-websocket-camera-web-app)) |
| `GET /snapshot` | `GET /api/v1/state`, or the WebSocket at `GET /api/v1/events` |
| `/camera`, `camera_path` | `GET /api/v1/camera/stream`, `/camera/snapshot` |
| `/download_support_bundle` | `GET /api/v1/support-bundle` (`admin` scope) |
| `/download_slam_map`, `/download_slam_trajectory` | **Not exposed in v1.** `slam_map_data` and `slam_trajectory` are still published on the runtime context by `slam_pi4`; a route that serves them is planned with the SLAM work. |
| `trace_id` filter on `/snapshot` | `trace_id` is a field of `GET /api/v1/state`, and the support bundle carries the same snapshots |

A config that still contains `modules.telemetry_dashboard` or `settings.telemetry_dashboard` now
fails to load with a did-you-mean: delete the block, and the web app replaces both.

## 25) WiFi Localization — removed
`modules.wifi_localization` and `optional/wifi_localization.py` are gone. The module scanned for
access points by shelling out to `netsh wlan show networks`, a Windows command: on Raspberry Pi
OS every scan returned `{"error": ...}`, so the feature it documented could never have worked on
the only hardware it targeted. It also had no test and was never registered in the module list.

Indoor positioning, when it comes back, belongs in `mapping/` as a source feeding the pose
estimate — not as a module that only ever worked on a developer's laptop.

## 26) Control Plane — REST, WebSocket, camera, web app

**What it does:** Serves the dog to a browser or a phone. One process, one port (8420), one API,
as specified in `docs/CONTROL_API.md`:

| Surface | Path | Scope |
|---|---|---|
| Liveness | `GET /api/v1/health` | none |
| Identity | `GET /api/v1/meta` | none |
| Caller identity | `GET /api/v1/whoami` | any valid token — the caller's `device`, `scopes` and `kind`, the same shape as the socket's `welcome` frame |
| State snapshot | `GET /api/v1/state` | `state:read` |
| Head sweep | `GET /api/v1/scan` | `state:read` — the last sweep's bearings; `state.scan` carries the summary so a client fetches only when it changed |
| Map | `GET /api/v1/map` | `state:read` — occupancy cells in the mapper's own grid coordinates, capped with a `truncated` flag |
| Module list | `GET /api/v1/modules` | `state:read` |
| Decisions | `GET /api/v1/decisions` | `state:read` |
| Telemetry stream | `GET /api/v1/events` (WebSocket) | token in the `hello` frame; `hello.logs` adds droppable live log lines (`admin`) |
| Camera | `GET /api/v1/camera/stream`, `/camera/snapshot` | `state:read` (`?ticket=`) |
| Places | `GET`/`POST`/`DELETE`/`PATCH /api/v1/places[/{id}]`, `POST /places/{id}/go` | `state:read` / `config` / `move` |
| People | `GET /api/v1/people`, `DELETE /api/v1/people/{id}` | `admin` — ids and names only, never an embedding |
| Motion | `POST /api/v1/command`, `/stop`, `/mode` | `move` |
| Config | `GET`/`PATCH /api/v1/config` (live keys persist into `settings.jsonc`), `GET /api/v1/calibration`, `POST /calibration/run` | `config` |
| History | `GET /api/v1/history` | `state:read` |
| Diagnostics | `GET /api/v1/logs` (`?level=` / `?contains=` filtered server-side), `/support-bundle` | `admin` |
| Web app | `GET /` and `/static/*` | same origin, token in the browser |

**The web app covers every route above.** `GET /` serves fourteen panels: Overview (subject posture,
sonar/battery/temperature/loop instruments, the "why" line behind the last decision, the head-sweep
radar), Drive (hold to
walk with the deadman drawn as a renewing ring, mode, one supervised step at a chosen speed), Tricks
(the repertoire grouped by action class, locomotion behind an arm switch), Routines (run, dry-run,
refused files, the writer), Places (teach, forget, walk, `at_anchor`), People (admin), Camera (ticket stream and
still), Decisions, History (audit, attached clients, pairing window), Map (the occupancy grid, drawn
from `GET /map`), Modules (per-module `tick_ms`
and the reason it is not running), Config (live keys only), Calibration (read-only probes) and Logs
(tail, filter, support bundle). A route with no panel is a feature only an SSH session can use, so
`tests/test_webapp_coverage.py` fails when a route in `ROUTES` is called by no panel and named in no
reasoned exclusion. A panel whose route needs a scope the token lacks says so instead of failing
blank: `people`, `logs` and `support-bundle` need `admin`, and pairing grants `state:read`, `move`
and `config`.

**Light or dark.** The console is dark-first and follows the OS when nobody has said otherwise; the
header's theme button switches to a light palette and remembers the choice in `localStorage`
(`houndmind.theme`), because a deliberate switch must survive a change of ambient light. Both palettes
are colour tokens in `style.css` and nothing else: a component rule that used a literal hex would
ignore the theme, so `tests/test_webapp_assets.py` fails if one appears or if the light block stops
restating a dark token.

**Installable, in a secure context.** `services/web/manifest.webmanifest`, `icon.svg` and `sw.js` let a
phone install the console to its home screen and reload it while the device is briefly away. All three
are gated on `window.isSecureContext`: on plain http the manifest is ignored and no worker is
registered, which is every default install — the TLS section of `docs/INSTALL.md` is the way to change
that, and the default stays off. The worker is network-first and never caches `/api/`, so the current
`app.js` is always what a browser gets while the device answers.

**Safety notifications are opt-in, and never the only signal.** With a secure context the header shows
a `notify` button; the permission prompt happens on that click and never on load, and the button says
`notify blocked` if the browser refuses. When granted, `command_vetoed`, `command_expired` and
`safety_action` raise a desktop notification — the same three the ticker tints as vetoes. The ticker
records every event regardless, and the dog's own stop path is on the device: a notification is an
extra signal, not the safety mechanism.

**The token.** Generated on first start by `services/auth.py::TokenStore` and written to
`~/.houndmind/api_token` with mode 0600. It is never in `config/settings.jsonc`, never in a log
line and never in this repository. There is no token-generator script to run: the runtime creates
the file if it is missing, on the first start of `python -m houndmind_ai`, with the directory `0700`
and the file `0600`. The installer does not create it, so a fresh install has no token file until
the runtime has run once. To read it on the device: `cat ~/.houndmind/api_token`. To pair a phone
or a second browser, open a pairing window and enter the 6-digit code it prints — the code is
single-use and expires after five minutes.

**It is not encrypted by default.** The control plane speaks plain HTTP on port 8420: the token, every
command and every camera frame travel in the clear. The token is the whole security boundary, so
anyone watching the network reads `move` and `config` out of it — and `admin` if they catch the device
token itself. Keep the dog on a network you trust, or close the door: `"host": "127.0.0.1"` plus an
SSH tunnel, a firewall rule admitting only your devices, or a TLS-terminating proxy in front. Never
port-forward 8420 to the internet.

**The camera does not take the token in a URL.** An `<img>` tag cannot set a header, so the stream used
to carry `?token=` — the operator credential, in browser history and every access log. It now carries
`?ticket=`: `POST /api/v1/camera/ticket` mints a value good for 60 seconds, one use, granting
`state:read` on a single frame. The web app mints its own.

**Turning TLS on** is one key — `"tls_enabled": true` — and the certificate is generated on first
start, self-signed, for this device. Each client trusts it once;
`docs/INSTALL.md` [§TLS](INSTALL.md#tls-for-the-control-plane-optional) has the
browser, phone and `curl` steps, including the part that bites: an Android HTTP client rejects a
self-signed certificate by default unless the app carries its own trust configuration.

```bash
# Show a pairing code (valid 5 minutes, single use)
# With TLS on, use https:// and add --cacert ~/.houndmind/tls/cert.pem
curl -H "Authorization: Bearer $(cat ~/.houndmind/api_token)" \
     -X POST http://127.0.0.1:8420/api/v1/pair/open
```

Every motion command is judged by the interlock exactly as an internal producer is. A refusal
answers `409` with `veto` and `detail`, and the client is expected to display the reason. `rest`
mode refuses client motion with a reason; `POST /api/v1/stop` is never vetoed.

**Config** (`settings.api`, and `modules.api` for the on/off switch):

| Key | Default | Meaning |
|---|---|---|
| `host` | `0.0.0.0` | Bind address. The token is the security boundary, not the bind — and the traffic is cleartext. |
| `port` | `8420` | One port for REST, WebSocket, MJPEG and the web app. |
| `token_path` | `~/.houndmind/api_token` | Where the device token is written on first start (`0600`). |
| `tls_enabled` | `false` | Serve HTTPS instead of HTTP. Off means cleartext — see the warning above. |
| `tls_cert` | `~/.houndmind/tls/cert.pem` | Certificate. Generated self-signed on first start when missing while TLS is on. |
| `tls_key` | `~/.houndmind/tls/key.pem` | Private key for that certificate, `0600`. |
| `state_hz` | `10.0` | Telemetry push rate. |
| `pairing_enabled` | `true` | Allow pairing codes. |
| `pairing_attempts_per_minute` | `5` | Rate limit per peer. |
| `command_queue` | `64` | Bounded inbox; a full queue is `429`, never added latency. |
| `command_ack_timeout_s` | `0.5` | How long a `POST /command` waits for the interlock before `503`. |
| `link_loss_s` | `6.0` | A client that stops pinging loses its command. |
| `max_clients` | `8` | Sessions kept; the least recently seen idle one is evicted. |
| `log_tail` | `200` | Default and maximum `?tail=` for `/logs`. |
| `discovery_enabled` | `true` | Advertise the control plane over mDNS so a client finds it by name (#38). Off means address-only. |
| `discovery_name` | `houndmind` | The mDNS instance name, so two dogs on one LAN stay distinguishable. |

**Disable:** `modules.api.enabled = false` removes the network surface entirely — the dog still
runs, and nothing listens. That is the right setting for a dog that should never be reachable.

**Not in v1:** remote access beyond the LAN and accounts. `POST /api/v1/calibration/run` is
implemented and is **read-only**: it dispatches the four calibration requests that read, never one
that writes an offset, so it needs no physical confirmation. A calibration that moves the dog stays
a device action (`python -m tools.calibrate_servos --apply`,
[`CONTROL_API.md` §10](CONTROL_API.md#10-calibration)).

---

## 27) Path Planning (A* helper)

**What it is:** `houndmind_ai.mapping.path_planner.astar`, a dependency-free A* over a grid of `0`
(free) / `1` (obstacle), plus the example below. It is a library function with **no caller in the
runtime**: `path_planning_enabled` and the `path_planning` context key went with the hook that
produced them ([#121](https://github.com/seven-lynx/HoundMind/issues/121)), because a grid route needs
a position estimate this stack does not have.

**Use instead:** `place_navigator` walks to a taught place (`docs/CONTROL_API.md` [§8](CONTROL_API.md#8-places)), and
`obstacle_avoidance` handles everything inside one scan sweep.
 
Note: setting `mapping.path_planning_enabled` or `mapping.goal` is now an unknown-key error at load.
`goal` never was a key, so the old text here stopped the runtime at startup.

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

**Not a runtime feature:** there is nothing to enable or disable. The two keys the old text told you
to set (`path_planning_enabled`, `goal`) are gone from the schema, and setting them is a load error.

---

## 28) Profiles

`profile` in `config/settings.jsonc` ships as `auto`, which asks `board/detect.py` which Raspberry Pi
this is; `HOUNDMIND_PROFILE` overrides it at launch.

| Profile | What it sets |
|---|---|
| `auto` | Default. Use the detected board's profile: `pi4` or `pi5`. On a host with no device tree (CI, a workstation, a container) it uses `pi4` and logs a warning. |
| `pi4` | `loop.tick_hz: 10`, faster scan cadence, and Pi4/5-only modules **permitted** — still individually `enabled: false`. |
| `pi5` | Same cadence and enablement as `pi4`, plus thermal warning thresholds that suit a board which idles near 65 °C and throttles at 80 °C. |

An unsupported board (Pi 3 and older) is a load-time error, not a silent fallback: the message names
the model and the last release that supported it. `v2026.01.18` is that release.

A profile enables capability, never a feature. Pi4/5 modules (vision feed, face recognition, semantic
labeling, SLAM, voice assistant) stay off until you turn that module on and validate it on the bench.

---

## 29) How to Disable Any Feature

1. Open `config/settings.jsonc`.
2. Find the module under `modules`.
3. Set `"enabled": false`.
4. Restart HoundMind.

Disabling is always safe: a module that is off publishes nothing, and every consumer reads the
validity flags instead of assuming a value. To remove the network surface entirely, disable
`modules.api` — the dog keeps running with nothing listening.

---

## 30) Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: pidog` | Install the SunFounder PiDog software first, then HoundMind in the **same** venv. It is not on PyPI. |
| A module shows `failed` in `GET /api/v1/modules` | Read its `detail`. A `failed` module is a bug; a `disabled` one is configured. |
| Config refuses to load | An unknown or misspelled key is a load-time error with a did-you-mean. Delete or fix the key — the runtime will not start on a bad config. |
| Camera frames never arrive | `settings.vision_pi4.backend` to `"opencv"` if `picamera2` fails. Check `python -m tools.camera_check --list-devices`. |
| `409 vetoed` on every forward | `veto` says why: `obstacle` (something is 12 cm away), `tilt` (right the dog), `low_voltage`, `mode` (`rest` refuses clients), or `expired` (the deadman ran out). |
| No logs on disk | `settings.logging.log_dir` and `logging.enable_file`. See `docs/LOGGING.md`. |
| Servos jitter | Lower `speed`, reduce `step_count`, and check the servo offsets were not overwritten.
