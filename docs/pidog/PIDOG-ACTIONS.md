# PiDog & RobotHAT — Actions

Status: **reference** — the built-in action catalogue and the `ActionFlow` runner. This is the
layer most example scripts actually use.
Version: v2026.01.18 • Author: 7Lynx
Verified against: `sunfounder/pidog@cee4bff`
Pairs with: `PIDOG-MOTION.md` §4 (what a frame is), `PIDOG-EXPRESSION.md` (sound the actions use)

Sections: §1 three kinds of "action" · §2 `Pidog.do_action` · §3 the catalogue ·
§4 `ActionFlow` · §5 writing your own routine · §6 hazards

---

## 1. Three things are called an action

Before anything else, because every misfire starts here:

| Name | Lives in | Takes | Raises on unknown name? |
|---|---|---|---|
| `Robot.do_action` | `robot_hat` | a key in `Robot.move_list`, which is **empty** | yes, `KeyError` |
| `Pidog.do_action` | `pidog` | a name from `ActionDict` (`'sit'`, `'wag_tail'` …) | **no** — prints and returns |
| `ActionFlow.add_action` | `pidog.action_flow` | a name from `ActionFlow.OPERATIONS` (`'sit'`, `'bark harder'` …) | **no** — ignored |

They are three different vocabularies with overlapping spellings. `Pidog` names are snake_case
(`wag_tail`); `ActionFlow` names are space-separated lowercase (`wag tail`). HoundMind converts
between them with `kernel/commands.py::canonical_action`.

---

## 2. `Pidog.do_action` and `ActionDict`

```python
dog.do_action(name, step_count=1, speed=50, pitch_comp=0)
```

`self.actions_dict` is an `ActionDict`, a `dict` subclass whose `__getitem__` is:

```python
def __getitem__(self, item):
    return eval("self.%s" % item.replace(" ", "_"))
```

So **the catalogue is a set of properties, not dictionary keys**. `'lie' in actions_dict` is
`False`; `actions_dict['lie']` still works. Iterating the dict yields nothing.

Each property returns a tuple `(frames, part)`, where `part` is `'legs'`, `'head'` or `'tail'` and
`frames` is the list of frames that part's buffer expects:

```python
frames, part = dog.actions_dict['sit']      # ([ [30, 60, -30, -60, 80, -45, -80, 45] ], 'legs')
```

`do_action` then appends `step_count` copies of those frames, with `immediately=False`, so it
**queues behind whatever is already running** and returns immediately.

Because `__getitem__` uses `eval`, any attribute name resolves: `do_action('__dict__')` returns a
dict, and the unpacking on the next line raises `ValueError`, which is caught. Weird names are
therefore harmless but silent.

Two knobs that change the catalogue itself:

| Call | Effect |
|---|---|
| `actions_dict.set_barycenter(mm)` | accepted range −60…59; shifts the body offset used by `stand` |
| `actions_dict.set_height(mm)` | accepted range 20…94; **stored and never used** — `stand` hard-codes 95 |

---

## 3. The catalogue

`legs` actions take 8 angles per frame; `head` actions take `[yaw, roll, pitch]`; `tail` takes one
angle. `Frames` is how many frames `do_action(step_count=1)` queues.

### 3.1 Postures and poses (legs)

| Name | Frames | What it is |
|---|---|---|
| `stand` | 1 | standing, body offset from `barycenter`, front legs 20 mm forward |
| `half_sit` | 1 | front legs folded, hind legs still extended |
| `sit` | 1 | hind legs folded, front legs straight |
| `lie` | 1 | all four legs folded — the pose `Pidog()` starts and ends in |
| `lie_with_hands_out` | 1 | lying with the front legs stretched forward |
| `stretch` | 1 | the downward-dog stretch |

These are literal angle lists, so they are what you read when you want to know the geometry.

### 3.2 Gaits (legs)

| Name | Frames | Source |
|---|---|---|
| `forward` | 49 | `Walk(FORWARD, STRAIGHT)` |
| `backward` | 49 | `Walk(BACKWARD, STRAIGHT)` |
| `turn_left` | 49 | `Walk(FORWARD, LEFT)` |
| `turn_right` | 49 | `Walk(FORWARD, RIGHT)` |
| `trot` | 6 | `Trot(FORWARD, STRAIGHT)` |

49 frames × one step each means a single `forward` call keeps the legs busy for
49 × frame duration. At `speed=98` with `max_dps=428` that is still seconds of motion: this is why
`ActionFlow` calls `wait_all_done()` after every operation and why `step_count` is nearly always
left at 1.

