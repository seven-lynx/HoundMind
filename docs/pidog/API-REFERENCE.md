# PiDog & RobotHAT — API Reference

Status: **reference** — signature lookup. Behaviour, traps and examples live in the topic files;
this page is the index of names.
Verified against: `sunfounder/pidog@cee4bff`, `sunfounder/robot-hat@4556bd8` (2.5.x)
Pairs with: `INDEX.md` (task router)

Sections: §1 provenance · §2 `robot_hat` · §3 `pidog` · §4 refreshing this set

---

## 1. Provenance and licence

| Source | Repository | Pinned commit | Version |
|---|---|---|---|
| PiDog library | `github.com/sunfounder/pidog` | `cee4bff0874641143c1dad101a40ba88897a4c20` | 1.4.0 |
| Robot HAT library | `github.com/sunfounder/robot-hat` | `4556bd8ba81277819d8e9711319e32cd19504fe9` (branch `2.5.x`) | 2.5.x |

Reference documentation used for cross-checking:

- `docs.sunfounder.com/projects/pidog/en/latest/` — assembly, kit chapters, FAQ
- `docs.sunfounder.com/projects/robot-hat/en/latest/` — pinout, MCU, API pages

Licences: `pidog` is GPL-2.0, `robot-hat` is GPL-3.0, HoundMind is GPL-3.0. This set paraphrases
behaviour and signatures; the only vendor code in it is short illustrative fragments. Do not paste
vendor source into this repository.

**Evidence rule.** Everything here was read from the two commits above. Nothing was observed on a
running dog. The `README` FAQ and the printer's assembly diagrams are quoted as *claims*, not
verified.

---

## 2. `robot_hat`

```python
from robot_hat import (
    Pin, ADC, PWM, Servo, I2C, Robot, Motor, Motors, Music,
    Ultrasonic, ADXL345, RGB_LED, Buzzer, Grayscale_Module,
    fileDB, Config, device,
)
```

### 2.1 GPIO, ADC, PWM, servo

```python
Pin(pin, mode=None, pull=None, active_state=None)
    .value(v=None) .on() .off() .high() .low() .name() .close() .deinit()
    .setup(mode, pull=None, active_state=None)
    .irq(handler, trigger, bouncetime=200, pull=None)
    .dict(_dict=None) .__call__(value)

ADC(chn, address=None)                 # chn: 0-7 or 'A0'-'A7'
    .read() -> int 0..4095
    .read_voltage() -> float 0..3.3

PWM(channel, address=None)             # channel: 0-19 or 'P0'-'P19'
    .freq(f=None) .prescaler(p=None) .period(arr=None)
    .pulse_width(v=None) .pulse_width_percent(p=None)

Servo(channel, address=None)
    .angle(a) .pulse_width_time(us)
```

### 2.2 Joint groups and the bus

```python
Robot(pin_list, db=config_file, name=None, init_angles=None, init_order=None)
    .servo_write_raw(list) .servo_write_all(list)
    .servo_move(targets, speed=50, bpm=None)
    .do_action(motion_name, step=1, speed=50)
    .set_offset(list) .calibration() .reset(list=None) .soft_reset()
    .new_list(v)

I2C(address=None, bus=1)
    .write(data) .read(length=1)
    .mem_write(data, memaddr) .mem_read(length, memaddr)
    .scan() .is_avaliable()

Motor(pwm, dir, is_reversed=False, mode=None, freq=100)
    .speed(-100..100) .set_is_reverse(bool)
Motors(db=config_file)
    .left .right .speed(l, r) .forward(s) .backward(s)
    .turn_left(s) .turn_right(s) .stop()
    .set_left_id(1|2) .set_right_id(1|2) .set_left_reverse() .set_right_reverse()
```

### 2.3 Modules

