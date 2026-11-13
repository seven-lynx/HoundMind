# HoundMind Control API v1

Status: **contract** — the web app and the Android app code against this file. Additive changes
only within `v1`; anything that removes or renames a field requires `v2` and a deprecation window.
Pairs with: `src/houndmind_ai/services/api.py` (the route table), `docs/FEATURES_GUIDE.md` §25

Base URL: `http://<pi-ip>:8420`. There is **no mDNS** — the dog does not advertise itself, so the
address is whatever `hostname -I` reports on the device. Everything under `/api/v1` is JSON;
`GET /` serves the web app that ships inside the package.

The route table in §2 is asserted against the code by `tests/test_api_routes.py`, which parses this
file. A route that exists in code and not here — or here and not in code — fails CI.

---

## 1. Authentication

Two mechanisms, both bearer-style. Everything requires a token except `/meta`, `/health` and
`/pair`, which is the exchange that *produces* a token.

**This is plaintext HTTP.** Nothing on port 8420 is encrypted: the device token, every command and
every camera frame cross the LAN in the clear. The token *is* the security boundary, so anyone who can
observe the network — or read a single access log — holds `move`, `config`, and `admin` if they catch
the device token itself. Keep the dog on a network you trust, or close the door:

- `settings.api.host: "127.0.0.1"` and an SSH tunnel: `ssh -L 8420:localhost:8420 <user>@<pi>`.
- A firewall rule that admits only your own devices to port 8420.
- A TLS-terminating reverse proxy in front, if you need to reach it from beyond the LAN.

**TLS is available and off by default.** `settings.api.tls_enabled: true` serves HTTPS with a
self-signed certificate generated on first start for this device — `docs/INSTALL.md` has the trust
steps for a browser and a phone. A client that cannot be taught to trust it (the Android app is one
today) stays on the plaintext path above, with those workarounds. **Do not port-forward 8420 to the
internet** either way.

**Device token** — generated on first start by `services/auth.py::TokenStore` and written to
`~/.houndmind/api_token`, directory `0700`, file `0600`. It is never in `config/settings.jsonc`,
never in a log line, and never in this repository. The web app does not receive it automatically: on
first load it shows a token field and you paste it once (`services/web/index.html`). On the device,
`cat ~/.houndmind/api_token`.

**Pairing** — for the Android app and for a second browser:

```
POST /api/v1/pair
{ "code": "483920", "client_name": "Pixel 8" }
→ 200 { "device_token": "...", "scopes": ["state:read","move","config"], "name": "Pixel 8" }
```

The code is 6 digits, shown only to a holder of the **device token** via `POST /api/v1/pair/open`,
valid for 5 minutes, single use, and rate-limited to `api.pairing_attempts_per_minute` (default 5)
per minute. It is never logged. A paired client gets `state:read`, `move` and `config` — not `admin`,
because rotating the device token is an operator decision, not a client one.

**Scopes** (`services/auth.py:38`)

| Scope | Grants |
|---|---|
| `state:read` | `GET /state`, `/modules`, `/events` (WS), `/camera/*`, `/history` |
| `move` | `POST /command`, `POST /stop`, `POST /mode` |
| `config` | `GET`/`PATCH /config`, `GET /calibration` |
| `admin` | `POST /pair/open`, `GET /people`, `DELETE /people/{id}`, `GET /logs`, `GET /support-bundle` — device token only |

Header: `Authorization: Bearer <token>`. The two camera routes also accept `?ticket=<ticket>` because an
`<img>` tag cannot set a header: mint one with `POST /api/v1/camera/ticket` (`state:read`), it is valid
for 60 seconds and **single use**, and it buys `state:read` on one frame and nothing else. The device
token is **not** accepted in a query string — it used to be, and that put the credential for `move`
and `config` into browser history and access logs (`#18`).

---

## 2. Endpoints

| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/meta` | none | `api_version`, `min_client`, `scheme`, `device_id`, `board`, `profile`, `uptime_s`, `capabilities` |
| `GET` | `/api/v1/health` | none | liveness only: `{"status":"ok"}` — no detail, no leak |
| `GET` | `/api/v1/state` | `state:read` | full state snapshot (see §4) |
| `GET` | `/api/v1/modules` | `state:read` | every module: `ok`/`degraded`/`disabled`/`failed` + reason |
| `GET` | `/api/v1/repertoire` | `state:read` | every action this dog can run, with its class and params (§3) |
| `GET` | `/api/v1/routines` | `state:read` | every routine the runner loaded, the files it refused, and the run in progress (§3) |
| `GET` | `/api/v1/places` | `state:read` | every place the file holds, the entries it refused, and the walk in progress (§8) |
| `GET` | `/api/v1/people` | `admin` | enrolled people: ids and names only, never an embedding (§9) |
| `DELETE` | `/api/v1/people/{id}` | `admin` | forget one person: the embedding and every reference face go, not just the name (§9) |
| `GET` | `/api/v1/decisions?limit=50` | `state:read` | the last N decision records, oldest first (§4); 503 when the feed is not running |
| `GET` | `/api/v1/events` | token in `hello` frame | WebSocket telemetry + event stream (§5) |
| `GET` | `/api/v1/camera/stream` | `state:read` (`?ticket=`) | MJPEG, multipart/x-mixed-replace |
| `GET` | `/api/v1/camera/snapshot` | `state:read` (`?ticket=`) | single JPEG |
| `POST` | `/api/v1/camera/ticket` | `state:read` | mint a single-use camera ticket: `{ticket, expires_in}` |
| `POST` | `/api/v1/pair` | none | exchange a pairing code for a client token |
| `POST` | `/api/v1/pair/open` | `admin` | open a pairing window; returns the 6-digit code |
| `POST` | `/api/v1/command` | `move` | issue a command (§3) |
| `POST` | `/api/v1/stop` | `move` | unconditional stop; never vetoed, never queued, and it ends a running routine |
| `POST` | `/api/v1/routines/{id}/run` | `move` | start one routine; optional `{"dry_run": true}` (§3) |
| `POST` | `/api/v1/places` | `config` | create one place; a refused body is `400` with `problems[]` (§8) |
| `DELETE` | `/api/v1/places/{id}` | `config` | forget one place by id or name; a second call is `404` (§8) |
| `POST` | `/api/v1/places/{id}/go` | `move` | ask the dog to walk to one place; optional `{"at_anchor": true}` (§8) |
| `GET` | `/api/v1/mode` | `state:read` | current mode |
| `POST` | `/api/v1/mode` | `move` | switch `idle` \| `patrol` \| `manual` \| `rest` |
| `GET` | `/api/v1/config` | `config` | effective config, secrets redacted |
| `PATCH` | `/api/v1/config` | `config` | four live keys only, listed below |
| `GET` | `/api/v1/calibration` | `config` | servo offsets, read-only |
| `GET` | `/api/v1/history?limit=50` | `state:read` | recent commands with verdicts, and live sessions |
| `GET` | `/api/v1/logs?tail=200` | `admin` | recent log lines, redacted |
| `GET` | `/api/v1/support-bundle` | `admin` | zip: meta, state, modules, redacted config, audit, sessions |

`PATCH /config` writes only `behavior.action_cooldown_s`, `led.brightness`,
`motors.min_action_interval_s` and `navigation.safe_distance_cm` (`services/api.py:62`), each re-read
every tick by its module. Any other key is refused with the live list in the body, because a config
write that changes nothing is the bug this API exists to avoid.

**Reserved, not implemented in v1:** `POST /api/v1/calibration/run` (it moves the dog, so it needs a
physical confirmation on the device first) and `POST /api/v1/update`. There is no route for face
enrollment or SLAM map download; both are runtime-context commands (see `FEATURES_GUIDE.md`).

---

## 3. Commands

```
POST /api/v1/command
Authorization: Bearer <token>
{
  "id": "8f2c1a",            // optional; the server generates one if omitted
  "action": "forward",       // must be in the command vocabulary
  "params": { "speed": 120 },
  "ttl_ms": 300              // deadman; defaults to 300, capped at 5000
}
```

`source` is not a client field: a client command is always `client`, and a client that could claim
`system` would outrank the watchdog.

**`202 Accepted`** — it reached the actuators:

```json
{ "accepted": true, "id": "8f2c1a", "action": "forward", "expires_at": 1762771200.31 }
```

**`409 Conflict`** — the interlock or the mode policy refused it. This is a *feature*, and the client
must show the reason to the user:

```json
{ "accepted": false, "id": "8f2c1a", "veto": "obstacle", "detail": "12.0 cm at sensor (limit 12.0 cm)", "retry_after_ms": 0 }
```

**`400 Bad Request`** — malformed, or an unknown action:

```json
{ "error": "unknown_action", "detail": "forwardd", "suggestion": "forward" }
```

**`429`** — the bounded command queue is full. **`503`** — no module answered within
`api.command_ack_timeout_s`, which means the runtime is not ticking; the dog cannot be driven.

### The command vocabulary, and the repertoire

`config/actions.jsonc` is the action **catalog**: activity groups (`idle`, `alert`, `avoid`, `play`,
`rest`, `patrol`, `explore`, `interact`, `custom`) of `pidog` ActionFlow names, which the behavior
module draws from. Beside them it carries the **classification** — one class per action — which is
what decides how much of the safety envelope the interlock applies.

`POST /command` accepts any action that is either in `kernel/commands.py::KNOWN_ACTIONS` (the
built-in vocabulary, always available) or classified in that file. Every action a bucket lists has
to be classified, or the device refuses to start and says which name is missing: an action the
behavior module can emit and the interlock must refuse is a bug, not a configuration style.

| Class | Tilt latch | Obstacle stop | Battery floor | Deadman | Examples |
|---|---|---|---|---|---|
| `locomotion` | yes | forward family | yes | yes | `forward`, `backward`, `turn_left`, `trot` |
| `posture` | yes | no | yes | yes | `sit`, `lie`, `stretch`, `high five` |
| `expression` | yes | no | yes | yes | `wag_tail`, `bark`, `shake_head`, `pant` |
| `non_motion` | no | no | no | yes | `rgb`, `sound`, `speak`, `head`, `rpy` |

Three rules the table implies, and a client should not have to discover:

1. **`non_motion` is never vetoed.** A dog at 6.3 V must still be able to whine about it, and an LED
   must not be blocked because something is 8 cm away. It still spends its deadman: a stale colour
   request is as wrong as a stale gait.
2. **The obstacle stop is the forward family** (`forward`), not every locomotion action. `backward`
   and the turns are how the dog gets out of a corner; a turn-in-place refused at 8 cm is a dog
   frozen facing a wall.
3. **The four gaits cannot be reclassified.** `forward`, `backward`, `turn_left` and `turn_right`
   are `locomotion` whatever the file says; a config that tries to weaken one is refused at load
   with the action named. `stop` is never vetoed, in any mode, from any class.

A `409` carries the reason, so a client shows `veto` rather than guessing: `veto: "unknown_action"`,
`"expired"`, `"tilt"`, `"low_voltage"`, `"obstacle"` or `"mode"` (§4 documents the state snapshot
the same refusals appear in).

`GET /api/v1/repertoire` is the honest menu: every action *this* device can run, so a client renders
what the firmware reports instead of a list baked into the app. It unions the classification with the
action list the HAL returns.

```json
{ "count": 43,
  "actions": [ { "name": "sit",   "class": "posture",    "params": [] },
               { "name": "sound", "class": "non_motion", "params": ["name", "volume"] } ] }
