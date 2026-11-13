# PiDog & RobotHAT — Expression

Status: **reference** — the LED board and the audio path: what the dog can show and say, and
which vendor calls block.
Verified against: `sunfounder/pidog@cee4bff` (pidog 1.4.0), `sunfounder/robot-hat@4556bd8` (2.5.x)
Pairs with: `ROBOTHAT.md` §9 (the `Music`/`Speaker` primitives), `PIDOG-ACTIONS.md` (presets that
speak)

Sections: §1 LED board · §2 sound effects · §3 music and tones · §4 voice, STT, LLM · §5 quirks

---

## 1. The LED board

Eleven addressable pixels on I2C `0x74`, driven by `RGBStrip`.

```python
dog.rgb_strip.set_mode(style='breath', color='white', bps=1, brightness=1)
dog.rgb_strip.show()          # render one frame — the rgb thread already does this
dog.rgb_strip.close()
```

`Pidog` constructs it as `RGBStrip(addr=0x74, nums=11)` and runs a thread that calls `show()`
continuously, so in practice you only ever call `set_mode`.

### 1.1 Styles

| Style | What it looks like |
|---|---|
| `monochromatic` | every pixel the same colour, no animation |
| `breath` | a soft pulse travelling along the strip |
| `boom` | a stronger, faster swell |
| `bark` | a sharp flash tuned for a bark |
| `speak` | a gentler flash tuned for speech |
| `listen` | a slow sweep, tuned for "paying attention" |

Any other string raises `ValueError`.

### 1.2 Colours

| Input | Example |
|---|---|
| name, case-insensitive | `'white' 'black' 'red' 'yellow' 'green' 'blue' 'cyan' 'magenta' 'pink'` |
| hex string | `'#a2c20c'` |
| 24-bit int | `0xa2c20c` |
| sequence | `[168, 192, 203]`, `(168, 192, 203)` |

Anything else raises `ValueError: Invalid color value.`

### 1.3 The two rate knobs

- `bps` — beats per second: how many animation frames per second the style advances. This is the
  knob for "make the breathing slower". HoundMind passes it through explicitly
  (`hal/vendor.py` → `_rgb`), because dropping it pins every effect to the vendor default.
- `brightness` — a multiplier applied to every channel, nominally 0–1. It is **not clamped**:
  `brightness=2` asks the driver for values above 255. Stay at or below 1.

`set_mode` only stores state; the rendering thread picks it up on its next `show()`. There is no
acknowledgement, so "set the LED then exit immediately" often shows nothing.

```python
dog.rgb_strip.set_mode('monochromatic', 'green', brightness=0.4)   # calm, steady

---

## 2. Sound effects

`Pidog` owns a `Music` object and two speaking methods.

```python
dog.speak('single_bark_1', volume=80)          # returns immediately
dog.speak_block('single_bark_1', volume=80)    # waits for the clip to finish
```

### 2.1 Name resolution

1. If `os.path.isfile(name)` → play that path (a full path always works).
2. Else `~/pidog/sounds/<name>.mp3`.
3. Else `~/pidog/sounds/<name>.wav`.
4. Else print `No sound found for <name>` and return `False`.

**The search path is the clone directory, not the installed package.** `SOUND_DIR` is
`f"{UserHome}/pidog/sounds/"`, resolved from `SUDO_USER`. A `pip install ./pidog` whose clone is
later deleted leaves every effect missing, and a script running as a different user looks in a
different home. If the speaker works but the dog is silent, check that directory first.

### 2.2 The effects that ship

`angry`, `confused_1`, `confused_2`, `confused_3`, `growl_1`, `growl_2`, `howling`, `pant`,
`single_bark_1`, `single_bark_2`, `snoring`, `woohoo`.

These are the vendor's names. Nothing validates them, so a build with fewer files logs a warning
and continues.

### 2.3 Every `speak` shells out to `sudo`

Both methods run `sudo killall pulseaudio` before playing — a workaround for VNC sessions with no
audio. That means a subprocess per call, a sudo requirement, and a few milliseconds of latency
before the clip starts. Without passwordless sudo it prints to stdout and carries on.

`sound_play_threading` spawns a **new thread per call** and never joins it. Ten barks in a second
is ten threads and ten overlapping clips; there is no mute, no queue and no cancellation.

---

## 3. Music and tones

The same `Music` object as `ROBOTHAT.md` §9.1:

```python
m = dog.music
m.sound_play('/home/pi/tone.wav', volume=60)          # blocking
m.music_play('/home/pi/theme.mp3', loops=1)           # background, non-blocking
m.music_stop()
m.play_tone_for(m.note('A4'), 0.3)                    # synthesised beep
```

`music_play` accepts `loops=0` for "forever" — stop it yourself, because there is no timeout and
`close()` does not stop music.

`note()` maps `'A4'`, `'C#5'` and the 128-entry `NOTES` table to Hz. `key_signature()` shifts
non-natural notes, so `note('C', natural=False)` follows the current key.

---

## 4. Voice, STT and LLM

`pidog` ships three one-line re-export shims:

```python
# pidog/tts.py
from robot_hat.tts import *
# pidog/stt.py
from robot_hat.stt import *
# pidog/llm.py
from robot_hat.llm import *
```

So `from pidog.tts import Espeak` reaches the same class as `robot_hat.tts`
(`ROBOTHAT.md` §9.3). Everything behind it — `sunfounder_voice_assistant`, Piper models, Vosk
models, API keys — is an optional install with its own setup and its own binaries.

**The dog has no built-in speech.** Before TTS exists at all the speaker must be enabled:
`device.enable_speaker()`, which `Music()` and every TTS class already do. HoundMind's
`optional/voice.py` is its own stack and does not depend on these shims.

---

## 5. Quirks

1. **The LED thread never sleeps.** It calls `show()` in a loop for the life of the process,
   holding a share of the single I2C bus. That contention is real — it is the usual cause of
   "the gait stutters when the LEDs are on".
2. **`speak` is fire-and-forget with no handle.** No id, no stop, no volume change for a clip
   that is already playing.
3. **`sudo killall pulseaudio` on every call**, including on a system that has no pulseaudio.
4. **The sound path depends on the shell user**, via `SUDO_USER` and `getent passwd`.
5. **No volume persistence.** `sound_play(volume=…)` sets the volume on that one `Sound` object;
   a later call with `volume=None` keeps pygame's default, not the last value.
6. **`brightness` is unclamped** and `bps` is only checked for being a number.

---

## Used by HoundMind

| Vendor call | Where |
|---|---|
| `rgb_strip.set_mode(style, color, bps, brightness)` | `src/houndmind_ai/hal/vendor.py` → `_rgb` |
| `dog.speak(name, volume)` | `hal/vendor.py` → `_say` (own worker thread, latest wins) |
| `dog.music` | not used directly; `speak` covers it |
| `pidog.tts` / `pidog.stt` / `pidog.llm` | not used; `optional/voice.py` is the runtime's stack |
