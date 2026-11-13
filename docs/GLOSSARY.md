# Glossary

Status: **reference** — the words this project uses as if everyone already knew them.
Pairs with: `docs/ARCHITECTURE.md` (the layers these belong to), `docs/REPERTOIRE.md` (the actions),
`docs/QUICKSTART.md` (if you are new, read that first)

One line each, then the section that owns the full story. If a term here is missing from the file it
points at, that file is the one with the bug.

## Contents

1. [Runtime](#1-runtime)
2. [Motion](#2-motion)
3. [Behaviour](#3-behaviour)
4. [Config and boards](#4-config-and-boards)
5. [Network and auth](#5-network-and-auth)
6. [Health and failure](#6-health-and-failure)

---

## 1. Runtime

| Term | Means |
|---|---|
| **module** | One runtime component with `start`/`tick`/`stop`, registered in `main.build_registry`. Missing from that list means it never runs. |
| **tick** | One pass of the loop: read sensors, fuse, decide, emit at most one motion command. `loop.tick_hz` is how many per second. |
| **context** | The `RuntimeContext` dict every module reads and writes. Its keys are a contract — `docs/HOUNDMIND_PROGRAMMING_GUIDE.md` §4. |
| **capability** | A tag a module registers with (`SAFETY`, `MOTION`, `VISION`, …) so the registry can answer "is there anything that does X". |
| **profile** | The board profile (`pi4`, `pi5`), resolved from the device tree when `profile` is `auto`. |
| **decision record** | One tick's answer to "what won, what was refused and why" (`kernel/decisions.py`), behind `/decisions`. |
| **dry run** | A routine or command that walks every step and moves nothing. |

## 2. Motion

| Term | Means |
|---|---|
| **HAL** | The hardware abstraction layer: the only code allowed to touch `pidog`/`robot_hat`. `FakeDogHAL` is its test stand-in. |
| **intent** | A producer's *request* to move, published to the `IntentBoard`. Not a command, and never an action string in the context. |
| **intent board** | The ranked table of live intents — one slot per source, expiring unless refreshed (`kernel/intents.py`). |
| **gateway** | `motion_gateway`: ranks the intents, runs the winner through the interlock, publishes `motion_command`. |
| **interlock** | The non-optional veto layer between a decision and a servo (`act/interlock.py`). Refuses on tilt, obstacle, low battery, mode, or an expired command. |
| **deadman** | A command's expiry. A motion command not refreshed in time is refused, so a dropped connection cannot leave the dog walking. |
| **veto** | The reason a command did not run: `obstacle`, `tilt`, `low_voltage`, `mode`, `expired`. |
| **latched** | A condition that stays true until explicitly cleared — e.g. `tilt_latched` after the dog was picked up. |
| **action** | One named thing the dog can do, from the repertoire. Its *class* decides how much interlock applies. |

## 3. Behaviour

| Term | Means |
|---|---|
| **repertoire** | The full catalogue of actions (`config/actions.jsonc`, `GET /api/v1/repertoire`). The vocabulary a command or routine may use. |
| **bucket** | A named group of actions the FSM draws from: `idle`, `alert`, `avoid`, `play`, `rest`, `patrol`, `explore`, `interact`. |
| **beat** | The action a behaviour state publishes on entry, so entering `alert` looks like something. |
| **cue** | The sound attached to a beat (`behavior.cue_sounds`), played on the same tick as the entry command. |
| **routine** | A JSON file listing steps the dog plays in order. Data, never code — `docs/ROUTINES.md`. |
| **place** | A named spot taught by heading and distance, navigable with `POST /api/v1/places/{id}/go`. |
| **anchor** | The reference a place's vector is measured from. A place taught against a different anchor is refused, not walked. |
| **autonomy** | The mode chooser that picks `idle`/`patrol`/`play`/`rest` on a timer, weighted by `personality`. |
| **habituation** | The suppression of repeated reactions to the same stimulus for a recovery window. |
| **energy** | An optional 0–1 internal state that biases autonomy toward rest when low. |
| **quiet mode** | Suppresses cues and sound while leaving motion alone. |

## 4. Config and boards

| Term | Means |
|---|---|
| **`modules.<name>`** | The on/off and `required` switch for one module. Tuning goes under `settings`, not here. |
| **`required: true`** | A module whose failure stops the whole runtime. Reserved for HAL pieces. |
| **load-time error** | A bad config stops the process before any hardware is touched, with a did-you-mean. Unknown keys are errors, not warnings. |
| **`disable(reason)`** | How a module that cannot run reports it instead of raising. It shows as `disabled` with the reason. |
| **board** | Which Raspberry Pi this is, from the device tree: `pi4`, `pi5`, `unsupported`, `unknown`. `board/` holds no policy — `docs/BOARD.md`. |
| **`unknown` board** | No device tree at all (CI, workstation, container). The runtime treats it as `pi4`. |

## 5. Network and auth

| Term | Means |
|---|---|
| **control plane** | The single HTTP + WebSocket listener on port 8420 (`services/api.py`). The only network surface. |
| **scope** | What a token may do: `state:read`, `move`, `config`, `admin`. Declared per route. |
| **device token** | The install-issued secret in `~/.houndmind/api_token` (0600). Never logged, never in a URL. |
| **pairing code** | A six-digit, five-minute, single-use code exchanged at `POST /api/v1/pair` for a client token. |
| **ticket** | A single-use, 60-second camera credential, because an `<img>` tag cannot send a header. |
| **unauthenticated route** | `/meta`, `/health`, `/pair`, `/events` (the socket authenticates in its first frame), and the two camera routes via `?ticket=` |

## 6. Health and failure

| Term | Means |
|---|---|
| **ok / degraded / disabled / failed** | A module's four states in `GET /api/v1/modules`. `disabled` is configured; `failed` is a bug. |
| **validity flag** | `distance_valid`, `imu_valid`, `touch_valid`, `sound_valid`. Branch on the flag before the value — `distance_cm=100` with `distance_valid=False` is not "clear at 1 m". |
| **staleness** | A reading older than its budget says nothing about now. The watchdog and `sensor_health` both measure it. |
| **hold** | What the watchdog does to motion when data goes stale: it stops. It never poses the dog. |
| **support bundle** | A zip of logs and config (from the shell) or of live state (over HTTP). Two producers, different contents — `docs/LOGGING.md`. |
| **trace id** | The id that ties one incident's log lines together (`HOUNDMIND_TRACE_ID`). |