```

A `class` of `null` means the HAL can do it and nothing has classified it: the dog will not run it
from a command until it is added to `config/actions.jsonc`. `null` is never a guess — the same rule
`sensors` follows for a reading that could not be taken.

Producers and the catalog spell motion with spaces (`"turn left"`, `"wag tail"`); the vocabulary is
underscored, and `kernel/commands.py::canonical_action` is the only translation. A client that wants
the raw catalog still reads `config/actions.jsonc` from the repository — `GET /meta`'s `capabilities`
is a list of *surfaces* (`command`, `events`, `mode`, `state`, plus `camera`, `pairing` and
`routines` when available), not a list of actions.

### Semantics the client must respect

1. **Motion is a deadman, not a toggle.** A client wanting continuous forward must re-issue at least
   every `ttl_ms`. If the app dies, the dog stops — and the deadman starts when the device received
   the command, so a command that sat in a tunnel does not run when it finally arrives.
2. **`POST /stop` is never refused** and bypasses the queue. The UI must always have it reachable, and
   must call it on `onPause`/`onStop`. It ends a running routine too, so a stop is a stop.
3. **`409` is not retried blindly.** `veto: "obstacle"` means retrying makes it worse; `veto: "tilt"`
   needs a human to right the dog and clear the latch; `veto: "mode"` means the runtime is in `rest`.
4. **Ordering is by priority, not arrival.** `system` > `watchdog` > `client` > `navigation` >
   `place` > `routine` > `behaviour` (`kernel/commands.py:37`). A `system` command preempts a `client`
   one, and the preempted client can see it in `actuators.displaced`. A `place` goal — "go to the
   kitchen" — sits just under `navigation`, so a hazard always wins the tick and the goal resumes when
   it clears; a `routine` sits under the goal, and over idle behaviour.

### Routines

A routine is a JSON file of steps the runner loaded at boot — one file per routine, from
`settings.routines.dir` (`FEATURES_GUIDE.md` §7). These routes expose what the dog **loaded**, not
what is on disk right now: a file added since boot appears after a restart, and a file the validator
refused is listed with the reason instead of being hidden.

`GET /api/v1/routines` — `state:read`:

```json
{
  "directory": "/home/pi/.houndmind/routines",
  "routines": [
    { "id": "morning_greeting", "name": "Morning greeting", "version": 1,
      "allow_locomotion": false,
      "steps": [ { "action": "sound", "params": { "name": "woohoo" } }, { "action": "sit" } ] }
  ],
  "refusals": {
    "broken.json": [ { "path": "routine.steps[0].action",
                       "message": "'sitt' is not in the repertoire; …", "hint": "sit" } ]
  },
  "current": { "id": "morning_greeting", "name": "Morning greeting", "index": 1, "total": 2,
               "state": "running", "dry_run": false, "action": "sit", "veto": null,
               "detail": null, "started_at": 1762771200.31 }
}
```

`current` is `null` before the first run and keeps the last run afterwards. `state` is `running`,
`done`, `stopped` or `refused`; a refused run names its `veto` (`obstacle`, `tilt`, `mode`,
`precedence`, …) in the same vocabulary as `motion_verdict`. `503` means no runner is loaded.

`POST /api/v1/routines/{id}/run` — `move`. The body is optional; its only field is `dry_run`:

```json
{ "dry_run": true }     // walk the steps without publishing one: counters move, servos do not
```

**`202 Accepted`** — queued for the runner's next tick, which publishes one step per tick:

```json
{ "accepted": true, "id": "morning_greeting", "dry_run": false, "steps": 2 }
```

- **`400`** — `dry_run` was not a real boolean (`"true"` is refused, never coerced).
- **`404`** — no routine by that id was loaded; `suggestion` carries the closest name.
- **`409`** — a run is in progress, or a request is already queued for the next tick; `current` is
  the run that blocked it.
- **`503`** — no routine runner is loaded.

Every step is published as a `routine` intent, so each one passes the mode gate and the interlock;
a run that is refused **stops** there rather than skipping the step, because a routine that half-runs
is worse than one that never starts. `POST /api/v1/stop` ends the run as well as the motion.

---

## 4. State snapshot

`GET /api/v1/state` and the WS `state` frame share one shape (`services/state.py::build_state`):

```json
{
  "ts": 4212.31,
  "trace_id": "trace123",
  "mode": "patrol",
  "sensors": {
    "distance_cm": 42.5, "distance_valid": true,
    "touch": "N", "touch_valid": true,
    "sound_detected": false, "sound_direction": null, "sound_valid": false,
    "pitch_deg": 1.2, "roll_deg": -0.4, "imu_valid": true,
    "battery_v": 7.6, "battery_valid": true
  },
  "actuators": {
    "last_command": "forward", "source": "navigation", "since_s": 0.8,
    "vetoed": false, "veto": null, "tilt_latched": false, "displaced": 0
  },
  "nav": { "decision": "forward", "confidence": 0.82 },
  "decision": {
    "schema_version": 1, "ts": 4212.3, "trace_id": "trace123",
    "mode": "patrol", "state": "alert", "intent": "forward", "source": "navigation",
    "vetoes": [
      { "action": "sit", "source": "behaviour", "reason": "precedence", "detail": "navigation outranks behaviour" }
    ],
    "inputs": { "distance_cm": 42.5, "distance_valid": true },
    "confidence": null
  },
  "routines": {
    "id": "morning_greeting", "name": "Morning greeting", "index": 1, "total": 3,
    "state": "running", "dry_run": false, "action": "sit", "veto": null, "detail": null,
    "started_at": 1762771200.31
  },
  "health": { "status": "ok", "cpu_pct": 31.0, "temp_c": 58.2, "mem_used_pct": 44.0, "reasons": [] },
  "supervisor": { "holding": false, "reason": null, "restarts": [], "failed": [] },
  "modules": { "loaded": 11, "disabled": 3, "failed": 0 }
}
```

`ts` is the runtime's **monotonic** clock, not epoch seconds: compare it to other timestamps in the
same stream, never to wall time. Device identity and version live in `GET /meta`, not here.

`decision` is the tick's decision record (`kernel/decisions.py`) — the same object
`GET /api/v1/decisions` returns a list of. `intent` and `source` name the intent that won the tick;
`vetoes` names every intent that lost and why, where `reason` is the interlock's own veto
(`obstacle`, `tilt`, `low_voltage`, `expired`, `unknown_action`) or `mode`/`precedence` for an intent
the mode policy dropped or a higher rank displaced; `inputs` carries the readings the decision used,
**with their validity flags**. It is `null` until the gateway's first tick. `confidence` is `null` —
never `0.0` — when nothing measured it. A client that diffs on `ts` sees one new record per tick; the
WS `decision` event (§5) fires only when the *choice* changes, so treat the two as different
cadences over the same object.

`routines` is the run the runner is playing — the **same object** `GET /api/v1/routines` returns as
`current` — or `null` before the first run and after a restart. `state` is `running`, `done`,
`stopped` or `refused`; a refused run keeps the `veto` and `detail` that ended it, so a client shows
"stopped at step 2: obstacle" instead of an unexplained halt. It is rewritten every tick while the run
is live, whereas the WS `routine` event (§5) fires only when the run *moves*: a new step, a new state,
or a new veto. `started_at` is epoch seconds from the device's wall clock, not the monotonic `ts` —
it is a timestamp to display, not one to compare against this stream.

`actuators.source` names the producer that won the tick (`system`, `watchdog`, `client`,
`navigation`, `routine`, `behaviour`). `actuators.displaced` counts the intents a higher-priority one overrode
this tick — a client that pressed forward and sees `source: "watchdog"` can tell "someone else is
driving" from "the dog ignored me". `actuators.veto` carries the reason the last command was refused,
and `actuators.tilt_latched` reports the latch state the client must surface.

`supervisor` is the watchdog's own state: whether it is holding motion (`holding` + `reason`, which is
`null` or a staleness reason), which modules it asked the runtime to restart, and which it has given
up on. `holding: true` never means the dog was posed — recovery is stop-and-report.

**Validity flags are mandatory and clients must honour them.** `distance_cm: 42.5` with
`distance_valid: false` means "no measurement" — render "—", never "42 cm". This is the one rule in
the API that a client may not soften. The same applies to `touch_valid`, `sound_valid`, `imu_valid`
and `battery_valid`, whose value fields are `null` rather than a plausible zero.

`GET /api/v1/modules` is the diagnostic view, and its `state` is a different scale from
`health.status`:

```json
{ "modules": [
    { "name": "scanning", "state": "ok", "tick_ms": 3.1, "detail": null },
    { "name": "slam_pi4", "state": "disabled", "tick_ms": null, "detail": "missing dependency: rtabmap" }
  ],
  "counts": { "loaded": 11, "disabled": 3, "failed": 0 } }
