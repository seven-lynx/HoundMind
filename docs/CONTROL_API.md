# HoundMind Control API v1

Status: **contract** — the web app and the Android app code against this file. Additive changes
only within `v1`; anything that removes or renames a field requires `v2` and a deprecation window.
Version: v2026.01.18 • Author: 7Lynx
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
| `admin` | `POST /pair/open`, `GET /logs`, `GET /support-bundle` — device token only |

Header: `Authorization: Bearer <token>`. A query-string token is accepted **only** on the two camera
routes, because an `<img>` tag cannot set a header; those routes require `state:read` and never grant
`config` or `admin`.

---

## 2. Endpoints

| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/meta` | none | `api_version`, `min_client`, `device_id`, `board`, `uptime_s`, `capabilities` |
| `GET` | `/api/v1/health` | none | liveness only: `{"status":"ok"}` — no detail, no leak |
| `GET` | `/api/v1/state` | `state:read` | full state snapshot (see §4) |
| `GET` | `/api/v1/modules` | `state:read` | every module: `ok`/`degraded`/`disabled`/`failed` + reason |
| `GET` | `/api/v1/events` | token in `hello` frame | WebSocket telemetry + event stream (§5) |
| `GET` | `/api/v1/camera/stream` | `state:read` (`?token=`) | MJPEG, multipart/x-mixed-replace |
| `GET` | `/api/v1/camera/snapshot` | `state:read` (`?token=`) | single JPEG |
| `POST` | `/api/v1/pair` | none | exchange a pairing code for a client token |
| `POST` | `/api/v1/pair/open` | `admin` | open a pairing window; returns the 6-digit code |
| `POST` | `/api/v1/command` | `move` | issue a command (§3) |
| `POST` | `/api/v1/stop` | `move` | unconditional stop; never vetoed, never queued |
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

### The command vocabulary

`config/actions.jsonc` is the action **catalog**: activity groups (`idle`, `alert`, `avoid`, `play`,
`rest`, `patrol`, `explore`, `interact`, `custom`) of `pidog` ActionFlow names, which the behavior
module draws from. The API accepts the smaller, fixed **command vocabulary** in
`kernel/commands.py::KNOWN_ACTIONS`:

| Family | Actions |
|---|---|
| Motion | `forward`, `backward`, `turn_left`, `turn_right`, `stop` |
| Posture | `stand`, `sit`, `lie`, `stretch` |
| Expression | `wag_tail`, `bark`, `head` (payload `{"yaw", "pitch", "roll"}` in degrees) |

Producers and the catalog spell motion with spaces (`"turn left"`, `"wag tail"`); the vocabulary is
underscored, and `kernel/commands.py::canonical_action` is the only translation. The catalog is **not**
served over HTTP — a client that needs it reads `config/actions.jsonc` from the repository, because
`GET /meta`'s `capabilities` is a list of *surfaces* (`command`, `events`, `mode`, `state`, plus
`camera` and `pairing` when available), not a list of actions.

### Semantics the client must respect

1. **Motion is a deadman, not a toggle.** A client wanting continuous forward must re-issue at least
   every `ttl_ms`. If the app dies, the dog stops — and the deadman starts when the device received
   the command, so a command that sat in a tunnel does not run when it finally arrives.
2. **`POST /stop` is never refused** and bypasses the queue. The UI must always have it reachable, and
   must call it on `onPause`/`onStop`.
3. **`409` is not retried blindly.** `veto: "obstacle"` means retrying makes it worse; `veto: "tilt"`
   needs a human to right the dog and clear the latch; `veto: "mode"` means the runtime is in `rest`.
4. **Ordering is by priority, not arrival.** `system` > `watchdog` > `client` > `navigation` >
   `behaviour` (`kernel/commands.py:36`). A `system` command preempts a `client` one, and the
   preempted client can see it in `actuators.displaced`.

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
  "health": { "status": "ok", "cpu_pct": 31.0, "temp_c": 58.2, "mem_used_pct": 44.0, "reasons": [] },
  "supervisor": { "holding": false, "reason": null, "restarts": [], "failed": [] },
  "modules": { "loaded": 11, "disabled": 3, "failed": 0 }
}
```

`ts` is the runtime's **monotonic** clock, not epoch seconds: compare it to other timestamps in the
same stream, never to wall time. Device identity and version live in `GET /meta`, not here.

`actuators.source` names the producer that won the tick (`system`, `watchdog`, `client`,
`navigation`, `behaviour`). `actuators.displaced` counts the intents a higher-priority one overrode
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
`command_vetoed`, `command_expired` and `pairing_window_open`. A command's *outcome* is the
synchronous reply to `POST /command` (§3) — there is no separate `command_ack` frame; the events are
the broadcast, not the acknowledgement. Clients must tolerate an unknown `name` and ignore it.

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
- Enum values are additive: a client must handle an unknown `mode` or module `state` by displaying it
  read-only rather than crashing.
- `docs/CONTROL_API.md` is the source of truth. `tests/test_api_routes.py` parses §2 and compares it
  to the route table in `services/api.py`, so a route that exists in one and not the other fails CI.
  Change both, in the same commit.