### 3.3 Head and tail

| Name | Part | Frames | What it is |
|---|---|---|---|
| `nod_lethargy` | head | 41 | slow sleepy nodding |
| `shake_head` | head | 21 | yaw sweep ±60° |
| `tilting_head_left` | head | 1 | roll −25, pitch 15 |
| `tilting_head_right` | head | 1 | roll 25, pitch 20 |
| `tilting_head` | head | 40 | left 20 frames, right 20 frames |
| `head_bark` | head | 4 | look up, settle, look up again |
| `head_up_down` | head | 3 | up, hold, down |
| `wag_tail` | tail | 2 | −30°, +30° |

### 3.4 Programmatic actions (legs)

| Name | Frames | What it is |
|---|---|---|
| `push_up` | 2 | front down / front up, hind legs braced |
| `doze_off` | 200 | front legs settle in a loop, hind legs follow (4 frames per step) |

Everything else that looks like a trick — handshake, high five, howling, scratch — is **not** an
action name. It is a function in `preset_actions.py` driven by `ActionFlow` (§4).

---

## 4. `ActionFlow` — the background runner

`ActionFlow` wraps a `Pidog` and runs named operations one at a time on its own thread, adding
posture bookkeeping and a random idle animation.

```python
from pidog import Pidog
from pidog.action_flow import ActionFlow

dog = Pidog()
flow = ActionFlow(dog)
flow.start()
flow.add_action('sit', 'bark')          # queued in order
flow.wait_actions_done()
flow.stop()
dog.close()
```

### 4.1 The state machine

| State | Behaviour |
|---|---|
| `STANDBY` | every 2–6 s runs a random idle action (§4.4) |
| `THINK` | does nothing at all, on purpose — a pause between behaviours |
| `ACTIONS` | drains the queue, one action at a time, 0.5 s apart |
| `ACTIONS_DONE` | defined and never used |

`add_action(*names)` puts each name on a `queue.Queue` and switches the state to `ACTIONS`.
`set_status(state)` sets it directly. `wait_actions_done()` spins until `STANDBY`.

### 4.2 `OPERATIONS` — the vocabulary

A dict of 30 entries; each maps a space-separated name to a small record:

```python
"wag tail": {
    "function": lambda self: self.dog_obj.do_action('wag_tail', speed=100),
    "after": "wag tail",
},
"high five": {
    "function": lambda self: high_five(self.dog_obj),
    "after": "sit",
    "poseture": Posetures.SIT,
},
```

