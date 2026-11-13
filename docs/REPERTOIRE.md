# HoundMind Action Repertoire

Status: **reference** — every action the dog can be asked to perform, its class, the parameters it
reads, and the behaviour buckets that draw on it.
Pairs with: `config/actions.jsonc` (the file this page mirrors — the file is authoritative),
`docs/ROUTINES.md` (the file format that names these), `docs/CONTROL_API.md` §3
(`POST /command`, `GET /repertoire`)

An action name is the unit of everything that moves. A command names one; a routine step names one; a
behaviour bucket is a list of them. `GET /api/v1/repertoire` returns this same catalogue at runtime,
which is what a client should read rather than hard-coding the tables below.

## Contents

1. [The four classes](#1-the-four-classes)
2. [Motion — `locomotion`](#2-motion--locomotion)
3. [Posture — `posture`](#3-posture--posture)
4. [Expression — `expression`](#4-expression--expression)
5. [Direct control — `non_motion`](#5-direct-control--non_motion)
6. [Parameters](#6-parameters)
7. [Buckets](#7-buckets)
8. [Adding an action](#8-adding-an-action)

---

## 1. The four classes

The class decides how much of the safety envelope the interlock applies before a command reaches a
servo (`src/houndmind_ai/act/interlock.py`). It is data in `config/actions.jsonc`, not a code path.

| Class | Envelope | What it means |
|---|---|---|
| `locomotion` | tilt latch + obstacle stop + battery floor + deadman | The dog can drive itself into something; sonar and the IMU can veto it. |
| `posture` | tilt latch + battery floor + deadman | Changes stance without travelling. |
| `expression` | tilt latch + battery floor + deadman | Head and tail only. |
| `non_motion` | deadman only | A sound or an LED is never blocked by sonar or a flat battery. |

`forward`, `backward`, `turn left` and `turn right` are always `locomotion`; the file cannot make them
weaker.

## 2. Motion — `locomotion`

| Action | Params | Used by |
|---|---|---|
| `forward` | `speed`, `steps`, `wait` | `avoid`, `patrol`, `explore` |
| `backward` | `speed`, `steps`, `wait` | `avoid` |
| `turn left` | `speed`, `steps`, `wait` | `avoid`, `patrol`, `explore` |
| `turn right` | `speed`, `steps`, `wait` | `avoid`, `patrol`, `explore` |
| `trot` | `speed`, `steps`, `wait` | `avoid`, `patrol`, `explore` |

## 3. Posture — `posture`

| Action | Params | Used by |
|---|---|---|
| `stand` | — | `idle`, `avoid`, `interact` |
| `sit` | — | `idle`, `interact` |
| `half_sit` | — | `idle` |
| `lie` | — | `idle`, `rest` |
| `waiting` | — | `idle` |
| `stretch` | — | `play` |
| `push up` | — | `play` |
| `high five` | — | `play`, `interact` |
| `handshake` | — | `play`, `interact` |
| `lick hand` | — | `play` |
| `feet shake` | — | `play` |
| `scratch` | — | `play` |
| `twist body` | — | `play` |
| `doze off` | — | `rest` |

## 4. Expression — `expression`

| Action | Params | Used by |
|---|---|---|
| `wag tail` | — | `alert`, `interact` |
| `shake head` | — | `idle`, `alert`, `interact` |
| `tilting_head` | — | `idle`, `explore` |
| `tilting_head_left` | — | `idle` |
| `tilting_head_right` | — | `idle` |
| `head_up_down` | — | `idle`, `explore` |
| `nod` | — | `idle` |
| `nod lethargy` | — | `rest` |
| `relax neck` | — | `idle`, `rest` |
| `think` | — | `idle` |
| `recall` | — | `idle` |
| `bark` | — | `alert` |
| `head_bark` | — | `alert` |
| `bark harder` | — | `alert` |
| `howling` | — | `alert` |
| `pant` | — | `alert` |
| `surprise` | — | `alert` |
| `fluster` | — | `play` |

## 5. Direct control — `non_motion`

These are not in any bucket. They exist for a client or a routine that wants the part directly.

| Action | Params | Notes |
|---|---|---|
| `stop` | — | Unconditional stop. `POST /api/v1/stop` is the audited path to the same thing. |
| `head` | `yaw`, `pitch`, `speed`, `wait` | Degrees, clamped to the head's travel range. |
| `rpy` | `roll`, `pitch`, `yaw` | Body pose in degrees — the whole chassis, not the head. |
| `rgb` | `style`, `color`, `brightness`, `bps` | LED strip. `brightness` is 0–1 and is **not** clamped by the vendor. |
| `sound` | `name`, `volume` | One of the shipped effects (`docs/pidog/PIDOG-EXPRESSION.md` §2.2). |
| `speak` | `text`, `volume` | Vendor TTS; requires the vendor speech stack. |

## 6. Parameters

| Param | Type | Range | Notes |
|---|---|---|---|
| `speed` | number | 0–1 (a fraction of full speed) | Clamped by the interlock before it reaches a servo. |
| `steps` | integer | 1 and up | Locomotion cycles, not centimetres. Nothing measures travel. |
| `wait` | number | seconds | Pause after the action. |
| `volume` | integer | 0–100 | |
| `brightness` | number | 0–1 | Values above 1 ask the driver for channels over 255. |
| `bps` | number | 0 and up | Beats per second for an LED animation. |
| `yaw`, `pitch`, `roll` | number | degrees | Head or chassis, per the action. |

A parameter that the action does not declare is **refused**, not ignored: `{"action": "sit", "params":
{"wait": 1}}` fails because `sit` declares no parameters (`docs/ROUTINES.md` §"A step").

## 7. Buckets

A bucket is named group of actions the behaviour FSM draws from, declared under `catalog` in
`config/actions.jsonc`. The shipped buckets: `idle`, `alert`, `avoid`, `play`, `rest`, `patrol`,
`explore`, `interact`. `docs/FEATURES_GUIDE.md` §7 explains how one is picked each tick — a
recency-weighted draw, not `random.choice`.

An action may appear in several buckets; `shift`-like duplicates cost nothing because the draw is
weighted by recency, not by list position.

## 8. Adding an action

1. Add the name under `actions` in `config/actions.jsonc` with a class, and its `params` if it takes
   any.
2. Add it to one or more buckets under `catalog`, or to none if it is client-only.
3. If the HAL cannot execute it, the command is refused at execution time with a named reason — the
   catalogue does not make a vendor action exist.
4. Restart. A name in a bucket that is missing from `actions` is a load-time error with a
   did-you-mean.