```

Module states: `ok`, `degraded` (enabled but not started), `disabled` (a normal, configured state) and
`failed` (a bug the user should see). `counts` is the same object `/state` reports.

---

## 5. WebSocket

```
GET /api/v1/events            (Upgrade: websocket)
→ client sends: { "type": "hello", "token": "<device_token>" }
← server sends: { "type": "welcome", "data": { "scopes": [...], "device": "<name>", "session": {...} } }
```

Nothing sent before `hello` is answered, and a failed `hello` closes the socket.

Server frames:

| `type` | Payload | When |
|---|---|---|
| `welcome` | `data`: `scopes`, `device`, `session` | once, after a successful `hello` |
| `state` | `data`: the §4 snapshot | `api.state_hz` (default 10 Hz) |
| `event` | `data`: `{ "name", "data", "ts" }` | on transition |
| `pong` | `ts` | in reply to a client `ping` |
| `error` | `error` (code), `detail` (optional) | on a rejected message, or `superseded` |

Client frames: `{"type": "hello", "token": "..."}` then `{"type": "ping"}`. Anything else is an
`error` with code `bad_request`.

The only event names the server publishes today are `mode_changed`, `command_accepted`,
`command_vetoed`, `command_expired`, `pairing_window_open`, `decision` and `routine`. The last two
carry the §4 `decision` and `routines` blocks and are sent only when the object changes — a new
winner, a new refusal, a new mode or state for the decision; a new step, a new state or a new veto for
a routine — never on every tick, because this channel is never dropped and a client that falls behind
it is disconnected. A command's *outcome* is the synchronous reply to `POST /command` (§3) — there is
no separate `command_ack` frame; the events are the broadcast, not the acknowledgement. Clients must
tolerate an unknown `name` and ignore it.

Client rules:

- **Send `ping` every 2 s.** No ping for `api.link_loss_s` (default 6 s) and the server treats the
  client as gone and stops its command, publishing `command_expired` with `reason: "link_loss"`.
- **Backpressure is drop-oldest for `state`, fatal for `event`.** A slow client silently skips `state`
  frames; a client that cannot absorb 64 queued event frames is disconnected, because losing
  `command_vetoed` is how a user ends up shouting at a dog that is refusing to move for a reason
  nobody told them.
- **One socket per token.** A second connection with the same token evicts the first, which receives
  `error` / `superseded` so the UI can explain it.

---

## 6. Errors

| HTTP | `error` | Meaning | Client action |
|---|---|---|---|
| 400 | `bad_request` | malformed JSON / missing field | fix the request |
| 400 | `unknown_action` | action not in the vocabulary | show `suggestion` |
| 401 | `unauthorized` | missing or bad token | re-pair |
| 403 | `forbidden` | token lacks the scope | do not retry |
| 404 | `not_found` | unknown path | — |
| 409 | `vetoed` | interlock or mode refused (`veto`, `detail`) | show the reason to the user |
| 429 | `rate_limited` | pairing attempts or command queue | honour `Retry-After` |
| 503 | `unavailable` | the runtime did not answer, or the log file is absent | show module detail |
| 500 | `internal` | a bug | ask for a support bundle |

Every error body is `{ "error": "<code>", "detail": "<human text>", ...extras }`. `detail` is safe to
display verbatim — it must never contain a path, a token, or a stack trace.

---

## 7. Versioning and compatibility

- `GET /api/v1/meta` returns `{ "api_version": 1, "min_client": 1 }`.
- Adding a field or a route is **not** a breaking change. Removing or renaming one is, and requires
  `v2` with the old route served for at least one release.
- `GET /api/v1/meta` gained `scheme` (`"http"` | `"https"`) when TLS became optional: additive, and a
  client that ignores it keeps working against both transports.
- **Breaking**: the two camera routes no longer accept `?token=`. Mint a ticket at
  `POST /api/v1/camera/ticket` and pass `?ticket=`. A client that sets headers needs no change at all,
  and the bundled web app already does the right thing. Removing the token from the query string is
  the point of the change (`#18`), so it is not kept behind a flag.
