# PiDog & RobotHAT — The `robot_hat` layer

Status: **reference** — every class `Robot HAT` gives you, and the traps in each. This is the
layer under `pidog`; understanding it is what turns "call the action name" into control.
Version: v2026.01.18 • Author: 7Lynx
Verified against: `sunfounder/robot-hat@4556bd8` (branch `2.5.x`)
Pairs with: `HARDWARE.md` (pin map), `PIDOG-MOTION.md` (the layer above)

Sections: §1 imports · §2 `Pin` · §3 `ADC` · §4 `PWM` · §5 `Servo` and `Robot` ·
§6 `I2C` · §7 motors · §8 `device` · §9 audio · §10 storage and utils · §11 quirks

---

## 1. Imports and what gates them

### 1.1 The one import you actually write

```python
from robot_hat import Pin, ADC, PWM, Servo, I2C, Motor, Motors, Ultrasonic, Music
from robot_hat import device           # battery, speaker, MCU reset, button, LED
from robot_hat.utils import mapping    # small helpers
```

`robot_hat/__init__.py` re-exports: `ADC`, `fileDB`, `Config`, `I2C`, everything in `modules`
(`Ultrasonic`, `ADXL345`, `RGB_LED`, `Buzzer`, `Grayscale_Module`, `LineTracker`), `Music`,
`Motor`, `Motors`, `Pin`, `PWM`, `Servo`, `Robot`, and everything in `utils`.

### 1.2 A missing wheel disables all of it, quietly

Before any of those imports run, the package checks four modules it needs:

```python
IMPORT_MODULES = ("smbus2", "lgpio", "pyaudio", "pygame")
```

If any is absent, it emits a `UserWarning` and **skips the entire import block**. You then get
`ImportError: cannot import name 'Servo' from 'robot_hat'` — a message that names the wrong
problem. When you see that, run:

```bash
robot_hat doctor        # what is installed, what the HAT says it is
robot_hat version
robot_hat scan_i2c
```

### 1.3 Which version is installed

This file documents **2.5.x**. Check before trusting a signature:

```bash
python -c "import robot_hat; print(robot_hat.__version__)"
pip show robot-hat
```

`2.5.x` added `Config`, `device.Devices`, `Speaker`, the TTS wrappers, `UserButton`, `LED`, and
moved `reset_mcu`/`get_battery_voltage`/`set_pin`/`enable_speaker` into `device`. The `v2.0`
tree this repo's install guide still clones lacks most of that, so a guide-following reader on a
`v2.0` install will find `from robot_hat import device` failing. Fix the install, not the code.

---

## 2. `Pin` — GPIO

```python
Pin(pin, mode=None, pull=None, active_state=None)
```

| Argument | Accepted |
|---|---|
| `pin` | `'D0'`…`'D16'`, `'USER'`, `'LED'`, `'MCURST'`, … or the raw BCM number |
| `mode` | `Pin.IN`, `Pin.OUT`, or `None` |
| `pull` | `Pin.PULL_UP`, `Pin.PULL_DOWN`, `Pin.PULL_NONE` |
| `active_state` | invert the software polarity when `False` |

Methods: `value(v=None)`, `on()`, `off()`, `high()`, `low()`, `__call__(v)`, `name()`,
`setup(mode, pull, active_state)`, `irq(handler, trigger, bouncetime=200, pull=None)`,
`close()`, `deinit()`.

Constants: `OUT`, `IN`, `PULL_UP`, `PULL_DOWN`, `PULL_NONE`, `IRQ_FALLING`, `IRQ_RISING`,
`IRQ_RISING_FALLING`.

Three behaviours to know:

- `value()` with no argument **switches the pin to input first** if it was output or unset. So a
  `Pin` cannot be both: reading after writing silently flips it.
- `Pin._chip` is one process-wide `lgpio` chip handle, opened lazily on first `Pin()` and shared
  with `SoundDirection`. Two libraries opening the chip separately is the classic "GPIO busy"
  failure this avoids.
- `active_state` is documented but **not stored** in 2.5.x — `setup()` reads it and ignores it.
  If you need inversion, invert in your own code.

```python
from robot_hat import Pin
sw = Pin('USER', mode=Pin.IN, pull=Pin.PULL_UP)
pressed = sw.value() == 0        # active low, as `device.get_usr_btn()` does
```

---

## 3. `ADC` — analogue input

```python
ADC(chn, address=None)     # chn: 0-7 or 'A0'-'A7'
```

| Method | Returns |
|---|---|
| `read()` | 0–4095 counts |
| `read_voltage()` | volts, 0–3.3 |