```python
Ultrasonic(trig, echo, timeout=0.02)
    .read(times=10) -> cm | -1      ._read() -> cm | -1 | -2      .close()

ADXL345(*args, address=0x53, bus=1)
    .read(axis=None)                 # ADXL345.X/.Y/.Z

RGB_LED(r_pin, g_pin, b_pin, common=1)      # common: RGB_LED.ANODE (1) or .CATHODE
    .color(str|int|tuple|list)

Buzzer(buzzer)                       # PWM (passive) or Pin (active)
    .on() .off() .freq(f) .play(freq, duration=None)

Grayscale_Module(pin0, pin1, pin2, reference=None)     # three ADC channels
    .read(channel=None) .reference(ref=None) .read_status(datas=None)

LineTracker(left, middle, right, slopes=None, offsets=None)   # three ADC channels
    .read(raw=False) .read_channel(channel, raw=False)
    .get_line_position(data=None) .is_on_line(data=None)
    .is_on_cliff(data=None) .calibrate(light_data, dark_data)
    .set_calibration_data(slopes, offsets) .get_calibration_data()
    .set_cliff_threshold(threshold) .update_line_reference(values)
```

### 2.4 Audio and storage

```python
Music()
    .sound_play(file, volume=None) .sound_play_threading(file, volume=None)
    .music_play(file, loops=1, start=0.0, volume=None) .music_stop()
    .music_pause() .music_resume() .music_set_volume(v)
    .sound_length(file) .get_tone_data(freq, duration)
    .play_tone_for(freq, duration) .note(note, natural=False)
    .time_signature(top, bottom) .key_signature(key) .tempo(bpm, note)

Speaker()
    .play(path) -> task .get_progress(task) .pause(task) .resume(task)
    .stop(task) .list_tasks()

fileDB(db, mode=None, owner=None)
    .get(name, default_value=None) -> str      .set(name, value)
```

### 2.5 The HAT itself

```python
device.get_battery_voltage() -> float
device.reset_mcu()
device.enable_speaker() / device.disable_speaker()
device.set_pin(pin, value) / device.get_usr_btn()
device.set_led(state) / device.get_led()        # set_led is a no-op in 2.5.x
device.Devices()

LED(pin='LED')   .on() .off() .toggle(skip_stop=False) .blink(...) .blink_loop(...) .blink_stop() .close()
UserButton()     .set_on_click(cb) .set_on_press(cb) .set_on_release(cb)
                 .set_on_long_press(cb, duration=2.0) .set_on_press_released(cb)
                 .start() .stop() .is_pressed() .get_pressed_for()

utils.mapping(x, in_min, in_max, out_min, out_max)
utils.run_command(cmd, user=None, group=None) -> (status, output)

---

## 3. `pidog`

```python
from pidog import Pidog
from pidog.action_flow import ActionFlow, ActionStatus, Posetures
from pidog.actions_dictionary import ActionDict
```

### 3.1 `Pidog`

```python
Pidog(leg_pins=DEFAULT_LEGS_PINS, head_pins=DEFAULT_HEAD_PINS, tail_pin=DEFAULT_TAIL_PIN,
      leg_init_angles=None, head_init_angles=None, tail_init_angle=None)

# movement
head_move(target_yrps, roll_comp=0, pitch_comp=0, immediately=True, speed=50)
head_move_raw(target_angles, immediately=True, speed=50)
head_rpy_to_angle(target_yrp, roll_comp=0, pitch_comp=0) -> [yaw, roll, pitch]
legs_move(target_angles, immediately=True, speed=50)
legs_simple_move(angles_list, speed=90)
tail_move(target_angles, immediately=True, speed=50)
do_action(action_name, step_count=1, speed=50, pitch_comp=0)

# waiting and cancelling
wait_legs_done() / wait_head_done() / wait_tail_done() / wait_all_done()
is_legs_done() / is_head_done() / is_tail_done() / is_all_done()
legs_stop() / head_stop() / tail_stop() / body_stop()
stop_and_lie(speed=85)
close() / close_all_thread()

# pose and kinematics
set_legs(legs_list)                     # 4 x (y, z)
set_pose(x=None, y=None, z=None)
set_rpy(roll=None, pitch=None, yaw=None, pid=False)
pose2coords() -> {"leg": [...], "body": [...]}
pose2legs_angle() -> [8 angles]
coord2polar(coord) -> (alpha, beta)
fieldcoord2polar(coord) -> (alpha, beta)
polar2coord(angles) -> [x, y, z]        # broken, see PIDOG-MOTION.md §7.1
legs_angle_calculation(coords)          # classmethod, 4 x (y, z) -> 8 angles
set_angle(angles_list, speed=50, israise=False)   # broken, see §7.1
limit(min, max, x)