| Key | Meaning |
|---|---|
| `function` | what to run: a `do_action` call or a `preset_actions` function |
| `poseture` | body posture to adopt **before** running (the vendor's spelling) |
| `before` | run this first, then wait — an operation name or a callable |
| `after` | run this afterwards, then wait |

Full name list: `forward`, `backward`, `turn left`, `turn right`, `stop`, `lie`, `stand`, `sit`,
`bark`, `bark harder`, `pant`, `wag tail`, `shake head`, `stretch`, `doze off`, `push up`,
`howling`, `twist body`, `scratch`, `handshake`, `high five`, `lick hand`, `waiting`,
`feet shake`, `relax neck`, `nod`, `think`, `recall`, `fluster`, `surprise`.

`run()` executes posture → `before` → `function` → `after`, calling `wait_all_done()` after every
stage.

### 4.3 Postures

```python
Posetures.STAND = 0
Posetures.SIT   = 1
Posetures.LIE   = 2
```

`change_poseture()` also sets a head pitch bias — 0° standing, −35° sitting/lying — and passes it
to the preset functions as `pitch_comp`. That is why a sitting `bark` looks up.

Transitioning to `STAND` from anything else calls `sit_2_stand(dog, speed=75)`, a dedicated
preset. The `speed > 70` note at its call site is real: below that the front legs can drag.

### 4.4 The idle animation is motion

In `STANDBY`, every 2–6 s the handler picks between `'waiting'` (weight 1) and
`'feet_left_right'` (weight 0.3) and runs it. `'feet_left_right'` **is not in `OPERATIONS`**, so
`run()` does nothing for it — the only idle animation you will actually see is `waiting`, which
shakes a front foot and looks at you.


### 4.5 `preset_actions` — the functions behind the names

The trick actions are plain functions taking the dog first, in `pidog/preset_actions.py`:

| Function | Signature |
|---|---|
| `bark` | `(my_dog, yrp=None, pitch_comp=0, roll_comp=0, volume=100)` |
| `bark_action` | `(my_dog, yrp=None, speak=None, volume=100)` |
| `howling` | `(my_dog, volume=100)` |
| `pant` | `(my_dog, yrp=None, pitch_comp=0, speed=80, volume=100)` |
| `shake_head` | `(my_dog, yrp=None)` |
| `shake_head_smooth` | `(my_dog, pitch_comp=0, amplitude=40, speed=90)` |
| `nod` | `(my_dog, pitch_comp=-35, amplitude=20, step=2, speed=90)` |
| `relax_neck` | `(my_dog, pitch_comp=-35)` |
| `stretch` | `(my_dog)` |
| `push_up` | `(my_dog, speed=80)` |
| `sit_2_stand` | `(my_dog, speed=75)` |
| `scratch`, `hand_shake`, `high_five`, `lick_hand` | `(my_dog)` |
| `feet_shake` | `(my_dog, step=None)` |
| `body_twisting`, `attack_posture` | `(my_dog)` |
| `waiting` | `(my_dog, pitch_comp)` |
| `think`, `recall`, `fluster`, `alert` | `(my_dog, pitch_comp=0)` |
| `head_down_left`, `head_down_right` | `(my_dog, pitch_comp=0)` |
| `surprise` | `(my_dog, pitch_comp=0, status='sit')` |

They call `dog.head_move`, `dog.legs_move`, `dog.do_action` and `dog.speak` directly, and most end
with `wait_all_done()`, so a single preset can occupy the dog for several seconds.

---

## 5. Writing your own routine

Two shapes, and the choice matters.

### 5.1 Frames in, frames out (precise, silent)

```python
sit = dog.actions_dict['sit'][0][0]          # the 8 angles of the sit pose
dog.legs_move([sit], speed=70)
dog.wait_legs_done()
```

The direct path: you control every frame, and nothing else moves the dog while you do it.

### 5.2 A function that owns the dog for a moment (expressive)

```python
def look_around(dog, speed=60):
    for yaw in (-40, 40, 0):
        dog.head_move([[yaw, 0, 0]], speed=speed)
        dog.wait_head_done()


def greet(dog):
    look_around(dog)
    dog.do_action('wag_tail', speed=100)
    dog.speak('single_bark_1', volume=80)
    dog.wait_all_done()
```

Name it, keep it near your other behaviours, and register an `OPERATIONS` entry if it must be
callable by string.

### 5.3 Which one

| Need | Use |
|---|---|
| Repeatable motion you can reason about | direct buffers (§5.1) |
| Sound, head and legs choreographed together | a preset-style function (§5.2) |
| A queue of named behaviours with postures | `ActionFlow` (§4) |
| Anything the runtime should supervise | `hal/vendor.py`, not a script — `PATTERNS.md` §7 |

---

## 6. Hazards

1. **`ActionFlow.stop()` can hang.** The worker blocks in `action_queue.get()` with no timeout. If
   the state is set to `ACTIONS` while the queue is empty (`set_status` then `stop`), the thread
   never sees `thread_running = False` and `join()` never returns.
2. **The thread is not a daemon.** Forget `stop()` and the process will not exit.
3. **`stop` is not a stop.** The `"stop"` operation record is empty, so `run('stop')` does
   nothing — it does not clear a buffer or halt motion. To stop, call `dog.body_stop()`.
4. **Names are not interchangeable.** `'wag_tail'` (Pidog) vs `'wag tail'` (ActionFlow). A wrong
   spelling is silently ignored by both.
5. **Idle motion.** A started flow animates the dog every few seconds (§4.4).
6. **Errors are swallowed and printed.** `run()` wraps everything in `try/except Exception` and
   prints `action error: …` — your code cannot see the failure, only the console can.

---

## Used by HoundMind

| Vendor call | Where |
|---|---|
| `ActionFlow(dog)` + `start()` | `src/houndmind_ai/hal/vendor.py` → `_ensure_action_flow` |
| `add_action(name)` for fire-and-forget | `hal/vendor.py` → `action` |
| operation-name discovery | `hal/vendor.py` → `_read_vendor_actions` |
| action catalogue offered to clients | `config/actions.jsonc` → `kernel/actions.py` |

HoundMind never calls `ActionFlow.wait_actions_done()` from the tick thread: the flow may be
inside a multi-second preset, and waiting there would stall the loop.