The channel is internally reversed (`chn = 7 - chn`) before it becomes a register value — a
quirk of the MCU wiring, invisible to callers. Channel `A4` is the battery divider.

```python
from robot_hat import ADC
a4 = ADC('A4')
volts = a4.read_voltage() * 3      # what device.get_battery_voltage() does
```


---

## 4. `PWM` — and the shared-timer rule

```python
PWM(channel, address=None)        # channel 0-19 or 'P0'-'P19'
```

| Member | Meaning |
|---|---|
| `CLOCK` | 72 000 000 Hz — the MCU timer clock |
| `ADDR` | `[0x14, 0x15, 0x16]`, probed in order |
| `freq(f=None)` | set/get Hz; picks the prescaler/period pair with the least error |
| `prescaler(p=None)` | set/get, register is written as `p - 1` |
| `period(arr=None)` | set/get ticks |
| `pulse_width(v=None)` | set/get ticks, 0–65535 |
| `pulse_width_percent(p=None)` | set/get 0–100, computed from the **timer's** period |

The relationship the whole class turns on:

```
frequency = CLOCK / prescaler / period
```

### 4.1 Channel → timer

`channel // 4` for 0–15, then 16–17 share timer 4, 18 is 5, 19 is 6:

| Channels | Timer |
|---|---|
| P0–P3 | 0 |
| P4–P7 | 1 |
| P8–P11 | 2 |
| P12–P15 | 3 |
| P16, P17 | 4 |
| P18 | 5 |
| P19 | 6 |

### 4.2 What is shared, and what breaks

The period is stored in a **module-level** list, one entry per timer, not per channel:

```python
timer = [{"arr": 1} for _ in range(7)]
```

So `prescaler()`, `period()` and `pulse_width_percent()` for *any* channel write to the timer
that channel belongs to. Two channels on the same timer cannot have different frequencies — the
last write wins for both.

### 4.3 Where the dog's servos sit

| Timer | Channels | What is on them |
|---|---|---|
| 0 | P0, P1, P2, P3 | three leg joints + LF shoulder |
| 1 | P4, P5, P6, P7 | head yaw/roll/pitch + RF shoulder |
| 2 | P8, P9, P10, P11 | RF leg, tail, RH shoulder, RH leg |
| 3 | P12, P13 | ***free*** — the wheel motors use these |
| 4–6 | P16–P19 | free |

Every `Servo` sets period 4095 and prescaler `round(72e6 / 50 / 4095)` = 352, so all twelve
servo channels agree and the sharing is harmless. The actual servo frequency is therefore
**49.95 Hz**, not exactly 50.

### 4.4 The rule

> **Never call `freq()`, `prescaler()` or `period()` on a channel that shares a timer with a
> servo.**

Driving a buzzer or an LED on P4 "just to try it" resets head yaw, roll and pitch to whatever
period you chose. Use P12–P19 for anything you add. If you must share a timer, keep
prescaler 352 / period 4095 and vary only `pulse_width`, which *is* per channel.

---

## 5. `Servo`, and how `Robot` turns a number into motion

### 5.1 `Servo`

```python
Servo(channel, address=None)

Servo.MAX_PW  = 2500      # microseconds
Servo.MIN_PW  = 500
Servo.FREQ    = 50
Servo.PERIOD  = 4095      # ticks
```

| Method | Behaviour |
|---|---|
| `angle(a)` | degrees, −90…+90; out-of-range is **clamped**, not raised |
| `pulse_width_time(us)` | 500–2500 µs, clamped; converts to ticks and writes it |

`angle()` is a straight linear map from (−90…90) onto (500…2500 µs), then onto ticks of the
20 ms frame. There is **no offset and no direction** at this level — both belong to `Robot`.

### 5.2 `Robot` — one joint group

```python
Robot(pin_list, db=config_file, name=None, init_angles=None, init_order=None)
```

| Argument | Purpose |
|---|---|
| `pin_list` | PWM channels, in the order the angle lists will use |
| `db` | calibration file (see `HARDWARE.md` §6) |
| `name` | prefix of the offset key: `legs_servo_offset_list` |
| `init_angles` | starting angles, one per pin; must match the count or `ValueError` |
| `init_order` | order to move them in on startup, with 0.15 s between |

`init_order` exists for a physical reason: moving eight servos at once browns out the supply.
`Pidog` orders shoulders before knees — `[0, 2, 4, 6, 1, 3, 5, 7]`.

