# HoundMind Control API v1

Status: **contract** — the web app in `services/web/` and the Android app, **HoundMind Remote**, code
against this file. HoundMind Remote lives in its own repository (#274): this tree publishes the contract
and the fixtures, not the app. Additive changes only within `v1`; anything that removes or renames a
field requires `v2` and a deprecation window.
Pairs with: `src/houndmind_ai/services/api.py` (the route table), `docs/FEATURES_GUIDE.md` [§25](FEATURES_GUIDE.md#25-wifi-localization--removed)

Base URL: `http://<pi-ip>:8420`, or `http://<hostname>.local:8420` — the name discovery actually
publishes. `services/discovery.py::_default_host` returns `<whatever the Pi is called>.local`, so on a
stock Bookworm card that is `raspberrypi.local` until the host is renamed; nothing in
`scripts/install_houndmind.sh`, `scripts/installer_core.py` or this tree's docs changes the hostname,
and `houndmind.local` resolves only on a device an owner renamed by hand (#294). The device advertises
**one** mDNS record — `houndmind._houndmind._tcp.local`, gated by `api.discovery_enabled` (on by
default) — carrying its host and port, so a client can find it by name. When discovery is off or
blocked, the address is whatever `hostname -I` reports on the device. Everything under `/api/v1` is
JSON; `GET /` serves the web app that ships inside the package.

**The web app's assets are versioned at serve time.** `GET /` rewrites each `/static/...` URL to carry
`?v=<package version>`, and `/static/` answers `Cache-Control: no-cache`. A returning browser
revalidates instead of assuming its copy is current, so an upgrade cannot leave yesterday's `app.js`
in front of today's API — the failure that made a camera pane report "enable a vision module" when the
real cause was a stale request shape (#102). Treat the asset URLs as opaque: read them from `GET /`.

The route table in [§2](#2-endpoints) is asserted against the code by `tests/test_api_routes.py`, which parses this
file. A route that exists in code and not here — or here and not in code — fails CI.

---

## Contents

1. [Authentication](#1-authentication) — the token, scopes, pairing, camera tickets
2. [Endpoints](#2-endpoints) — the full route table with scopes
3. [Commands](#3-commands) — the vocabulary, the semantics, dry runs
4. [State snapshot](#4-state-snapshot) — everything `GET /state` carries
5. [WebSocket](#5-websocket) — the `hello` frame and the event stream
6. [Errors](#6-errors) — status codes and the `error` body
7. [Versioning and compatibility](#7-versioning-and-compatibility)
8. [Places](#8-places)
9. [People](#9-people)
10. [Calibration](#10-calibration) — the read-only run route
11. [Conformance corpus](#11-conformance-corpus) — recorded decisions every client must reproduce

---

## 1. Authentication

Two mechanisms, both bearer-style. Everything requires a token except `/api/v1/meta`,
`/api/v1/health` and `/api/v1/pair`, which is the exchange that *produces* a token.

`/api/v1/whoami` is the one route that requires a token and **no particular scope**. It reports the
scopes a token holds, so naming one would refuse the caller who most needs the answer — a client whose
token cannot read state, config or logs. It is the HTTP twin of the WebSocket `welcome` frame
([§5](#5-websocket)): same `device`/`scopes` shape, no socket required.

**This is plaintext HTTP.** Nothing on port 8420 is encrypted: the device token, every command and
every camera frame cross the LAN in the clear. The token *is* the security boundary, so anyone who can
observe the network — or read a single access log — holds `move`, `config`, and `admin` if they catch
the device token itself. Keep the dog on a network you trust, or close the door:

- `settings.api.host: "127.0.0.1"` and an SSH tunnel: `ssh -L 8420:localhost:8420 <user>@<pi>`.
- A firewall rule that admits only your own devices to port 8420.
- A TLS-terminating reverse proxy in front, if you need to reach it from beyond the LAN.

**The device advertises itself, and the advertisement is public.** With `settings.api.discovery_enabled`
(the default) the control plane publishes one mDNS record so a client can resolve a name instead of
an address (`#38`). Its TXT payload is `api_version`, `min_client` and `scheme` - a subset of what the
unauthenticated `/api/v1/meta` already reports, with no token, no device secret and no location.
Anyone on the LAN can read it, which is exactly as much as they can read from `/api/v1/meta` today.

**TLS is available and off by default.** `settings.api.tls_enabled: true` serves HTTPS with a
self-signed certificate generated on first start for this device — `docs/INSTALL.md` has the trust
steps for a browser and a phone. A client that cannot be taught to trust it (the Android app is one
today) stays on the plaintext path above, with those workarounds. **Do not port-forward 8420 to the
internet** either way.

**Two console features need that secure context** (#176, #177): the installable app shell (a service
worker at `/sw.js`, registered only when `window.isSecureContext`) and desktop notifications for
safety events. On plain http both are skipped rather than broken: no worker is registered, no
permission is requested, and everything else on this page behaves exactly as documented. `/sw.js` and
`/static/*` are served without a token, like the assets they are.

**One console, one origin — or an allowlist.** The app is served by the plane it controls, so a second
dog is a second origin and the header's device picker *navigates* to it (#179). Navigating needs no
policy at all, which is why it shipped first. Talking to another plane **in place** is now possible
too, but only when the operator says so: `settings.api.cors_origins` (empty by default) names the
origins whose pages may read this plane, and a request from a listed origin gets
`Access-Control-Allow-Origin` echoed back with `Vary: Origin`; a preflight `OPTIONS` is answered
`204` without a token, because a browser never sends `Authorization` on one. An origin that is not
listed gets no header at all — the response is still served, the browser simply refuses to hand it
to the page (#202). `*` is **ignored**, not honoured: the token is the boundary, and a wildcard would
let any page on the LAN read whichever dog it holds a token for. Mixed content is still a hard wall:
an `https://` console cannot call an `http://` plane, so put both on the same scheme. The remembered
device list is client-side only; nothing about it is sent anywhere.

**Device token** — generated on first start by `services/auth.py::TokenStore` and written to
`~/.houndmind/api_token`, directory `0700`, file `0600`. It is never in `config/settings.jsonc`,
never in a log line, and never in this repository. The web app does not receive it automatically: on
first load it shows a token field and you paste it once (`services/web/index.html`). Read it on the
device, and paste exactly what this prints:

```bash
# the web console's token field takes this string
grep -m1 . ~/.houndmind/api_token

# and confirm it is still private: expect "600" and the path
stat -c '%a %n' ~/.houndmind/api_token
```

`grep -m1 .` rather than `cat`: the file has no trailing newline, and this prints the token as one
pasteable line. Do not paste the output into an issue, a chat window or a screenshot - on port 8420
that string is the whole security boundary.


**Pairing** — for HoundMind Remote and for a second browser:

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
| `config` | `GET`/`PATCH /config`, `GET /calibration`, `POST /calibration/run` |
| `admin` | `POST /pair/open`, `GET`/`POST /people`, `DELETE /people/{id}`, `GET /logs`, `GET /support-bundle` — device token only |

Header: `Authorization: Bearer <token>`. The two camera routes also accept `?ticket=<ticket>` because an
`<img>` tag cannot set a header: mint one with `POST /api/v1/camera/ticket` (`state:read`), it is valid
for 60 seconds and **single use**, and it buys `state:read` on one frame and nothing else. The device
token is **not** accepted in a query string — it used to be, and that put the credential for `move`
and `config` into browser history and access logs (`#18`).

Both camera rows declare that requirement in `services/api.py::ROUTES` as the `HANDLER_SCOPE` marker,
not as `None`: in that table `None` means "public on purpose", and the camera routes are not. The
check happens inside the handler because a ticket has to be claimed there, and a visible marker is
what stops the guard from looking redundant (`#39`).

---

## 2. Endpoints

| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/api/v1/meta` | none | `api_version`, `min_client`, `scheme`, `device_id`, `board`, `board_model`, `profile`, `uptime_s`, `capabilities` |
| `GET` | `/api/v1/health` | none | liveness only: `{"status":"ok"}` — no detail, no leak |
| `GET` | `/api/v1/whoami` | any valid token | the caller's `device` name, `scopes` and `kind` — the same shape as the `welcome` frame, so a client can say what its token cannot do before a request fails (#168) |
| `GET` | `/api/v1/state` | `state:read` | full state snapshot (see [§4](#4-state-snapshot)) |
| `GET` | `/api/v1/scan` | `state:read` | the last head sweep verbatim — `mode` plus `forward`/`right`/`left`, or `mode` plus `angles` `{yaw: cm}`; `{"scan": null}` before the first one (#169) |
| `GET` | `/api/v1/map` | `state:read` | the occupancy grid as `[ix, iy, hits]` cells with `cell_size_cm`, `count` and `truncated`, plus `document`, the versioned home map (see below); `{"map": null}` when no cell has been filled (#175) |
| `PUT` | `/api/v1/map` | `config` | replace the home-map document: body `{"document": {...}}`, judged by the same validator that loads the file; `meta.rev` must match or the answer is `409` with the current one (M1) |
| `GET` | `/api/v1/modules` | `state:read` | every module: `ok`/`degraded`/`disabled`/`failed` + reason |
| `GET` | `/api/v1/repertoire` | `state:read` | every action this dog can run, with its class and params ([§3](#3-commands)) |
| `GET` | `/api/v1/routines` | `state:read` | every routine the runner loaded, the files it refused, and the run in progress ([§3](#3-commands)) |
| `POST` | `/api/v1/routines` | `config` | write one routine file, judged by the loader's own `check_routine`; `?replace=true` to overwrite ([§3](#3-commands)) |
| `GET` | `/api/v1/places` | `state:read` | every place the file holds, the entries it refused, and the walk in progress ([§8](#8-places)) |
| `GET` | `/api/v1/people` | `admin` | enrolled people: ids and names only, never an embedding ([§9](#9-people)) |
| `POST` | `/api/v1/people` | `admin` | teach one face: `202` with the handle to poll; a refusal lands in `last_enroll` ([§9](#9-people)) |
| `DELETE` | `/api/v1/people/{id}` | `admin` | forget one person: the embedding and every reference face go, not just the name ([§9](#9-people)) |
| `GET` | `/api/v1/decisions?limit=50` | `state:read` | the last N decision records, oldest first ([§4](#4-state-snapshot)); 503 when the feed is not running |
| `GET` | `/api/v1/events` | token in `hello` frame | WebSocket telemetry + event stream ([§5](#5-websocket)) |
| `GET` | `/api/v1/camera/stream` | `state:read` (`?ticket=`) | MJPEG, multipart/x-mixed-replace |
| `GET` | `/api/v1/camera/snapshot` | `state:read` (`?ticket=`) | single JPEG |
| `POST` | `/api/v1/camera/ticket` | `state:read` | mint a single-use camera ticket: `{ticket, expires_in}` |
| `POST` | `/api/v1/pair` | none | exchange a pairing code for a client token |
| `POST` | `/api/v1/pair/open` | `admin` | open a pairing window; returns the 6-digit code |
| `POST` | `/api/v1/command` | `move` | issue a command ([§3](#3-commands)) |
| `POST` | `/api/v1/stop` | `move` | unconditional stop; never vetoed, never queued; sets the mode to `rest` and ends a running routine |
| `POST` | `/api/v1/routines/{id}/run` | `move` | start one routine; optional `{"dry_run": true}` ([§3](#3-commands)) |
| `POST` | `/api/v1/places` | `config` | create one place; a refused body is `400` with `problems[]` ([§8](#8-places)) |
| `DELETE` | `/api/v1/places/{id}` | `config` | forget one place by id or name; a second call is `404` ([§8](#8-places)) |
| `PATCH` | `/api/v1/places/{id}` | `config` | correct a place's `name`, `heading_deg`, `distance_cm` or `anchor`; the `id` cannot change ([§8](#8-places)) |
| `POST` | `/api/v1/places/{id}/go` | `move` | ask the dog to walk to one place; optional `{"at_anchor": true}` ([§8](#8-places)) |
| `GET` | `/api/v1/mode` | `state:read` | current mode |
| `POST` | `/api/v1/mode` | `move` | switch `idle` \| `patrol` \| `manual` \| `rest` |
| `GET` | `/api/v1/config` | `config` | effective config, secrets redacted |
| `PATCH` | `/api/v1/config` | `config` | four live keys only, listed below |
| `GET` | `/api/v1/calibration` | `config` | servo offsets, read-only |
| `POST` | `/api/v1/calibration/run` | `config` | run one read-only calibration request ([§10](#10-calibration)) |
| `GET` | `/api/v1/history?limit=50` | `state:read` | recent commands with verdicts, and live sessions |
| `GET` | `/api/v1/logs?tail=200&level=ERROR&contains=<text>` | `admin` | recent log lines, redacted; `level` (one of `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`) and `contains` (case-insensitive substring) are applied by the server across a bounded scan, not to the fetched tail |
| `GET` | `/api/v1/support-bundle` | `admin` | zip: meta, state, modules, redacted config, audit, sessions |

**The four modes gate sources, not verbs.** `services/api.py` validates the name; the table in
`kernel/commands.py:113-122` decides what each one admits:

| Mode | Sources that may command motion | Means |
|---|---|---|
| `idle` | every source | autonomy on: behaviour and the navigator may drive |
| `patrol` | every source | the navigator roams on its own |
| `manual` | client, routine, place, watchdog, system | a hand on the wheel: autonomy may not |
| `rest` | watchdog and system | parked: only the two sources that exist to end a motion |

`stop` is never gated by a mode, and any valid mode may be set from any other — including `rest` →
`idle`, which hands the dog back to autonomy with no confirmation step and no intermediate state. An
unknown name is a `400` listing the four accepted values, and each change is published as a
`mode_changed` event on `/api/v1/events`.

**`POST /stop` is a mode change as well as a stop.** It sets `rest`, because a stop that only cleared
the motion in flight was overwritten on the next tick: under `idle` the behaviour and the navigator
publish a fresh intent about 100 ms later (#333). The answer carries `{"accepted": true, "action":
"stop", "mode": "rest"}`, and leaving `rest` is the operator's next act. A client that wants to stop
motion *without* parking issues a `stop` command through `/command`, which every mode admits
(`act/gateway.py::_vet`) — that is what the console's pad release does.

`PATCH /config` writes only `behavior.action_cooldown_s`, `led.brightness`,
`motors.min_action_interval_s` and `navigation.safe_distance_cm` (`services/api.py:81`), each re-read
every tick by its module. Any other key is refused with the live list in the body, because a config
write that changes nothing is the bug this API exists to avoid.

The `logs` response is `{"lines": [...], "filtered": bool, "truncated": bool}`. `truncated` is the
honest half of a filter: it says the walk stopped at its 4 MiB budget before reaching the start of the
file, so `lines: []` means "no match in that window", not "no match in the log". An unknown `level` is
a `400` carrying the accepted set, because a misspelled filter and an empty result are different
answers. A traceback's continuation lines carry no level, so `level` keeps record lines only; `contains`
still matches them.

The `map` response is `{"map": {"cell_size_cm", "cells", "count", "truncated"}, "grid_enabled"}`.
Cells are `[ix, iy, hits]` **in the mapper's own cell indices** — `ix` grows to the dog's left, `iy`
forward, exactly what `mapping/mapper.py::_ingest_into_grid` writes — so a client scales them by
`cell_size_cm` and does not re-derive a projection the producer might disagree with. The list is
capped at 4000 cells and keeps the ones with the most hits; `count` is the uncapped total and
`truncated: true` means "the rest is on the device, not in this response", because an empty corner of
a truncated map is not unmapped space.

The same response carries `document` (M1): the versioned home map, in the shape `PUT /map` takes
back. One document, two spellings, and the contract names both. On the **wire** `cells` is flat and
`samples` is a count; in the **file** the cells sit under `grid` and `samples` is the log. A client
never receives that log, so it cannot send one, and `PUT /map` keeps the file's window. `meta` is
carried verbatim either way, which is what reserves `meta.floor` for a multi-floor map without a
version bump. `document` is `null` when no map was loaded and none was ever saved — a third fact
beside `map: null`, and a client that cannot tell it from an empty map draws a room nobody has seen.

Every coordinate in `document` is centimetres from the map origin with `x` left-positive and `y`
forward-positive — the mapper's own axes (`mapping/mapper.py::_ingest_into_grid`) — so a console
scales the cells and converts nothing.

`PUT /map` replaces the document under the `config` scope and bumps `meta.rev`. The body is
`{"document": {...}}` carrying the generation it read; a stale generation is a `409` with the current
`rev` in the body and nothing is written, so two consoles never overwrite each other silently. A
refused document is a `400` with `problems[]` (the shape `POST /places` already uses), judged by
`mapping/home_map.py::validate_document` — the same function that loads the file, which is why a
document this route accepts is one the next start can read. Writes are atomic, and a scan snapshot
every `home_map_save_interval_s` carries the user's sections and the `rev` forward, so the map's own
log never erases an edit.

A value the config **file** would have rejected is refused too: the write is checked against the same
section schema (`kernel/config_schema.py::validate_settings_section`), so a `400` carries
`invalid: [{key, problems: [{path, message, hint}]}]` and nothing is stored. A value that got through
would otherwise fail the module that reads it on every tick, which is a worse version of the same bug.

The change is **persisted into `config/settings.jsonc`** (#174) when the runtime read one, and both
happen or neither does: the write goes in first, and only then is the live table updated. The edit is
surgical — the value's bytes are replaced and every comment in the file survives — so the file still
reads as the document it was. A response carries `persisted: true` when the file was written and
`persisted: false` only for a runtime with no settings file (a `Config` built in code), which then
applies in memory as before.

Three refusals are specific to this:

- `409 conflict`, `detail` naming the file, when `settings.jsonc` changed on disk since the runtime
  started. The edit made on the device wins; restart to pick it up, then send the change again. The
  runtime does not overwrite an edit it did not make.
- `409 conflict` when a live key is not **written** in the file (it exists only as a default). Add the
  key there once; the writer will not invent a line and guess its indentation.
- `500 internal` if the rewrite would not load or would not land on the asked-for value. Nothing is
  written in that case: the rewritten text is proved before it replaces the file.

**Reserved, not implemented in v1:** `POST /api/v1/update`. There is no route for face
enrollment or SLAM map download; both are runtime-context commands (see `FEATURES_GUIDE.md`).
`POST /api/v1/calibration/run` is implemented, and it is **read-only** — see [§10](#10-calibration).

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
`"expired"`, `"tilt"`, `"low_voltage"`, `"obstacle"` or `"mode"` ([§4](#4-state-snapshot) documents the state snapshot
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
the raw catalog still reads `config/actions.jsonc` from the repository — `GET /api/v1/meta`'s `capabilities`
is a list of *surfaces* (`command`, `events`, `mode`, `state`, plus `camera`, `pairing` and
`routines` when available), not a list of actions.

### Semantics the client must respect

1. **Motion is a deadman, not a toggle.** A client wanting continuous forward must re-issue at least
   every `ttl_ms`. If the app dies, the dog stops — and the deadman starts when the device received
   the command, so a command that sat in a tunnel does not run when it finally arrives.
2. **`POST /stop` is never refused**, bypasses the queue, and **parks** the runtime in `rest`. The UI
   must always have it reachable, and must call it on `onPause`/`onStop`. It ends a running routine too,
   so a stop is a stop — and it clears the mode that would let autonomy re-issue the motion on the next
   tick. A motion stop that must leave the mode alone is a `stop` command through `/command`.
3. **`409` is not retried blindly.** `veto: "obstacle"` means retrying makes it worse; `veto: "tilt"`
   needs a human to right the dog and clear the latch; `veto: "mode"` means the runtime is in `rest`.
4. **Ordering is by priority, not arrival.** `system` > `watchdog` > `client` > `navigation` >
   `place` > `routine` > `behaviour` (`kernel/commands.py:37`). A `system` command preempts a `client`
   one, and the preempted client can see it in `actuators.displaced`. A `place` goal — "go to the
   kitchen" — sits just under `navigation`, so a hazard always wins the tick and the goal resumes when
   it clears; a `routine` sits under the goal, and over idle behaviour.

### Routines

A routine is a JSON file of steps the runner loaded at boot — one file per routine, from
`settings.routines.dir` (`FEATURES_GUIDE.md` [§7](FEATURES_GUIDE.md#7-behavior)). These routes expose what the dog **loaded**, not
what is on disk right now: a file added since boot appears after a restart, and a file the validator
refused is listed with the reason instead of being hidden.

`POST /api/v1/routines` — `config` — writes one file, and it is the same validator that judges it:

```json
{
  "id": "morning_greeting", "name": "Morning greeting", "version": 1,
  "allow_locomotion": false,
  "steps": [ { "action": "sound", "params": { "name": "woohoo" } }, { "action": "sit" } ]
}
```

`201` — the file is written atomically and named `<id>.json`:

```json
{ "routine": { …as sent… }, "path": "/home/pi/.houndmind/routines/morning_greeting.json",
  "reload_required": false }
```

- **`400`** — the document is not a legal routine; `problems[]` is the loader's own list (unknown
  action, a locomotion step without the opt-in, a missing `steps`, too many steps).
- **`409`** — the id is already claimed. Creating and replacing are different requests: an existing
  `<id>.json` needs `?replace=true`, and an id **another** file declares is always refused, because a
  second file with that id is refused at load.
- **`503`** — no runner is loaded, so there is no directory to write into.

**The write is playable immediately.** The route sets `routine_reload`, and the runner re-reads the
directory on its next tick, so `GET /routines` and `POST /routines/{id}/run` see the new file without
a restart. `reload_required` stays in the answer as `false` for clients written against the older
shape. One case is deliberately deferred: if a run is **in flight**, the reload waits until it ends —
`_advance` looks the routine up every tick, so swapping the catalogue mid-walk would change the steps
under the run. The request stays set and applies the moment the run finishes (#196).

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
               "detail": null, "started_at": 4212.3 }
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

The route waits up to half a second for the runner's own answer before it replies, so a start the
runner declines comes back as the `409` below rather than a `202` a client has no way to retract. A
request that has not been looked at yet — no runner ticking, or a loop slower than the wait — keeps
the `202`, because a queued request is not a refused one.

- **`400`** — `dry_run` was not a real boolean (`"true"` is refused, never coerced).
- **`404`** — no routine by that id was loaded; `suggestion` carries the closest name.
- **`409`** — a run is in progress, a request is already queued for the next tick, or the runner
  declined this start; `detail` carries the runner's own reason and `current` is the run that
  blocked it, or `null`.
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
  "safety": { "active": false, "emergency_stop": false },
  "nav": { "decision": "forward", "confidence": 0.82, "heading_calibrated": true },
  "localization": {
    "tier": "dead_reckoning", "frame": "odometry",
    "pose": { "x": 118.4, "y": -32.0, "yaw_deg": 92.5 },
    "confidence": 0.94, "age_s": 6.2, "reason": "no SLAM backend (stub)"
  },
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
    "started_at": 4212.3
  },
  "scan": { "mode": "sweep", "timestamp": 4211.9, "samples": 9 },
  "health": { "status": "ok", "cpu_pct": 31.0, "temp_c": 58.2, "mem_used_pct": 44.0, "reasons": [], "high_water": { "temp_c": 61.4, "mem_used_pct": 51.0 } },
  "supervisor": { "holding": false, "reason": null, "restarts": [], "failed": [], "exempt": { "api": "exempt by settings.watchdog.ignore_modules" } },
  "modules": { "loaded": 11, "disabled": 3, "failed": 0 },
  "perf": { "tick_hz_target": 5, "tick_hz_actual": 4.98, "tick_ms": 41.2, "tick_overrun_ms": 0.0, "loop_delay_ms": 200.0 },
  "session": { "started_at": 4212.0, "trace_id": "trace123", "previous_ending": "reboot", "previous_started_at": 4000.1, "previous_pid": 1187, "boot_changed": true, "throttled": "0x50000" }
}
```

`ts` is the runtime's **monotonic** clock, not epoch seconds: compare it to other timestamps in the
same stream, never to wall time. Device identity and version live in `GET /api/v1/meta`, not here.

`decision` is the tick's decision record (`kernel/decisions.py`) — the same object
`GET /api/v1/decisions` returns a list of. `intent` and `source` name the intent that won the tick;
`vetoes` names every intent that lost and why, where `reason` is the interlock's own veto
(`obstacle`, `tilt`, `low_voltage`, `expired`, `unknown_action`) or `mode`/`precedence` for an intent
the mode policy dropped or a higher rank displaced; `inputs` carries the readings the decision used,
**with their validity flags**. It is `null` until the gateway's first tick. `confidence` is `null` —
never `0.0` — when nothing measured it. A client that diffs on `ts` sees one new record per tick; the
WS `decision` event ([§5](#5-websocket)) fires only when the *choice* changes, so treat the two as different
cadences over the same object.

`routines` is the run the runner is playing — the **same object** `GET /api/v1/routines` returns as
`current` — or `null` before the first run and after a restart. `state` is `running`, `done`,
`stopped` or `refused`; a refused run keeps the `veto` and `detail` that ended it, so a client shows
"stopped at step 2: obstacle" instead of an unexplained halt. It is rewritten every tick while the run
is live, whereas the WS `routine` event ([§5](#5-websocket)) fires only when the run *moves*: a new step, a new state,
or a new veto. `started_at` is on the same monotonic clock as `ts`, so `ts - started_at` is how long
the run has been going - a duration, not a wall-clock moment to display.

`scan` is the **summary** of the last head sweep: `mode` (`sweep` or `three_way`), the reading's
`timestamp` (epoch seconds, from the scanner) and how many bearings it holds. It is `null` until the
scanner has finished its first sweep, and stays `null` while `modules.scanning` is off. The bearings
themselves are **not** here: a sweep is one reading per angle — up to 181 — and this snapshot is sent
at `api.state_hz` to every client, so the samples live behind `GET /api/v1/scan` and a client fetches
them when `timestamp` moves (#169).

`session` is how this run started and how the one before it ended (#214). `started_at` is epoch
seconds, because it describes a moment in the past rather than a point on this stream's clock;
`previous_ending` is `unclean` (the process died, the machine did not), `reboot` (the machine went
away under it) or `unknown` (a marker no build could attribute), and it is **`null` when the last
session closed itself** - a clean stop removes the marker, so absence is the clean case rather than
a fourth value. `boot_changed` and `throttled` are only filled in for a reboot: `throttled` is
`vcgencmd get_throttled` read *at start*, and bits 16-18 are sticky for the life of the boot, which
is what makes it an under-voltage fingerprint. The block is `null` when nothing recorded a session
- a tool or a test that built a runtime without `main()`. It reports; it never resumes: motion does
not survive a restart.

`actuators.source` names the producer that won the tick (`system`, `watchdog`, `client`,
`navigation`, `routine`, `behaviour`). `actuators.displaced` counts the intents a higher-priority one overrode
this tick — a client that pressed forward and sees `source: "watchdog"` can tell "someone else is
driving" from "the dog ignored me". `actuators.veto` carries the reason the last command was refused,
and `actuators.tilt_latched` reports the latch state the client must surface.

`safety` answers the narrower question `actuators` cannot: is the safety module overriding right now
(`active`), and is the emergency stop set (`emergency_stop`). Both are `false` while
`modules.safety` is disabled, which is the shipped default — that is the module not running, not the
dog reporting itself safe, and a client must not render the two the same way.

`nav.heading_calibrated` says whether the gyro bias was measured this run
(`navigation/orientation.py`). A turn made on a calibrated heading and one made on a drifting heading
look identical in `nav.decision`, so a client that shows heading quality needs the flag.

`nav.confidence` is the share of the navigator's confirm window that voted for the direction it
picked — the one number the scan actually measures. It is `null` when the tick decided without a
scan (a clear-path streak, for instance), and it is never derived from `score`: a scan score ranks
one opening against another and is not a probability, so a client that wants "how sure is it" reads
this field and a client that wants "how good is the gap" reads the decision's `score`.

`health.high_water` is the session's peak for each health signal (`temp_c`, `gpu_temp_c`, `load_1m`,
`mem_used_pct`), which is what a support bundle wants: the average hides the thermal spike that
throttled vision. It is `{}` while `modules.health` is disabled.

`perf` is the loop against its budget, in milliseconds — the same unit as `tick_ms` on
`/api/v1/modules`. `tick_ms` is the EMA of one tick's duration (not the worst one),
`tick_overrun_ms` how far past the budget the last tick ran, and `loop_delay_ms` the target interval.
Every field is `null` before the loop's first tick, because `0` would read as a free loop;
`tick_hz_actual` stays `null` until there are two ticks to compare.

`supervisor` is the watchdog's own state: whether it is holding motion (`holding` + `reason`, which is
`null` or a staleness reason), which modules it asked the runtime to restart, and which it has given
up on. `holding: true` never means the dog was posed — recovery is stop-and-report.

`exempt` names the modules the watchdog is configured never to restart, with the reason, so
"exempt on purpose" is distinguishable from "healthy". The shipped `settings.watchdog.ignore_modules`
exempts `api`, because restarting the control plane re-binds the port and drops every WebSocket
client mid-request. That exemption no longer hides a plane whose thread has exited: the module checks
its own thread each tick, publishes `api_alive`, and asks the runtime to restart it (#330). A plane
that hangs while its thread stays alive is still not restarted by anything (#338).

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
→ client sends: { "type": "hello", "token": "<device_token>", "logs": true }
← server sends: { "type": "welcome", "data": { "scopes": [...], "device": "<name>", "session": {...}, "logs": <bool> } }
```

Nothing sent before `hello` is answered, and a failed `hello` closes the socket. `logs` is optional
and asks for the live log channel; `welcome.logs` says whether it was granted.

Server frames:

| `type` | Payload | When |
|---|---|---|
| `welcome` | `data`: `scopes`, `device`, `session`, `logs` | once, after a successful `hello` |
| `state` | `data`: the [§4](#4-state-snapshot) snapshot | `api.state_hz` (default 10 Hz) |
| `event` | `data`: `{ "name", "data", "ts" }` | on transition |
| `log` | `data`: `{ "lines": [...] }`, newest batch only | only while the socket asked for `logs` and holds `admin` (#170) |
| `pong` | `ts` | in reply to a client `ping` |
| `error` | `error` (code), `detail` (optional) | on a rejected message, or `superseded` |

The `log` channel carries the same data as `GET /api/v1/logs`, read from the same file, covering the
lines written since the socket connected. It is granted only to a token holding `admin`; a token
without it keeps its socket and gets `welcome.logs: false`, because taking telemetry away from a
paired phone to punish it for asking about logs would be the wrong trade. `log` frames are
**droppable**: the newest batch replaces an undelivered one, so a client that cannot keep up loses
lines rather than being disconnected — the opposite rule to `event`, and the reason the two classes
are separate.

Client frames: `{"type": "hello", "token": "..."}` then `{"type": "ping"}`. Anything else is an
`error` with code `bad_request`.

Every frame comes from one place. The hub's own pump runs on the aiohttp loop and calls
`publish_event` (`services/stream.py`) when something it watches has changed: a module that has
something to say writes it into the context, and the pump is what turns that into a frame. There
is no second, thread-agnostic entry point to choose between, so a producer never has to reason
about which thread it is on.

The only event names the server publishes today are `mode_changed`, `command_accepted`,
`command_vetoed`, `command_expired`, `pairing_window_open`, `decision` and `routine`. The last two
carry the [§4](#4-state-snapshot) `decision` and `routines` blocks and are sent only when the object changes — a new
winner, a new refusal, a new mode or state for the decision; a new step, a new state or a new veto for
a routine — never on every tick, because this channel is never dropped and a client that falls behind
it is disconnected. A command's *outcome* is the synchronous reply to `POST /command` ([§3](#3-commands)) — there is
no separate `command_ack` frame; the events are the broadcast, not the acknowledgement. Clients must
tolerate an unknown `name` and ignore it.

Client rules:

- **Send `ping` every 2 s.** No ping for `api.link_loss_s` (default 6 s) and the server treats the
  client as gone and stops its command, publishing `command_expired` with `reason: "link_loss"`.
- **Backpressure is drop-oldest for `state` and `log`, fatal for `event`.** A slow client silently
  skips `state` frames and loses `log` lines (newest batch wins); a client that cannot absorb 64
  queued event frames is disconnected, because losing `command_vetoed` is how a user ends up shouting
  at a dog that is refusing to move for a reason nobody told them.
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
| 409 | `conflict` | `settings.jsonc` changed on disk since boot, or the key is not written there (#174) | restart the runtime, or edit the file |
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
- `docs/CONTROL_API.md` is the source of truth. `tests/test_api_routes.py` parses [§2](#2-endpoints) and compares it
  to the route table in `services/api.py`, so a route that exists in one and not the other fails CI.
  Change both, in the same commit.

---

## 8. Places

A place is a named pose a person taught: `{id, name, heading_deg, distance_cm, anchor, confidence,
created_ts, visits}`. `id` is the slug of the name at creation (`"Living Room"` → `living_room`) and is
what every other route takes. **The id never changes**, including on a rename: goals and the navigator
address a place by id, so correcting a name must not move the handle out from under a walk that is
already under way. Nothing infers a place from a scan, and `DELETE` is the only way one disappears.

| Route | Body | Answers |
|---|---|---|
| `POST /api/v1/places` | `{"name", "heading_deg", "distance_cm"}` required; `{"anchor", "confidence"}` optional | `201 {"place": {...}}` · `400 {"problems": [...]}` · `503` |
| `PATCH /api/v1/places/{id}` | any of `{"name", "heading_deg", "distance_cm", "anchor"}` — omitted fields keep their value | `200 {"place": {...}, "path"}` · `400 {"problems": [...]}` · `404` + `suggestion` · `503` |
| `DELETE /api/v1/places/{id}` | none — the path segment may be an id **or** a name | `200 {"removed": {...}}` · `404` + `suggestion` · `503` |
| `POST /api/v1/places/{id}/go` | `{"at_anchor": true}` — optional, see below | `202 {"accepted", "id", "name", "at_anchor"}` · `404` · `409` · `503` |

`400` bodies carry `problems[]` in the `{path, message, hint}` shape [§2](#2-endpoints)'s config validator already
uses, so a client shows them without translating: a duplicate name, a heading the format does not
allow, a name with no characters usable in an id (`"///"` slugs to `""`), or the catalogue limit.

`PATCH` follows the same rules and adds two of its own: an empty body is a `400` (a write that changes
nothing is how a client comes to believe it edited something), and `id` in the body is a `400` that says
to delete and recreate, because ignoring it would look like success. Renaming onto an existing name is
the duplicate-name `Problem` a second `POST` would return.

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
| `GET /api/v1/people` | `admin` | `{identity, path, people, last_enroll}` |
| `POST /api/v1/people` | `admin` | `202 {id, name, status}` · `400` · `503` |
| `DELETE /api/v1/people/{id}` | `admin` | `{removed: {id, name}, path}` · `404` · `503` |

```jsonc
{"identity": {"enabled": true, "backend": "face_recognition", "reason": null},
 "path": "/home/pi/.houndmind/face_references.json",
 "people": [{"id": "alex_kim", "name": "Alex Kim"}],
 "last_enroll": {"name": "Alex Kim", "ok": true, "reason": null, "ts": 1731628800.0}}
```

`last_enroll` is the outcome of the most recent enrolment request — `{name, ok, reason, ts}`, `null`
before the first one and again once the module stops. It is where a client reads the reason a person
did not appear in `people`; nothing about a face is in it.

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
 "path": null, "people": [], "last_enroll": null}
```

`reason` is the module's `disabled_reason` verbatim when it has one — `missing dependency:
face_recognition (dlib)` is a different problem from a switched-off module, and the module is the one
that knows which. `people: []` beside `identity.enabled: false` is never read as "nobody is enrolled".

### Enrolling

```http
POST /api/v1/people
{"name": "Alex Kim"}

→ 202 {"id": "alex_kim", "name": "Alex Kim", "status": "pending"}
```

Admin scope, like the read and the delete. `202` is the honest status: an enrolment needs the next
tick and **exactly one face in frame**, so the route accepts the request and returns the handle the
client will see in `people` — it does not claim the person is known yet.

**The answer is the roster, not this body.** A client that wants to know how it went re-reads
`GET /api/v1/people`: either the person is in `people`, or `last_enroll` says why not — `"no camera
frame yet, so there is nothing to enrol from"`, `"enrolment needs exactly one face in frame; got 2"`,
or `"backend 'face_recognition' cannot enrol"` after the wheel went missing. Before this route, the
same refusal was a `WARNING` line on the device that no client could read
([#103](https://github.com/seven-lynx/HoundMind/issues/103)).

- **`400`** for a name that is absent, not a string, blank, or has no usable characters. The id is
  `slug(name)`, so a name that slugs to nothing cannot be a person.
- **`503`** when no identity module is running, with the same `detail` the read puts in
  `identity.reason`. A read may report "nothing to show" about a stopped module; a write may not
  report "learning".
- Enrolling one name twice is legal and means two reference faces for one person, which is how the
  detector already treats the pair.

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

**A routine can do the same thing without a client.** `POST /api/v1/people` is a publisher and
nothing else: the command it writes (`face_recognition_command`) is the one
[§20](FEATURES_GUIDE.md#20-face-recognition-pi4) of `docs/FEATURES_GUIDE.md` documents, so a routine
step or a tool can enrol with no API involved.

---

## 10. Calibration

`GET /api/v1/calibration` reports the servo trim and whether offsets are auto-applied. It and the
route below are **read-only**: nothing in this build writes a servo offset over HTTP, and
`CalibrationModule` (`calibration/workflow.py`) publishes no motion intent.

```http
POST /api/v1/calibration/run
Authorization: Bearer <token>
{ "request": "servo_zero" }
→ 202 {"request": "servo_zero", "request_id": "9f3c1a77", "result": {"status": "ok", ...}}
```

| `request` | Measures |
|---|---|
| `servo_zero` | the trim the hardware already holds (`hal.read_offsets`), never written back |
| `wall_follow` | the distance error against `calibration.wall_follow_target_distance_cm` |
| `corner_seek` | the clearest angle of the latest scan |
| `landmark_align` | the pose confidence against `calibration.landmark_alignment_confidence_min` |

- The four names are an **allow-list** (`services/api.py::CALIBRATION_REQUESTS`). Anything else is
  `400 unknown_request` with the list, and nothing is put on the context.
- Every call carries a fresh `request_id`, so asking for the same reading twice is two runs. The
  module's re-run guard compares the pair, not just the name.
- `202` returns the module's result. `503 unavailable` means the runtime did not answer within one
  second (five ticks at the shipped 5 Hz): the request stays queued and the next tick still runs it.
- **There is no `POST /api/v1/calibration/apply`,** and no route that drives a servo in order to
  calibrate it. A calibration that *does* move the dog is a separate route with its own physical
  arming step; it must not be bolted onto this one, which is read-only by construction.
- **Saving a trim is a device action**, not an API one: `python -m tools.calibrate_servos --set
  joint=deg --apply` on the Pi writes through `DogHAL.apply_offsets`, merging over the loaded values
  and clamping to `SERVO_OFFSET_LIMIT_DEG`. `settings.calibration.auto_apply_servo_offsets` replays
  a saved trim at startup; nothing in the control plane writes one.

## 11. Conformance corpus

Three clients read the same wire contract, and prose is a poor way to disagree with someone's code.
`docs/fixtures/clients/` holds recorded decisions plus the outcome each one must produce, and

```bash
python -m tools.replay_decisions --corpus docs/fixtures/clients
```

runs every case through the same `ReplaySession` the control plane serves from: no dog, no socket,
no playback timing.

### 11.1 The manifest

`corpus.json` is the index. A case is one recorded stream and what it must produce:

```json
{
  "version": 1,
  "cases": [
    {
      "id": "obstacle-veto",
      "decisions": "decisions/obstacle-veto.jsonl",
      "expect": {
        "records": 3,
        "served": 3,
        "last_intent": "stand",
        "last_source": "behavior",
        "last_veto_reasons": ["obstacle"],
        "distance_valid_on_last": true
      }
    }
  ]
}
```

- `decisions` is relative to the corpus directory. An absolute path, or one that escapes the
  directory, is refused: a manifest is data, and data does not get to name a file outside the corpus.
- `expect` names only what a replay can actually check. A key outside
  [§11.2](#112-the-expectation-keys) is refused rather than ignored, so a typo cannot pass as
  "nothing to assert".

### 11.2 The expectation keys

| Key | Means |
|---|---|
| `records` | records `DecisionRecord` accepted from the stream |
| `served` | records the control plane would serve from its ring after the replay |
| `last_intent` | the newest record's `intent` (`null` when it decided nothing) |
| `last_source` | the newest record's `source` |
| `last_veto_reasons` | the newest record's refusal reasons, in recorded order |
| `distance_valid_on_last` | whether the replayed sensor reading keeps `distance_valid` for the last record |

The last row matters most. Replay is a *decision* feed, so a fixture that turns an invalid distance
into a plausible one teaches a client to trust a reading the dog never made
(`tools/replay_decisions.py:9-20`).

### 11.3 What a corpus run proves

It proves the **contract**: the JSON a client parses, the fields it reads, and the decision semantics
it renders. It does not prove the dog behaves this way — these streams are recordings, and the
equivalent run on hardware is `docs/HARDWARE_TEST.md`. Add a case when a client depends on a shape
that is not covered; never edit an expectation to make a client pass.

Both clients read this corpus: the web app in `services/web/`, and **HoundMind Remote**, which lives in
its own repository and is written against this file and these fixtures (#274).


