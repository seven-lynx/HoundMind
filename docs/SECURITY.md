# Security and Exposure

Status: **runbook** — what the device exposes, what protects it, and what to do before it leaves a lab.
Pairs with: `docs/CONTROL_API.md` §1 (the auth contract), `docs/INSTALL.md` §TLS, `docs/LOGGING.md`
(what a support bundle may contain)

HoundMind listens on **one port** and holds **one secret**. Everything below is about those two facts
and the places they leak.

## Contents

1. [The shape of it](#1-the-shape-of-it)
2. [The device token](#2-the-device-token)
3. [What is unauthenticated, and why](#3-what-is-unauthenticated-and-why)
4. [Scopes](#4-scopes)
5. [Pairing](#5-pairing)
6. [Camera tickets](#6-camera-tickets)
7. [Turning on TLS](#7-turning-on-tls)
8. [Data that is nobody's business](#8-data-that-is-nobodys-business)
9. [Checklist before it leaves the bench](#9-checklist-before-it-leaves-the-bench)
10. [Reporting a problem](#10-reporting-a-problem)

---

## 1. The shape of it

- One process, one listener: `services/api.py`, port **8420** by default.
- No second server. The old per-feature listeners (8088 face, 8090 vision, 8091 voice, 8092
  telemetry) are gone, and each was unauthenticated — that removal is most of the security story.
- `settings.api.host` ships as `0.0.0.0`: the device is reachable from the LAN *by design*, and the
  token is the boundary. There is no cloud relay and no remote access from outside the LAN.
- Video is the one place a credential travels in a URL, and it is a single-use 60-second ticket rather
  than the device token (§6).

## 2. The device token

- Generated on first start into `~/.houndmind/api_token`, mode **0600**
  (`services/auth.py::TokenStore`).
- Never logged, never returned by a route, never printed by a tool. The support bundle redacts
  `api.token_path` to `***` (`tests/test_api_routes.py` asserts it).
- Send it as `Authorization: Bearer <token>`. Never put it in a query string — `?token=` on the camera
  routes is refused with a `401` that names the replacement.
- To rotate: stop the runtime, delete the file, start it again, and re-pair every client. There is no
  hot rotation, and no token-generator script to run.

## 3. What is unauthenticated, and why

| Route | Why |
|---|---|
| `GET /api/v1/meta` | A client must discover the API version and board before it holds a token. It carries no state and no roster. |
| `GET /api/v1/health` | Liveness only: `{"status":"ok"}`. No detail to leak. |
| `POST /api/v1/pair` | The exchange that *produces* a token; protected by the pairing code instead. |
| `GET /api/v1/events` | The WebSocket authenticates in its own first `hello` frame. |
| `GET /api/v1/camera/stream`, `/camera/snapshot` | An `<img>` tag cannot send a header. Protected by a ticket (§6). |

Everything else needs a token, and `tests/test_api_routes.py` fails if a new route ships without a
scope. A new listener is not covered by any of this — it needs its own auth story before it merges.

## 4. Scopes

| Scope | Can | Typical holder |
|---|---|---|
| `state:read` | read state, modules, decisions, history, camera | a phone dashboard |
| `move` | `POST /command`, `/stop`, `/mode`, routine run, place go | the controller |
| `config` | read config, patch the four live keys, read calibration, write places | an admin client |
| `admin` | logs, support bundle, pairing window, people roster and forget | the owner's device token |

Scope is declared per route in `ROUTES`, so the table in `docs/CONTROL_API.md` §2 and the code cannot
drift apart without a test failing.

## 5. Pairing

`POST /api/v1/pair/open` (admin) opens a window and returns a **six-digit code** valid for five
minutes and usable once. A client exchanges it at `POST /api/v1/pair` for its own token. Attempts are
rate-limited (`settings.api.pairing_attempts_per_minute`), and only an `admin` token can open a
window — a client token gets `403`.

## 6. Camera tickets

`POST /api/v1/camera/ticket` (`state:read`) mints a single-use ticket valid for 60 seconds.
`/camera/stream` and `/camera/snapshot` accept it as `?ticket=`. This exists because a device token in
a URL ends up in browser history, proxy logs and screenshots; a 60-second single-use secret in that
position is a much smaller problem.

## 7. Turning on TLS

Plaintext HTTP is the default: the token, every command and every frame cross the LAN in the clear.

```jsonc
"api": {
  "tls_enabled": true
}
```

The plane then serves HTTPS with a generated self-signed certificate. `docs/INSTALL.md` §TLS has the
trust steps for a client (`--cacert ~/.houndmind/tls/cert.pem`). Self-signed means a client must either
trust that file or pin it — there is no CA behind it and no domain name.

## 8. Data that is nobody's business

| Where | What | Rule |
|---|---|---|
| `~/.houndmind/face/` | face embeddings and reference images | biometric. Copy none of it off the device; delete it if the dog changes hands (`docs/FEATURES_GUIDE.md` §20). |
| `~/.houndmind/places.json`, `routines/` | room names, household routines | personal. No bundle includes them, but event logs can name them. |
| `config/settings.jsonc` | WiFi credentials | never commit it with a real passphrase; never paste it into an issue. |
| `logs/` | whatever the runtime printed | review before sharing; strip anything identifying. |

No route serves `/face/`, and no bundle member contains an embedding — the roster returns names and
ids only.

## 9. Checklist before it leaves the bench

- [ ] Device token present at `~/.houndmind/api_token`, mode 0600.
- [ ] `GET /api/v1/meta` reachable, and `GET /api/v1/state` returns `401` without a token.
- [ ] A `?token=` request to `/camera/stream` returns `401` (tickets only).
- [ ] No pairing window sitting open.
- [ ] `tls_enabled` decided deliberately, and clients configured for whichever answer you chose.
- [ ] Port 8420 not forwarded from the internet, whatever else is true.
- [ ] Face directory deleted if the dog is being passed on.

## 10. Reporting a problem

Open a **private security advisory** on the repository (Security → Advisories → Report a vulnerability)
rather than a public issue. Include the version from `pyproject.toml`, the board, and the route or
module involved. Do not include a live token, a WiFi passphrase, or a support bundle with logs from a
real home.