Public surface: `servo_write_raw(list)`, `servo_write_all(list)`, `servo_move(targets,
speed=50, bpm=None)`, `do_action(name, step=1, speed=50)`, `set_offset(list)`,
`calibration()`, `reset(list=None)`, `soft_reset()`, `new_list(v)`, plus the attributes
`servo_positions`, `origin_positions`, `calibrate_position`, `direction`, `offset`, `max_dps`.

- `servo_write_raw` writes the angles straight through.
- `servo_write_all` adds `origin_positions`, `offset` and the `direction` sign first.
- `offset` is loaded from the calibration file and clamped to ±20° on save.
- `do_action` looks in `move_list`, which is **empty by default** — `Robot.do_action` raises
  `KeyError` unless you populated it yourself. The dog does not use it; `Pidog.do_action` is a
  different method.

### 5.3 The speed model — read this before tuning a gait

`servo_move` does not set a velocity. It computes a **duration**, then interpolates to it in
10 ms steps:

```
total_time_ms = -9.9 * speed + 1000        # speed 0 → 1000 ms, 100 → 10 ms
dps           = max_delta_deg / total_time_ms * 1000
if dps > max_dps:
    total_time_ms = max_delta_deg / max_dps * 1000
max_step = int(total_time_ms / 10)
```

Consequences:

1. `speed` is a duration knob, so **the same speed is a different angular rate for a small
   move and a large one** — the large one saturates against `max_dps` first.
2. Above the saturation point, raising `speed` changes nothing at all. For a 90° move:

   | Group | `max_dps` | Saturates at `speed` ≈ | Fastest 90° move |
   |---|---|---|---|
   | head | 300 | 71 | 300 ms |
   | legs | 428 | 80 | 210 ms |
   | tail | 500 | 83 | 180 ms |

3. The loop sleeps `step_time` minus the time the I2C writes took, so on a loaded bus the
   movement runs *slower* than requested, never faster.
4. `bpm` overrides the speed entirely: `total_time = 60 / bpm * 1000`, i.e. the move takes one
   beat.

```python
from robot_hat import Robot

arm = Robot([12, 13], name='demo', init_angles=[0, 0], init_order=[0, 1])
arm.servo_move([30, -30], speed=50)      # ~505 ms of interpolated motion
arm.set_offset([2, -1])                  # saved to disk, ±20 clamp
```


---

## 6. `I2C` — and why a failed read is not an exception

```python
I2C(address=None, bus=1)      # address may be a list: first one found on the bus wins
```

| Method | Returns |
|---|---|
| `write(data)` | `int`, `list` or `bytearray`; dispatches on length (1, 2, 3, or block) |
| `read(length=1)` | list of bytes |
| `mem_write(data, memaddr)` | writes a block at a register |
| `mem_read(length, memaddr)` | list of bytes |
| `scan()` | list of addresses present on the bus |
| `is_avaliable()` | `True` when `address` answers (the typo is in the API) |

### 6.1 The retry wrapper swallows failures

Every low-level operation goes through:

```python
for _ in range(self.RETRY):        # RETRY = 5
    try:
        return func(...)
    except OSError:
        continue
return False
```

So an I2C transaction that fails five times **returns `False` instead of raising**. `read(2)` then
hands you `[False, False]`, and arithmetic on it fails somewhere far away — or, worse, produces
`0` and looks like a valid reading.

```python
raw = i2c.mem_read(12, 0x0C)
if raw is False or any(b is False for b in raw):
    ...   # treat as "no data", not as zero
```

This is the single most important correctness rule in the layer, and it is why HoundMind's
`SensorSnapshot` carries validity flags next to every value (`PATTERNS.md` §4).

### 6.2 One bus, one writer

Each `Servo`, `PWM`, `ADC`, `Sh3001` and `RGBStrip` constructs its own `SMBus(1)`. Nothing in
`robot_hat` serialises them. Two threads writing at once interleave their transactions, and the
retry wrapper turns the resulting `OSError` into silence. If your program has more than one
thread touching hardware, take a lock around every call that reaches a device
(`PATTERNS.md` §2).

---

## 7. Motors (the HAT's wheel driver, not the legs)

The PiDog's legs are servos on the PWM channels; `Motor`/`Motors` drive the HAT's two DC motor
outputs and are used by SunFounder's car projects. They are documented here because they are
part of mastering the HAT, not because a dog has wheels.

```python
Motor(pwm, dir, is_reversed=False, mode=None, freq=100)
Motor.speed(-100.0 … 100.0)
```

The `dir` argument is a `Pin` in drive mode 1 (TC1508S) and a second `PWM` in mode 2 (TC618S).
The mode comes from `device.__device__.motor_mode`, so the same code works on both HAT revisions
— but a `Pin` passed on a mode-2 board raises `TypeError`.