- Enum values are additive: a client must handle an unknown `mode` or module `state` by displaying it
  read-only rather than crashing.
- `docs/CONTROL_API.md` is the source of truth. `tests/test_api_routes.py` parses §2 and compares it
  to the route table in `services/api.py`, so a route that exists in one and not the other fails CI.
  Change both, in the same commit.

---

## 8. Places

A place is a named pose a person taught: `{id, name, heading_deg, distance_cm, anchor, confidence,
created_ts, visits}`. `id` is the slug of the name (`"Living Room"` → `living_room`) and is what every
other route takes. Nothing infers a place from a scan, and `DELETE` is the only way one disappears.

| Route | Body | Answers |
|---|---|---|
| `POST /api/v1/places` | `{"name", "heading_deg", "distance_cm"}` required; `{"anchor", "confidence"}` optional | `201 {"place": {...}}` · `400 {"problems": [...]}` · `503` |
| `DELETE /api/v1/places/{id}` | none — the path segment may be an id **or** a name | `200 {"removed": {...}}` · `404` + `suggestion` · `503` |
| `POST /api/v1/places/{id}/go` | `{"at_anchor": true}` — optional, see below | `202 {"accepted", "id", "name", "at_anchor"}` · `404` · `409` · `503` |

`400` bodies carry `problems[]` in the `{path, message, hint}` shape §2's config validator already
uses, so a client shows them without translating: a duplicate name, a heading the format does not
allow, a name with no characters usable in an id (`"///"` slugs to `""`), or the catalogue limit.

