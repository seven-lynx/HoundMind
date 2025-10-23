# Complete PiDog API Reference

🎓 This is your "dictionary" of all PiDog commands!

**What is an API?** API = "Application Programming Interface" - fancy words for "all the commands you can use to control your PiDog"

Think of this like a menu at a restaurant:
- 🍕 **Method names** = The dishes (like "do_action" or "head_move")  
- 🥗 **Parameters** = The ingredients/options (like speed=50 or step_count=3)
- 🍰 **Returns** = What you get back (like sensor readings or True/False)

**How to read this guide:**
- 💚 **Beginner Friendly** = Start here! Safe and easy to use
- 🟡 **Intermediate** = Need some experience first
- 🔴 **Advanced** = For experts only - can break things if used wrong

---

## 🤖 Core PiDog Class - Your Robot Controller

### Creating Your PiDog Controller (Constructor)

**💚 BEGINNER:** Most of the time, just use `Pidog()` with no parameters!

```python
# Simple way (recommended for beginners)
dog = Pidog()

# Advanced way (only if you know what you're doing)  
dog = Pidog(
    leg_pins=[2, 3, 7, 8, 0, 1, 10, 11],      # Which pins control leg servos
    head_pins=[4, 6, 5],                       # Head servo pins [left/right, tilt, up/down]  
    tail_pin=[9],                              # Tail servo pin
    leg_init_angles=None,                      # Starting leg positions (None = safe default)
    head_init_angles=None,                     # Starting head position (None = safe default)
    tail_init_angle=None                       # Starting tail position (None = safe default)
)
```

**🎯 Parameter Guide:**
- **pins** = Hardware connection numbers (only change if you modified the robot)
- **init_angles** = Starting positions in degrees (None = use safe defaults)
- **None** = "Use the smart default values" (recommended for beginners)

---

## 🎯 Core PiDog Class

### Constructor

```python
class Pidog(
    leg_pins: List[int] = [2, 3, 7, 8, 0, 1, 10, 11],
    head_pins: List[int] = [4, 6, 5],  # [yaw, roll, pitch]  
    tail_pin: List[int] = [9],
    leg_init_angles: List[int] = None,     # Default: lie position
    head_init_angles: List[int] = None,    # Default: [0, 0, 45] (pitch offset)
    tail_init_angle: List[int] = None      # Default: [0]
)
```

### 🎮 Global Control Methods - Your Main Remote Control

**💚 BEGINNER FRIENDLY:** These are the most important commands every PiDog owner should know!

| Method | What It Does | Parameters | Beginner Tips |
|--------|-------------|------------|---------------|
| 🎬 `do_action(action_name, step_count=1, speed=50)` | **Most important command!** Makes PiDog perform pre-made actions | `action_name`: "sit", "stand", "forward", etc.<br>`step_count`: How many times (1-20)<br>`speed`: How fast (1-100, start with 50) | **START HERE!** This is like pressing buttons on a remote control. Try "sit", "stand", "forward" first! |
| ⏳ `wait_all_done()` | **Safety command!** Waits until PiDog finishes current action | None | **Always use this** after `do_action()` to avoid "command collision" |
| 🛑 `body_stop()` | **Emergency stop!** Immediately stops all movement | None | **Emergency use only** - like slamming on brakes. Use if PiDog acts weird |
| 😴 `stop_and_lie()` | **Safe stop** - stops movement and lies down safely | None | **Better than body_stop()** - puts PiDog in safe sleeping position |
| 🔒 `close()` | **Always use when done!** Safely shuts down PiDog | None | **CRITICAL** - like turning off a car engine. Prevents overheating! |

**🎯 Beginner Usage Pattern:**
```python
dog = Pidog()                          # 1. Wake up PiDog
dog.do_action("stand")                 # 2. Give command  
dog.wait_all_done()                    # 3. Wait for completion
dog.close()                            # 4. Always close when done!
```

---

## 🦵 Leg Control - PiDog's "Muscles" (8 Servos)

**🔴 ADVANCED WARNING:** Direct leg control can damage your PiDog if used incorrectly! Beginners should stick to `do_action()` commands.

### 🧭 Understanding PiDog's Anatomy