| Mode | Forward | Backward | Stop |
|---|---|---|---|
| 1 | PWM on `pin_a`, `pin_b = 1` | PWM on `pin_a`, `pin_b = 0` | PWM 0 |
| 2 | PWM on `pin_a`, `pin_b = 0` | `pin_a = 0`, PWM on `pin_b` | 0 / 0 |

`Motors` adds the boring parts: `Motors(db=…)` wires `P13`+`D4` and `P12`+`D5`, remembers which
is left and right in its db file, and gives you `forward(speed)`, `backward(speed)`,
`turn_left(speed)`, `turn_right(speed)`, `speed(l, r)`, `stop()`, and `left`/`right` properties
that raise until `set_left_id(1|2)` has been run once.

`P12`/`P13` are timer 3, which is why the motors do not disturb the servos (`§4.3`).

---

## 8. `device` — what the HAT itself can do

```python
from robot_hat import device
```

| Function | Effect |
|---|---|
| `get_battery_voltage()` | `ADC('A4').read_voltage() * 3` → volts |
| `reset_mcu()` | pulses the MCU reset line (`MCURST`, GPIO 5, 10 ms low then high) |
| `enable_speaker()` / `disable_speaker()` | drives the revision's speaker-enable pin, then plays 0.5 s of silence to charge the amp |
| `set_pin(pin, value)` | drives a GPIO through the `pinctrl`/`raspi-gpio` command line |
| `get_usr_btn()` | `True` while the HAT button is held (`Pin('USER') == 0`) |
| `set_led(state)` / `get_led()` | HAT user LED — **`set_led` does not work in 2.5.x**, see §11.2 |
| `Devices()` | the revision detector described in `HARDWARE.md` §7.1 |

`reset_mcu()` is the recovery move for a wedged MCU: if every PWM write starts raising `OSError`
or the servos stop responding, that line is what revives the board without a power cycle.

`enable_speaker()` is not optional before audio: without it the amplifier stays muted and
`pygame` plays happily into silence.

### 8.1 `LED`

```python
from robot_hat.led import LED
led = LED('LED')            # or any Pin name
led.on(); led.off(); led.toggle()
led.blink(times=1, delay=0.1, pause=0)
led.blink_loop(times=1, delay=0.1, pause=0); led.blink_stop(); led.close()
```

This is the *HAT's* single LED — the dog's chest board is `RGBStrip`
(`PIDOG-EXPRESSION.md` §1), a different device on a different bus.

### 8.2 `UserButton`

```python
from robot_hat.user_button import UserButton
btn = UserButton()
btn.set_on_click(cb); btn.set_on_press(cb); btn.set_on_release(cb)
btn.set_on_long_press(cb, duration=2.0); btn.set_on_press_released(cb)
btn.start(); btn.stop()
btn.is_pressed(); btn.get_pressed_for()
```


---

## 9. Audio: `Music`, `Speaker`, TTS

### 9.1 `Music` — the one `Pidog` uses

```python
Music()                      # initialises pygame.mixer and calls enable_speaker()
```

| Method | Blocking? | Notes |
|---|---|---|
| `sound_play(file, volume=None)` | **yes** — sleeps for the clip length | volume 0–100, per-sound |
| `sound_play_threading(file, volume=None)` | no | one thread per call, never joined |
| `music_play(file, loops=1, start=0.0, volume=None)` | no | loops 0 = forever |
| `music_stop()`, `music_pause()`, `music_resume()`, `music_unpause()` | no | |
| `music_set_volume(v)` | no | 0–100 |
| `sound_length(file)` | — | seconds |
| `play_tone_for(freq, duration)` | yes | synthesises a sine on the fly |
| `note(name, natural=False)` | — | `'A4'`, `'C#5'` → Hz |
| `get_tone_data(freq, duration)` | — | raw PCM bytes |

Also exposes musical scaffolding: `time_signature(top, bottom)`, `key_signature(key)`,
`tempo(bpm, note)`, `NOTES` (MIDI-compatible name table), and the `KEY_*` / `*_NOTE` constants.

`sound_play_threading` is what `Pidog.speak` calls, so a bark never blocks the caller — but it
also never stops: a long clip keeps playing after your script moves on.

### 9.2 `Speaker` — the 2.5.x task-based player

```python
from robot_hat.speaker import Speaker
sp = Speaker()
task = sp.play('clip.mp3')
sp.get_progress(task); sp.pause(task); sp.resume(task); sp.stop(task); sp.list_tasks()
```

