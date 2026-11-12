# HoundMind Routines

Status: **contract** — the file format a user writes and the dog plays. A new optional key is an
additive change; renaming a key, or making an optional one required, breaks every routine already on a
device.
Version: v2026.01.18 • Author: 7Lynx
Pairs with: `docs/CONTROL_API.md` §3 (the routes that list and start one), `config/actions.jsonc` (the
vocabulary a step may name), `src/houndmind_ai/kernel/routine.py` (the validator this file describes)

A routine is a list of actions the dog plays in order — stand up, look left, wag, sit. It is **data,
never code**: flat JSON, one step per action, no expressions and no loops, so a routine cannot fail to
terminate and the worst a bad one can do is be refused at load time.

Two rules carry the design:

1. **The repertoire is the vocabulary.** A step names an action `GET /api/v1/repertoire` lists, and a
   parameter is legal only if the catalog entry for that action declares it. The menu a client builds
   a routine from is the menu that accepts it.
2. **A routine that cannot run in full is refused.** A bad step is a load-time error that names the
   path to fix, never a run that stops halfway.

## Where the files live

| | |
|---|---|
| Directory | `settings.routines.dir`, `~/.houndmind/routines` by default. `~` is expanded at startup. |
| One file per routine | any `*.json`. The name is a **label**, not the identity: `greeting.json` may declare `"id": "morning_greeting"`. |
| When it is read | once, when the runtime starts. A file added or edited since then appears after a restart. |
| Who writes | you. The dog never creates, edits or deletes anything in this directory. |

A missing directory is an empty list, not an error — a fresh install has no routines and still boots.
A path that points at a file is treated the same way. One file is capped at 256 KB, which a legal
64-step routine is nowhere near.

## The document

```json
{
  "id": "morning_greeting",
  "name": "Morning greeting",
  "allow_locomotion": false,
  "steps": [
    { "action": "sit" },
    { "action": "head", "params": { "yaw": 20, "pitch": 5 } },
    { "action": "sound", "params": { "name": "woohoo" } },
    { "action": "wag_tail" }
  ]
}
```

| Key | Required | Rule |
|---|---|---|
| `id` | yes | A slug: lowercase letters, digits, `_` or `-`, at most 64 characters, starting with a letter or a digit. It names the routine in the API and in `current`. |
| `name` | no | A non-empty string for a human. Clients fall back to the `id`. |
| `version` | no | A whole number ≥ 1, default `1`. Reserved for a format change; every routine today is version 1. |
| `allow_locomotion` | no | A real `true`/`false`, default `false`. See below. |
| `steps` | yes | A list of 1–64 step objects, played in order. |

Unknown keys are **refused, not ignored**. A typo'd `allow_locomotion` that was silently dropped would
mean a routine the user believed harmless walks the dog, so the validator reports the key and suggests
the nearest one.

### A step

| Key | Required | Rule |
|---|---|---|
| `action` | yes | An action from `GET /api/v1/repertoire`. Case and spacing do not matter: `turn left`, `turn_left` and `Turn Left` are one action. |
| `params` | no | A table of scalars — string, number or boolean. A key is legal only if the catalog declares it for that action, so `{ "action": "sit", "params": { "wait": 1 } }` is refused: `sit` declares no parameters. |

`params` are what the action's catalog entry reads: `{ "action": "forward", "params": { "speed": 0.5,
"steps": 3 } }` walks three cycles at half speed, `{ "action": "head", "params": { "yaw": 20 } }` turns
the head, and `{ "action": "speak", "params": { "text": "Good morning" } }` says a line. The
authoritative list of names and parameters is `GET /api/v1/repertoire`; `config/actions.jsonc` is the
same table in file form.


### `allow_locomotion`

Locomotion moves the dog across the floor. A routine with `allow_locomotion: false` — the default —
may not contain a step whose action the catalog classes `locomotion` (`forward`, `backward`,
`turn left`, `turn right` and `trot` in the shipped catalog). That is a load-time refusal, not a
runtime veto: a routine that half-runs is worse than one that never starts.

Only a real boolean counts. `"allow_locomotion": "false"` is refused rather than coerced — a non-empty
string is truthy, so a coercion would switch the opt-in **on** while reading as off.

```json
{
  "id": "patrol_march",
  "name": "Three steps forward, then sit",
  "allow_locomotion": true,
  "steps": [
    { "action": "forward", "params": { "speed": 0.5, "steps": 3 } },
    { "action": "sit" }
  ]
}
```

## How it plays

`POST /api/v1/routines/{id}/run` queues a run; nothing moves until the next tick. The runner then
publishes one step per tick as a `routine` intent and reads the gateway's answer on the following
tick, so **every step passes the mode gate and the interlock exactly like a command from a hand**:

- a `routine` intent outranks idle behaviour and yields to `navigation`, so obstacle avoidance can
  preempt a step;
- `rest` refuses it; `idle`, `patrol` and `manual` admit it;
- an obstacle, a tilt latch, a flat battery or a mode change can end a run mid-way.

The first refusal **ends the run** instead of skipping the step: the run's `state` becomes `refused`
and `veto` names the reason (`obstacle`, `tilt`, `mode`, …), in the same vocabulary as
`motion_verdict`. Otherwise a run ends as `done`, or as `stopped` when `POST /api/v1/stop` arrives.

`dry_run: true` walks the same steps without publishing one: counters and transitions move, servos do
not. It is how a client previews a routine on a real dog.

## Watching a run

| Surface | What it shows |
|---|---|
| `GET /api/v1/routines` | `current`, the run the runner holds (or `null`) |
| `GET /api/v1/state` | `state.routines`, the same object, rewritten every tick |
| WS `routine` event | the same object, pushed when the run *moves*: a new step, a new state, a new veto |

The two reads and the event carry one object, so a client never translates between them. `index` is
the step currently published (0-based) and a finished run has `index == total`, which is how a client
renders "step 3 of 5" without guessing from `state`.

## When a file is refused

One bad file never costs the others: the directory still loads, the runtime still starts, and the
refusal is reported next to the file a user has to fix.

| Situation | What happens |
|---|---|
| Not valid JSON, unreadable, or over 256 KB | the file is refused by name |
| A key, action or parameter the format does not know | refused with the validator's path (`routine.steps[0].action`), the reason, and a suggestion when there is one |
| A locomotion step under `allow_locomotion: false` | refused, naming the action |
| No steps, or more than 64 | refused |
| Two files declaring one `id` | the first file in sorted order keeps the id; the second is refused and names the file it collided with |

`GET /api/v1/routines` lists those refusals under `refusals`, keyed by file name, with the validator's
own paths — `docs/CONTROL_API.md` §3 has the shape.

## What this file does not cover

- The routes that list and start a routine: `docs/CONTROL_API.md` §3, and §4/§5 for the snapshot block
  and the socket event.
- Turning the runner off: `docs/FEATURES_GUIDE.md` §7.
- Scheduling. A routine runs when something asks for it; nothing on the device starts one on a timer.