Think of PiDog's legs like your own arms and legs - each has joints that bend:

```
🐕 PiDog Leg Layout (viewed from above):
    FRONT               BACK
LF (Left Front)    LH (Left Hind)
RF (Right Front)   RH (Right Hind)

Each leg has 2 servos (like 2 joints):
- Shoulder servo: Lifts leg up/down  
- Leg servo: Moves leg forward/back
```

**📍 Servo Index Numbers:**
```
[0] = Left Front shoulder    [4] = Left Hind shoulder
[1] = Left Front leg         [5] = Left Hind leg
[2] = Right Front shoulder   [6] = Right Hind shoulder  
[3] = Right Front leg        [7] = Right Hind leg
```

### 🔧 Advanced Leg Control Methods

| Method | Skill Level | What It Does | Parameters | Danger Level |
|--------|-------------|--------------|------------|--------------|
| 🟡 `legs_move(target_angles, immediately=True, speed=50)` | **Intermediate** | Move legs to custom positions | `target_angles`: List of 8 angles<br>`immediately`: True=wait, False=queue<br>`speed`: 1-100 | ⚠️ **Medium** - Wrong angles can stress servos |
| 🔴 `legs_simple_move(angles_list, speed=90)` | **Expert** | Direct servo control (no safety) | `angles_list`: [8 angles], `speed`: 1-100 | 🚨 **HIGH** - No angle validation! |
| 💚 `is_legs_done()` | **Beginner Safe** | Check if legs finished moving | None | ✅ **Safe** - Just checks status |

**🎯 Safe Angle Ranges (to avoid breaking servos):**
- **Shoulder servos:** -90° to +90° (safe range)
- **Leg servos:** -90° to +90° (safe range)  
- **⚠️ Beyond ±90°:** Risk of mechanical damage!

**💡 Beginner Alternative:** Use `do_action("custom_pose")` instead of direct leg control!
| `wait_legs_done()` | Wait for leg movement to complete | None | None |
| `legs_stop()` | Stop leg movement | None | None |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `legs_action_buffer` | List | Queue of pending leg movements |
| `leg_current_angles` | List[int] | Current leg servo positions |
| `legs_speed` | int | Current leg movement speed |

---

## 👤 Head Control (3 Servos)

### Servo Layout: [Yaw, Roll, Pitch]
- **Yaw**: -90° to +90° (left/right)
- **Roll**: -70° to +70° (tilt left/right)  
- **Pitch**: -45° to +30° (up/down)

### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `head_move(target_angles, roll_comp=0, pitch_comp=0, immediately=True, speed=50)` | Move head with optional IMU compensation | `target_angles`: List[List[int]], `roll_comp`: float, `pitch_comp`: float, `immediately`: bool, `speed`: int | None |
| `is_head_done()` | Check if head movement complete | None | bool |
| `wait_head_done()` | Wait for head movement to complete | None | None |
| `head_stop()` | Stop head movement | None | None |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `head_action_buffer` | List | Queue of pending head movements |
| `head_current_angles` | List[int] | Current head servo positions |
| `head_speed` | int | Current head movement speed |

---

## 🐕 Tail Control (1 Servo)

### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `tail_move(target_angles, immediately=True, speed=50)` | Move tail to specified angle | `target_angles`: List[List[int]], `immediately`: bool, `speed`: int | None |
| `is_tail_done()` | Check if tail movement complete | None | bool |
| `wait_tail_done()` | Wait for tail movement to complete | None | None |
| `tail_stop()` | Stop tail movement | None | None |

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `tail_action_buffer` | List | Queue of pending tail movements |
| `tail_current_angles` | List[int] | Current tail servo position |
| `tail_speed` | int | Current tail movement speed |

---

## 🔊 Audio System

### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `speak(name, volume=100)` | Play sound effect | `name`: str (without extension), `volume`: int (0-100) | None |

### Available Sound Effects