**Types are not coerced.** `{"heading_deg": true}` is a `400`, not 1.0 — `true` is an `int` in
Python — and `{"heading_deg": "90"}` is a `400`, not 90 degrees.

**`POST /places/{id}/go` asks; it does not command.** The request is written for the next tick, like
`POST /routines/{id}/run`, and the navigator answers through `place_goal`, which `GET /api/v1/places`
returns as `goal`:

- `at_anchor: true` is the user confirming the dog is standing at the place's anchor. Without it the
  navigator refuses (`anchor_mismatch`) instead of walking a vector measured from somewhere else —
  that arrives as `202` then a refusal in `goal`, because the rule belongs to the navigator, which
  also has to answer for a place taught against a *different* anchor.
- `409` means a walk is already in flight; `current` is the goal that is.

`503` on any of the four means no place navigator is running (`modules.place_navigator.enabled` is
off, so nothing owns the file). That is not an empty catalogue, and the two are worth distinguishing
in a client.

## 9. People

Who the dog has been taught to recognise. `optional/face_recognition.py` owns the identities and
publishes the roster; this route reports it and nothing else.

| Route | Scope | Answers |
|---|---|---|
| `GET /api/v1/people` | `admin` | `{identity, path, people}` |
| `DELETE /api/v1/people/{id}` | `admin` | `{removed: {id, name}, path}` · `404` · `503` |

