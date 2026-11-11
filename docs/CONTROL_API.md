# HoundMind Control API v1

Status: **contract** — both the web app and the Android app code against this file. Additive
changes only within `v1`; anything breaking requires `v2` and a deprecation window.

Base URL: `http://houndmind.local:8420` (mDNS) or `http://<pi-ip>:8420`.
Everything under `/api/v1` is JSON. `GET /` serves the web app.

---

## 1. Authentication

Two mechanisms, both bearer-style, both required for anything except `/api/v1/meta` and
`/api/v1/health`.

**Device token** — issued at install to `~/.houndmind/api_token` (mode 0600). The web app
receives it once when the browser is opened from the device; Android obtains one by pairing.

**Pairing** — for the Android app and for a second browser:

```
POST /api/v1/pair
{ "code": "483920", "client_name": "Pixel 8" }
→ 200 { "device_token": "...", "scopes": ["state:read","move","config"] }
```

The pairing code is shown on the device (dashboard/log/LED) and is valid for 5 minutes,
single use, and rate-limited to 5 attempts per minute. Never printed to a log at INFO.

**Scopes**

| Scope | Grants |
|---|---|
| `state:read` | `GET /state`, `/events` (WS), `/camera/*`, `/modules` |
| `move` | `POST /command`, `POST /stop`, `POST /mode` |
| `config` | `GET/PATCH /config` (allowlisted keys), `GET /calibration`, `POST /calibration/apply` |
| `admin` | `POST /password`, `POST /pair/rotate`, `GET /logs`, `GET /support-bundle` |

Headers: `Authorization: Bearer <token>`. Query-string tokens are accepted only for the
MJPEG stream (`?token=`), because `<img>` tags cannot set headers. That path is rate-limited
and never grants `config` or `admin`.

---

## 2. Endpoints

| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/meta` | none | api version, device id, board, firmware, capabilities |
| `GET` | `/api/v1/health` | none | liveness only: `{"status":"ok"}` — no detail, no leak |
| `GET` | `/api/v1/state` | `state:read` | full state snapshot (see §4) |
| `GET` | `/api/v1/modules` | `state:read` | every module: loaded/disabled/failed + reason |
| `GET` | `/api/v1/events` | `state:read` | WebSocket telemetry + event stream (§5) |
| `GET` | `/api/v1/camera/stream` | `state:read` | MJPEG, multipart/x-mixed-replace |
| `GET` | `/api/v1/camera/snapshot` | `state:read` | single JPEG |
| `POST` | `/api/v1/pair` | none | exchange a pairing code for a device token |
| `POST` | `/api/v1/pair/open` | `admin` | open a pairing window; returns the 6-digit code once |
| `POST` | `/api/v1/command` | `move` | issue a `Command` (§3) |
| `POST` | `/api/v1/stop` | `move` | unconditional stop; never vetoed, never queued |
| `GET` | `/api/v1/mode` | `state:read` | current mode |
| `POST` | `/api/v1/mode` | `move` | switch `idle\|patrol\|manual\|rest` |
| `GET` | `/api/v1/config` | `config` | effective config (secrets redacted) |
| `PATCH` | `/api/v1/config` | `config` | allowlisted live keys only |
| `GET` | `/api/v1/calibration` | `config` | servo offsets, read-only |
| `GET` | `/api/v1/history?limit=50` | `state:read` | recent commands with their verdicts, and live sessions |
| `GET` | `/api/v1/logs?tail=200` | `admin` | recent log lines, redacted |
| `GET` | `/api/v1/support-bundle` | `admin` | zip: logs, config, module status, events |

Reserved, not implemented in v1: `POST /api/v1/calibration/run` (moves the dog — requires a
physical confirmation on the device), `POST /api/v1/update`.

---

## 3. Commands

```
POST /api/v1/command
Authorization: Bearer <token>
{
  "id": "8f2c1a",            // client-generated, unique per issue
  "action": "forward",       // must exist in the action catalog
  "params": { "speed": 120 },
  "ttl_ms": 300,             // deadman; a motion stops when this elapses
  "source": "client"
}
```

**`202 Accepted`** — it reached the actuators:
```json
{ "accepted": true, "id": "8f2c1a", "expires_at": 1762771200.31 }
```

**`409 Conflict`** — the interlock refused it. This is a *feature*, and the client must show
the reason to the user:
```json
{ "accepted": false, "id": "8f2c1a", "veto": "obstacle", "detail": "12.0 cm at sensor", "retry_after_ms": 0 }
```

**`400 Bad Request`** — malformed or unknown action:
```json
{ "error": "unknown_action", "detail": "forwardd", "suggestion": "forward" }
```

### Action catalog

The authoritative list is `config/actions.jsonc`. The API exposes it in
`GET /api/v1/meta.capabilities.actions`. Baseline set:

| Family | Actions |
|---|---|
| Motion | `forward`, `backward`, `turn_left`, `turn_right`, `stop` |
| Posture | `stand`, `sit`, `lie`, `stretch` |
| Expression | `wag_tail`, `bark`, `head` (`{yaw,pitch,roll}` in degrees) |

### Semantics the client must respect

1. **Motion is a deadman, not a toggle.** A client wanting continuous forward must re-issue
   (or renew the same `id`) at least every `ttl_ms`. If the app dies, the dog stops.
2. **`POST /stop` is never refused** and bypasses the queue. The UI must always have it
   reachable, and must call it on `onPause`/`onStop`.
3. **`409` is not retried blindly.** `veto: "obstacle"` means retrying makes it worse;
   `veto: "tilt"` needs a human.
4. **Ordering is by priority, not arrival.** A `system` command preempts a `client` one.

---

## 4. State snapshot

`GET /api/v1/state` and the WS `state` message share one shape:

```json
{
  "ts": 1762771200.31,
  "device": { "id": "pidog-pi5-a1b2", "board": "pi5", "version": "2026.11.10", "uptime_s": 4212 },
  "mode": "patrol",
  "sensors": {
    "distance_cm": 42.5, "distance_valid": true,
    "touch": "N", "touch_valid": true,
    "sound_direction": 90, "sound_valid": true,
    "pitch_deg": 1.2, "roll_deg": -0.4, "imu_valid": true,
    "battery_v": 7.6, "battery_valid": false
  },
  "actuators": { "last_command": "forward", "since_s": 0.8, "vetoed": false },
  "nav": { "decision": "forward", "confidence": 0.82 },
  "health": { "status": "ok", "cpu_pct": 31.0, "temp_c": 58.2, "mem_used_pct": 44.0 },
  "modules": { "loaded": 11, "disabled": 3, "failed": 0 }
}
```

**Validity flags are mandatory and clients must honour them.** `distance_cm: 42.5` with
`distance_valid: false` means "no measurement" — render "—", never "42 cm". This is the one
rule in the API that a client may not soften.

`GET /api/v1/modules` is the diagnostic view:

```json
{ "modules": [
  { "name": "scanning", "state": "ok", "tick_ms": 3.1, "detail": null },
  { "name": "slam", "state": "disabled", "tick_ms": null, "detail": "missing dependency: rtabmap" }
] }
```

Module states: `ok`, `degraded`, `disabled`, `failed`. A `disabled` module in the shipped
config is normal; a `failed` one is a bug the user should see.

---

## 5. WebSocket

```
GET /api/v1/events            (Upgrade: websocket)
→ client sends: { "type": "hello", "token": "<device_token>" }
← server sends: { "type": "welcome", "scopes": ["state:read","move"] }
```

Server messages:

| `type` | Payload | When |
|---|---|---|
| `welcome` | `scopes`, `device` | on connect, after auth |
| `state` | the §4 snapshot | 10 Hz, and immediately on any change |
| `event` | `{ "name": "...", "data": {...}, "ts": ... }` | on transition |
| `command_ack` | `{ "id", "accepted", "veto"?, "detail"? }` | when a command reaches the actuators |
| `error` | `{ "code", "detail" }` | on a rejected client message |

Event names: `mode_changed`, `command_accepted`, `command_vetoed`, `command_expired`,
`obstacle`, `tilt`, `module_state_changed`, `pairing_window_open`, `low_voltage`.

Client rules:

- **Send `ping` every 2 s.** No ping for 6 s → the server treats the client as gone and
  stops its commands. This is the link-loss check in `ARCHITECTURE.md §5`.
- **Backpressure is drop-oldest.** A slow client loses `state` frames, never `event` frames.
- **One socket per client.** The second connection with the same token evicts the first, with
  an `error` message so the UI can explain it.

---

## 6. Errors

| HTTP | `error` | Meaning | Client action |
|---|---|---|---|
| 400 | `bad_request` | malformed JSON / missing field | fix the request |
| 400 | `unknown_action` | action not in the catalog | show `suggestion` |
| 401 | `unauthorized` | missing or bad token | re-pair |
| 403 | `forbidden` | token lacks the scope | do not retry |
| 404 | `not_found` | unknown path | — |
| 409 | `vetoed` | interlock refused (`veto`, `detail`) | show the reason to the user |
| 429 | `rate_limited` | too many pairing attempts / commands | honour `Retry-After` |
| 503 | `unavailable` | the subsystem is disabled or failed | show module detail |
| 500 | `internal` | a bug | show a support-bundle link |

Every error body is `{ "error": "<code>", "detail": "<human text>", ...extras }`.
`detail` is safe to display verbatim — it must never contain a path, a token, or a stack.

---

## 7. Versioning and compatibility

- `GET /api/v1/meta` returns `{ "api_version": 1, "min_client": 1 }`.
- Adding a field or a route is **not** a breaking change. Removing or renaming one is,
  and requires `v2` with the old route served for at least one release.
- Enum values are additive: clients must handle an unknown `mode` or `module.state` by
  displaying it read-only rather than crashing.
- Both clients declare the `api_version` they were built against in their `User-Agent`;
  the server logs mismatches so drift is visible before a user reports it.
- `docs/CONTROL_API.md` is the source of truth. The route list is asserted by a test, so a
  route that exists in code but not here fails CI.