| Sound File | Description |
|------------|-------------|
| `"angry"` | Angry bark sound |
| `"confused_1"` | Confused whine variant 1 |
| `"confused_2"` | Confused whine variant 2 |
| `"confused_3"` | Confused whine variant 3 |
| `"growl_1"` | Low growl variant 1 |
| `"growl_2"` | Low growl variant 2 |
| `"howling"` | Wolf-like howling |
| `"pant"` | Happy panting |
| `"single_bark_1"` | Single bark variant 1 |
| `"single_bark_2"` | Single bark variant 2 |
| `"snoring"` | Sleeping snore sound |
| `"woohoo"` | Excited celebration |

---

## 💡 RGB LED Strip (11 LEDs)

### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `rgb_strip.set_mode(style, color, bps=1.0, brightness=1.0)` | Set LED pattern | `style`: str, `color`: str, `bps`: float, `brightness`: float (0.0-1.0) | None |
| `rgb_strip.close()` | Turn off all LEDs | None | None |

### LED Styles

| Style | Description | Parameters |
|-------|-------------|------------|
| `"breath"` | Smooth breathing effect | `color`, `brightness` |
| `"boom"` | Pulsing boom effect | `color`, `bps` (beats per second), `brightness` |
| `"bark"` | Bark indicator pattern | `color`, `brightness` |

### Color Options

**Named Colors:** `"red"`, `"green"`, `"blue"`, `"yellow"`, `"purple"`, `"cyan"`, `"white"`, `"black"`, `"pink"`, `"orange"`

**Hex Colors:** `"#FF0000"`, `"#00FF00"`, etc.

---

## 📏 Ultrasonic Distance Sensor

### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `ultrasonic.read_distance()` | Get distance measurement | None | float (centimeters) |

---

## ⚖️ IMU (Inertial Measurement Unit)

### Properties

| Property | Type | Description | Units |
|----------|------|-------------|-------|
| `accData` | Tuple[int, int, int] | Raw accelerometer [X, Y, Z] | 1G = ±16384 |
| `gyroData` | Tuple[int, int, int] | Raw gyroscope [X, Y, Z] | degrees/second |

### Usage Example

```python
ax, ay, az = dog.accData
gx, gy, gz = dog.gyroData

# Convert to G force
ax_g = ax / 16384.0
ay_g = ay / 16384.0  
az_g = az / 16384.0
```

---

## 👂 Sound Direction Sensor

### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `ears.isdetected()` | Check if sound detected | None | bool |
| `ears.read()` | Get sound direction | None | int (0-359°) |

### Direction Reference
- **0°**: Front
- **90°**: Right side
- **180°**: Behind  
- **270°**: Left side

---

## ✋ Dual Touch Sensor

### Methods

| Method | Description | Parameters | Returns |
|--------|-------------|------------|---------|
| `dual_touch.read()` | Read touch status | None | str |

### Touch Status Values

| Value | Description |
|-------|-------------|
| `"N"` | No touch detected |
| `"L"` | Left side touched |
| `"R"` | Right side touched |
| `"LS"` | Left to right swipe |
| `"RS"` | Right to left swipe |

---

## 🎭 Complete Preset Actions List

### Basic Poses

| Action | Description | Recommended Speed |
|--------|-------------|-------------------|
| `"stand"` | Standing position | 50-70 |
| `"sit"` | Sitting position | 40-60 |
| `"lie"` | Lying down flat | 30-50 |
| `"half_sit"` | Partial sitting | 40-60 |

### Locomotion

| Action | Description | Recommended Speed | Notes |
|--------|-------------|-------------------|-------|
| `"forward"` | Walk forward | 60-80 | Use `step_count` |
| `"backward"` | Walk backward | 50-70 | Use `step_count` |
| `"turn_left"` | Turn left in place | 60-80 | Use `step_count` |
| `"turn_right"` | Turn right in place | 60-80 | Use `step_count` |
| `"trot"` | Trotting gait | 70-90 | Use `step_count` |

### Exercises & Tricks

| Action | Description | Recommended Speed |
|--------|-------------|-------------------|
| `"stretch"` | Stretching pose | 40-60 |
| `"push_up"` | Push-up exercise | 50-70 |

### Head Movements

| Action | Description | Recommended Speed |
|--------|-------------|-------------------|
| `"shake_head"` | Shake head "no" | 60-80 |
| `"tilting_head"` | Curious head tilt | 30-50 |
| `"tilting_head_left"` | Tilt head left | 30-50 |
| `"tilting_head_right"` | Tilt head right | 30-50 |
| `"head_bark"` | Head movement while barking | 70-90 |
| `"head_up_down"` | Nod head "yes" | 50-70 |

