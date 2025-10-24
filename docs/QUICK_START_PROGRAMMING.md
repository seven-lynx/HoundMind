# PiDog Quick Start Programming Guide
> Author: 7Lynx · Doc Version: 2025.10.24

Get started programming your PiDog in 5 minutes with these essential code patterns.

## 🚀 Basic Setup Template

```python
#!/usr/bin/env python3
from pidog import Pidog
import time

# Basic safe program structure
dog = Pidog()
try:
    # Your code here
    dog.do_action("stand", speed=60)
    dog.wait_all_done()
    
finally:
    dog.close()  # Always call this!
```

## 🎯 Essential Commands Cheat Sheet

### Movement Commands
```python
# Basic poses
dog.do_action("stand", speed=60)     # Stand up
dog.do_action("sit", speed=50)       # Sit down  
dog.do_action("lie", speed=40)       # Lie down

# Walking
dog.do_action("forward", step_count=5, speed=70)   # Walk forward 5 steps
dog.do_action("backward", step_count=3, speed=60)  # Walk backward 3 steps
dog.do_action("turn_left", step_count=2, speed=80) # Turn left 2 steps
dog.do_action("turn_right", step_count=2, speed=80)# Turn right 2 steps

# Wait for completion
dog.wait_all_done()      # Wait for all movements
dog.wait_legs_done()     # Wait only for legs
```

### Head Control
```python
# Basic head movements [yaw, roll, pitch]
dog.head_move([[30, 0, 0]], speed=80)   # Look left 30°
dog.head_move([[-30, 0, 0]], speed=80)  # Look right 30°
dog.head_move([[0, 0, -20]], speed=80)  # Look down 20°
dog.head_move([[0, 0, 20]], speed=80)   # Look up 20°

# Multiple movements in sequence
nod_sequence = [[0, 0, -20], [0, 0, 20], [0, 0, 0]]
dog.head_move(nod_sequence, speed=70)
```

### Audio
```python
# Play sound effects
dog.speak("single_bark_1", volume=80)   # Bark sound
dog.speak("pant", volume=60)            # Happy panting
dog.speak("woohoo", volume=90)          # Excitement

# Available sounds: angry, confused_1, confused_2, confused_3, 
# growl_1, growl_2, howling, pant, single_bark_1, single_bark_2, 
# snoring, woohoo
```

### LED Lights
```python
# Set LED patterns
dog.rgb_strip.set_mode("breath", "blue", brightness=0.8)    # Breathing blue
dog.rgb_strip.set_mode("boom", "red", bps=2.0, brightness=1.0)  # Pulsing red
dog.rgb_strip.set_mode("bark", "yellow", brightness=0.9)    # Bark indicator

# Turn off
dog.rgb_strip.set_mode("breath", "black")
```

## 📱 Sensor Reading

```python
# Distance sensor
distance = dog.ultrasonic.read_distance()  # Returns cm
if distance < 20:
    print("Obstacle detected!")

# Touch sensor
touch = dog.dual_touch.read()
if touch == "L":        # Left side touched
    dog.speak("pant")
elif touch == "R":      # Right side touched  
    dog.do_action("wag_tail", step_count=5, speed=90)

# Sound direction
if dog.ears.isdetected():
    direction = dog.ears.read()  # 0-359°, 0=front
    print(f"Sound from {direction}°")

# IMU (motion sensor)
ax, ay, az = dog.accData      # Accelerometer
gx, gy, gz = dog.gyroData     # Gyroscope
```

## 🔄 Complete Behavior Loop