```jsonc
{"identity": {"enabled": true, "backend": "face_recognition", "reason": null},
 "path": "/home/pi/.houndmind/face_references.json",
 "people": [{"id": "alex_kim", "name": "Alex Kim"}]}
```

`identity` is the module's own account of itself: `backend` is whichever backend is running, and
`reason` is why there is no roster. `path` names the file those identities are kept in — the one
thing a user needs in order to delete them. `people` is `[{id, name}]`, where `id` is the slug of the
name (`"Alex Kim"` → `alex_kim`), the rule a place already follows.

**Nothing biometric is served.** No embedding, no dataset image, no vector and no face box — and
`admin` rather than `state:read` for that reason: an enrolled face is biometric data, so a paired
phone holding `move` does not get to enumerate who lives here (design §6.4). `GET /api/v1/meta` does
not advertise the roster either, because it is unauthenticated: announcing that people are enrolled
would undo the scope one route over.

**Identity off is normal, so it is a `200`.** Identity ships `modules.face_recognition.enabled:
false`, so an error status would make the shipped default a permanent failure on a screen a client
wants to draw — the opposite of `/places`, where "no navigator" is a configuration mistake. What
keeps the two states apart is the block:

```jsonc
{"identity": {"enabled": false, "backend": null,
              "reason": "identity is disabled; enable modules.face_recognition"},
 "path": null, "people": []}
```