Handles `wav`/`flac`/`ogg` through `soundfile` and `mp3`/`m4a`/`aac`/`wma` through `librosa`,
i.e. two optional dependencies that are **not** in the core import list — a missing one fails at
`play()`, not at import. Use it when you need pause/resume/progress; use `Music` when you want
the vendor's own path.

### 9.3 TTS

```python
from robot_hat.tts import Espeak, Pico2Wave, Piper, OpenAI_TTS, EdgeTTS
tts = Espeak()
```

Each class is a thin wrapper over `sunfounder_voice_assistant.tts` that enables the speaker in
its constructor. The package is optional; `pip install sunfounder-voice-assistant` is its own
install, and the engines behind it (`espeak`, `pico2wave`, piper models, API keys) are separate
again. HoundMind does not depend on this path — `Pidog.speak()` (`PIDOG-EXPRESSION.md` §2.2) is
the vendor's own sound-file player, and `optional/voice.py` is HoundMind's own stack.

---

## 10. Storage and small utilities

### 10.1 `fileDB`

```python
fileDB(db, mode=None, owner=None)
db.get(name, default_value=None)     # str or the default
db.set(name, value)                  # str, creates the key if absent
```

A flat `name = value` text file with no types: everything comes back as a string, so `get`
followed by arithmetic needs your own coercion. `mode`/`owner` are applied by shelling out to
`sudo chmod`/`sudo chown`, which is why calibration writes need passwordless sudo.

`fileDB.set` opens the file for reading first — if the file was deleted underneath you, it
raises rather than recreating it. That is a real risk when a script runs as `pi` after a
`sudo` run re-owned `~/.config/pidog`.

### 10.2 `Config`

`robot_hat.config.Config` is the newer settings reader used by the CLI and the speaker helper.
It is not used by `Pidog`; if you need per-install settings in your own code it is a better
choice than `fileDB`, but do not mix the two in one file.

### 10.3 `utils`

| Function | Notes |
|---|---|
| `mapping(x, in_min, in_max, out_min, out_max)` | linear map; no clamp |
| `run_command(cmd, user=None, group=None)` | `shell=True`; returns `(status, output)` |
| `command_exists(cmd)`, `command_path(cmd)` | PATH plus sbin directories |
| `set_volume(v)` | `sudo amixer -M sset 'PCM' v%`, clamped 0–100 |
| `LazyReader(fn, interval=10)` | caches a read for `interval` seconds |
| `ignore_stderr()` | context manager around a noisy subprocess |
| `info/debug/warn/error` | ANSI-coloured `print` helpers |

`run_command` uses a shell and returns the output as one decoded string; it never raises on a
non-zero status, so check the status yourself.

---

## 11. Layer quirks worth memorising

### 11.1 Deprecated shims still in the import path

`utils.reset_mcu`, `utils.get_battery_voltage`, `utils.set_pin`, `utils.enable_speaker` and
`utils.disable_speaker` all emit `DeprecationWarning` and forward to `device`. `pidog` calls them
anyway, and silences every warning globally at import time:

```python
warnings.filterwarnings("ignore")   # pidog/pidog.py, module scope
```

That is a process-wide side effect: **your** warnings disappear too as soon as you
`import pidog`. If you need warnings during debugging, re-arm them after the import
(`PATTERNS.md` §5).

### 11.2 `device.set_led()` is a no-op

```python
pin = Pin("LED")
pin.value = state        # assigns an attribute, does not call value(state)
```

The pin is never driven. Use `robot_hat.led.LED('LED').on()` or `Pin('LED').value(1)` instead.
`device.get_led()` is correct.

### 11.3 `Pin.value()` flips direction

Reading a pin that was configured as output re-runs `setup(self.IN)`. There is no "write then
read back" on this layer; if you need the last value you wrote, keep it yourself.

### 11.4 `active_state` is accepted and dropped

`Pin(..., active_state=False)` does not invert anything in 2.5.x. Invert in your own code and do
not build on the argument.

### 11.5 `Robot.do_action` needs a `move_list` you must fill

`Robot.move_list = {}` by default and nothing populates it. Calling `robot.do_action('x')`
raises `KeyError`. The dog's named actions come from `Pidog.do_action`
(`PIDOG-ACTIONS.md` §2), a completely different method that reads `ActionDict`.

### 11.6 Everything is untyped

No annotations on the vendor surface, no validation on most arguments, and `False` where you
expected an exception. Coerce at your boundary: `float()`/`int()` with a default, and check for
`False` before treating a return as data.