```python
#!/usr/bin/env python3
from pidog import Pidog
import time

def main():
    dog = Pidog()
    
    try:
        # Initialize
        dog.do_action("stand", speed=60)
        dog.wait_all_done()
        
        # Main behavior loop
        while True:
            # Read sensors
            distance = dog.ultrasonic.read_distance()
            touch = dog.dual_touch.read()
            
            # Behavior logic
            if touch != "N":
                # React to touch
                dog.speak("pant", volume=70)
                dog.rgb_strip.set_mode("breath", "green", brightness=0.8)
                
            elif distance > 0 and distance < 15:
                # Avoid obstacles
                dog.speak("confused_1", volume=50)
                dog.do_action("backward", step_count=1, speed=60)
                dog.do_action("turn_left", step_count=1, speed=70)
                
            # Small delay for 20Hz update rate
            time.sleep(0.05)
            
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        dog.close()

if __name__ == "__main__":
    main()
```

## 🛡️ Error Handling

```python
def safe_pidog_program():
    dog = None
    try:
        dog = Pidog()
        
        # Your code here
        dog.do_action("stand", speed=60)
        
    except KeyboardInterrupt:
        print("Program interrupted")
    except Exception as e:
        print(f"Error: {e}")
        if dog:
            dog.body_stop()  # Emergency stop
    finally:
        if dog:
            dog.close()
```

## 📊 Debugging

```python
# Show current status
def show_status(dog):
    print(f"Legs buffer: {len(dog.legs_action_buffer)} actions")
    print(f"Head buffer: {len(dog.head_action_buffer)} actions") 
    print(f"Current leg angles: {dog.leg_current_angles}")
    print(f"Current head angles: {dog.head_current_angles}")
    
    # Sensor readings
    distance = dog.ultrasonic.read_distance()
    touch = dog.dual_touch.read()
    print(f"Distance: {distance:.2f}cm, Touch: {touch}")
```

## 🎮 Quick Action Reference

| Action | Speed | Description |
|--------|-------|-------------|
| `"stand"` | 50-70 | Basic standing |
| `"sit"` | 40-60 | Sitting pose |  
| `"forward"` | 60-80 | Walking forward |
| `"push_up"` | 50-70 | Exercise movement |
| `"wag_tail"` | 80-100 | Happy tail wagging |
| `"shake_head"` | 60-80 | Head shake "no" |
| `"tilting_head"` | 30-50 | Curious head tilt |

## 🎨 LED Colors

**Named colors:** `"red"`, `"green"`, `"blue"`, `"yellow"`, `"purple"`, `"cyan"`, `"white"`, `"black"`, `"pink"`, `"orange"`

**Hex colors:** `"#FF0000"`, `"#00FF00"`, `"#0000FF"`, etc.

## 💡 Pro Tips

1. **Always use `dog.close()`** in a `finally:` block
2. **Use `wait_all_done()`** before complex sequences
3. **Limit speed to 0-100** (higher = faster)
4. **Head angles:** Yaw ±90°, Roll ±70°, Pitch -45° to +30°
5. **For smooth movement:** Use `immediately=False` to queue actions
6. **Emergency stop:** Call `dog.body_stop()` to halt all movement
7. **Audio needs sudo** on some systems: `sudo python3 script.py`

## 🔧 Common Patterns

### Queue Multiple Actions
```python
# Fill movement buffer
for _ in range(10):
    dog.legs_move([[45, -45, -45, 45, 45, -45, -45, 45]], 
                  immediately=False, speed=60)

# Let them execute while doing other things
dog.speak("woohoo")
time.sleep(3)
```

### Coordinated Movement
```python
# Move head and tail together
for _ in range(5):
    dog.head_move([[30, 0, 0], [-30, 0, 0]], immediately=False, speed=70)
    dog.tail_move([[30], [-30]], immediately=False, speed=90)
```

### Sensor-Reactive Behavior
```python
while True:
    if dog.ears.isdetected():
        direction = dog.ears.read()
        # Turn head toward sound
        yaw = max(-45, min(45, (direction - 180) / 4))
        dog.head_move([[yaw, 0, 0]], speed=80)
    time.sleep(0.05)
```

---

**Next Steps:** 
- Check `../examples/pidog_programming_examples.py` for complete working examples
- See `api_reference.md` for detailed API documentation
- Run examples with: `python3 ../examples/pidog_programming_examples.py`