# calibration (writes user data)
set_leg_offsets(cali_list, reset_list=None)
set_head_offsets(cali_list)
set_tail_offset(cali_list)
set_imu_offsets(acc_offset=None, gyro_offset=None)
save_imu_offsets() / load_imu_offsets() -> bool / reset_imu_offsets()

# sensors and audio
read_distance() -> cm float | -1.0
speak(name, volume=100) / speak_block(name, volume=100)
get_battery_voltage() -> float
```

Class constants: `LEG=42`, `FOOT=76`, `BODY_LENGTH=117`, `BODY_WIDTH=98`,
`HEAD_DPS=300`, `LEGS_DPS=428`, `TAIL_DPS=500`, `HEAD_PITCH_OFFSET=45`,
`DEFAULT_LEGS_PINS`, `DEFAULT_HEAD_PINS`, `DEFAULT_TAIL_PIN`, `HEAD_*_MIN/MAX`, `KP/KI/KD`,
`SOUND_DIR`.

Attributes: `legs`, `head`, `tail`, `actions_dict`, `imu`, `rgb_strip`, `dual_touch`, `ears`,
`music`, `ultrasonic`, `distance`, `accData`, `gyroData`, `pitch`, `roll`, `pose`, `rpy`,
`body_height`, `legs_speed`, `head_speed`, `tail_speed`, `touch` (stale),
`*_action_buffer`, `*_thread_lock`.

### 3.2 `ActionDict`

Properties, each returning `(frames, part)`: `stand`, `sit`, `lie`, `lie_with_hands_out`,
`forward`, `backward`, `turn_left`, `turn_right`, `trot`, `stretch`, `push_up`, `doze_off`,
`half_sit`, `nod_lethargy`, `shake_head`, `tilting_head_left`, `tilting_head_right`,
`tilting_head`, `head_bark`, `wag_tail`, `head_up_down`.
Methods: `set_height(mm)`, `set_barycenter(mm)`.

### 3.3 `ActionFlow`

```python
ActionFlow(dog_obj)
    .start() .stop()
    .add_action(*actions) .set_status(status) .wait_actions_done()
    .run(action) .change_poseture(poseture) .set_head_pitch_init(pitch)
    .OPERATIONS            # 30 space-separated names
```

`ActionStatus`: `STANDBY`, `THINK`, `ACTIONS`, `ACTIONS_DONE`.
`Posetures`: `STAND`, `SIT`, `LIE`.

### 3.4 The sensor and actuator classes

```python
Sh3001(db="sh3001.config")              # I2C 0x36
    ._sh3001_getimudata() -> (acc, gyro) | False
    .sh3001_getimudata(aram, axis)      # aram: 'acc'|'gyro'|'all'
    .sh3001_gettempdata() -> degC
    .get_calibrated_data() -> (g, deg/s) | False
    .set_acc_calibration(bias=None, scale=None)
    .set_gyro_calibration(bias=None, scale=None)
    .reset_calibration() .set_offset(list=None)
    .calibrate(aram, stopfunc=stop_func, waitfunc=default_wait)
    .acc_calibrate_cmd()

RGBStrip(addr=0x74, nums=8)
    .set_mode(style='breath', color='white', bps=1, brightness=1)
    .show() .close() .monochromatic(color) .colorConvertor(color)
    STYLES, COLORS

DualTouch(sw1='D2', sw2='D3')
    .read() -> 'N'|'L'|'R'|'LS'|'RS'      .close()
    SLIDE_MAX_INTERVAL = 0.5

SoundDirection(busy_pin=6)
    .isdetected() -> bool      .read() -> 0..359 | -1      .close()

Walk(fb, lr).get_coords()
Trot(fb, lr).get_coords()
```

---

## 4. Refreshing this set

The clones used for the reading are not in the repository; reproduce them when you need to
re-verify:

```bash
git clone --depth 1 https://github.com/sunfounder/pidog.git
git clone --depth 1 -b 2.5.x https://github.com/sunfounder/robot-hat.git
git -C pidog rev-parse HEAD          # expect cee4bff…
git -C robot-hat rev-parse HEAD      # expect 4556bd8…
```

Then, for every changed file, update the "Verified against" header in **all nine** files, because a
partial update is a set that quietly disagrees with itself.

```powershell
cd 'C:\Users\Seito\Github\HoundMind'
Select-String -Path docs\pidog\*.md -Pattern 'Verified against' | Select-Object -First 9
```