`reason` is the module's `disabled_reason` verbatim when it has one — `missing dependency:
face_recognition (dlib)` is a different problem from a switched-off module, and the module is the one
that knows which. `people: []` beside `identity.enabled: false` is never read as "nobody is enrolled".

### Forgetting

```http
DELETE /api/v1/people/alex_kim
→ 200 {"removed": {"id": "alex_kim", "name": "Alex Kim"}, "path": "/home/pi/.houndmind/face/face_references.json"}
```

Admin scope, like the read. **The data goes, not just the name**: for the dlib backend the embeddings
are dropped from the JSON and written back; for OpenCV the person's image directory is deleted and the
LBPH model is retrained from the images that remain, because deleting images without retraining leaves
a model that still recognises the person. Forgotten the last person? The model file is removed, the
label map is emptied, and the recognizer is replaced with an untrained one — face detection continues,
naming stops. `_train_lbph` returns early on an empty dataset, so without that step the old model would
stay trained and keep naming somebody the user had just deleted.

`id` is matched by slug against **every** raw name, not against the one display name the roster shows:
two enrolments that slug alike are one person in `GET /people`, so they are one delete.

- **`404` on a second call** — never a silent success. A client retrying must learn the person was
  already gone, or it will conclude the first attempt failed.
- **`503`** when no identity module is running, with the same `detail` the read route puts in
  `identity.reason`. The asymmetry with the read's `200` is deliberate: a read can honestly report
  "nothing to show", a write cannot honestly report "removed".

This is the route that satisfies the design's *"Deletable"* requirement (`robot-pet-design.md:444`).
That sentence also promises the thumbnail is removed; nothing in this build generates one, so what
exists and what is tested is the embedding and the reference images — thumbnails would be a separate
feature, not a claim this route can honour today.

**Enrolment is not a route.** It is still a runtime command (§20 of `docs/FEATURES_GUIDE.md`), so a
client cannot add a person yet; this route is what a client reads after someone has
([#103](https://github.com/seven-lynx/HoundMind/issues/103)).