### Tail & Expression

| Action | Description | Recommended Speed |
|--------|-------------|-------------------|
| `"wag_tail"` | Happy tail wagging | 80-100 |

### Sleep & Tired

| Action | Description | Recommended Speed |
|--------|-------------|-------------------|
| `"doze_off"` | Sleepy/tired pose | 20-40 |
| `"nod_lethargy"` | Sleepy head nods | 20-30 |

---

## 🔧 Advanced Properties & Buffers

### Internal Buffers

| Buffer | Type | Description |
|--------|------|-------------|
| `legs_action_buffer` | List[List[int]] | Queued leg movements |
| `head_action_buffer` | List[List[int]] | Queued head movements |
| `tail_action_buffer` | List[List[int]] | Queued tail movements |

### Hardware Limits

| Component | Parameter | Min | Max | Default |
|-----------|-----------|-----|-----|---------|
| Head Yaw | Servo range | -90° | +90° | 0° |
| Head Roll | Servo range | -70° | +70° | 0° |
| Head Pitch | Servo range | -45° | +30° | +45° |
| All Servos | Speed | 0 | 100 | 50 |
| Audio | Volume | 0 | 100 | 100 |
| RGB | Brightness | 0.0 | 1.0 | 1.0 |

### Thread Control

| Property | Type | Description |
|----------|------|-------------|
| `exit_flag` | bool | Global thread shutdown flag |
| `thread_list` | List[str] | Active thread names |

---

## 📚 Usage Patterns & Examples

### Basic Program Structure

```python
from pidog import Pidog

dog = Pidog()
try:
    # Your code here
    dog.do_action("stand", speed=60)
    dog.wait_all_done()
finally:
    dog.close()  # Always call this
```

### Queue Multiple Actions

```python
# Fill buffers with multiple movements
for _ in range(10):
    dog.legs_move([[90, -30, -90, 30, 80, 70, -80, -70]], 
                  immediately=False, speed=60)
    dog.head_move([[30, 0, 0], [-30, 0, 0]], 
                  immediately=False, speed=80)

# Let them execute
time.sleep(5)
dog.body_stop()
```

### Sensor-Driven Behavior

```python
while True:
    if dog.ears.isdetected():
        direction = dog.ears.read()
        yaw = max(-45, min(45, (direction - 180) / 4))
        dog.head_move([[yaw, 0, 0]], speed=80)
    
    touch = dog.dual_touch.read()
    if touch == "L":
        dog.speak("pant", volume=80)
    
    time.sleep(0.05)
```

---

## 🛠️ Diagnostic Tools

### Introspection Helpers

```python
# List all available methods
from pidog import Pidog
import inspect

methods = [name for name, obj in inspect.getmembers(Pidog) 
           if inspect.isfunction(obj) or inspect.ismethod(obj)]
print("Available methods:", methods)

# List all sound effects
import os
import pidog

sound_dir = os.path.join(os.path.dirname(pidog.__file__), 'sounds')
sounds = [f.split('.')[0] for f in os.listdir(sound_dir) 
          if f.endswith(('.wav', '.mp3', '.ogg'))]
print("Available sounds:", sounds)

# Test all actions
dog = Pidog()
actions = ['sit', 'stand', 'lie', 'forward', 'backward', 'wag_tail']
for action in actions:
    try:
        dog.do_action(action, step_count=1, speed=10)
        print(f"✓ {action}")
    except Exception as e:
        print(f"✗ {action}: {e}")
dog.close()
```

### Buffer Monitoring

```python
def show_buffer_status(dog):
    """Show current buffer status"""
    print(f"Legs: {len(dog.legs_action_buffer)} queued")
    print(f"Head: {len(dog.head_action_buffer)} queued") 
    print(f"Tail: {len(dog.tail_action_buffer)} queued")
    print(f"Exit flag: {dog.exit_flag}")
```

This completes the comprehensive PiDog API reference with all methods, parameters, return values, and practical usage examples based on the actual source code.