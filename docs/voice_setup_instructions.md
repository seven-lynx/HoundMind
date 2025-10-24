# Voice Recognition Setup for PiDog AI
> Author: 7Lynx · Doc Version: 2025.10.24

## 🎙️ Installing Voice Recognition Dependencies

To enable voice commands with "PiDog" wake word, you need to install additional packages:

### 1. Install Python packages
```bash
pip install speech_recognition pyaudio
```

### 2. On Raspberry Pi (if you get errors):
```bash
# Install system dependencies first
sudo apt update
sudo apt install portaudio19-dev python3-pyaudio

# Then install Python packages
pip3 install speech_recognition pyaudio
```

### 3. On Windows (if you get pyaudio errors):
```bash
# Try pre-compiled wheel
pip install pipwin
pipwin install pyaudio

# OR install manually from wheel
pip install https://download.lfd.uci.edu/pythonlibs/archived/pyaudio-0.2.11-cp39-cp39-win_amd64.whl
```

### 4. Test the installation:
```python
import speech_recognition as sr
import pyaudio
print("✅ Voice recognition ready!")
```

## 🎯 Voice Commands Available

Once installed, you can use these commands:

**Wake Word:** "PiDog" (must be said before each command)

### Basic Commands:
- **"PiDog sit"** - Makes PiDog sit down
- **"PiDog stand"** - Makes PiDog stand up  
- **"PiDog lie down"** - Makes PiDog lie down
- **"PiDog walk"** - Makes PiDog walk forward

### Movement Commands:
- **"PiDog turn left"** - Turn left
- **"PiDog turn right"** - Turn right
- **"PiDog wag tail"** - Happy tail wagging
- **"PiDog shake head"** - Shake head no
- **"PiDog nod"** - Nod head yes
- **"PiDog stretch"** - Stretching pose

### Behavior Commands:
- **"PiDog play"** - Enter playful mode
- **"PiDog explore"** - Start exploring behavior
- **"PiDog wander"** - Begin continuous wandering
- **"PiDog rest"** - Go to rest mode

### Emotional Commands:
- **"PiDog good dog"** - Praise (increases energy & happiness)
- **"PiDog bad dog"** - Scold (decreases energy, makes sad)

### Emergency:
- **"PiDog stop"** - Emergency stop all movement

## 💡 Tips for Best Voice Recognition:

1. **Speak clearly** - Enunciate the wake word "PiDog"
2. **Use quiet environment** - Background noise affects recognition
3. **Wait for LED feedback** - Cyan flash indicates command received  
4. **Keep commands simple** - Stick to the exact phrases listed above
5. **Internet required** - Uses Google Speech Recognition (online service)

## 🔧 Troubleshooting:

### "No module named speech_recognition"
```bash
pip install --upgrade speech_recognition
```

### "PyAudio not available"
- On Raspberry Pi: `sudo apt install python3-pyaudio`
- On Windows: Use `pipwin install pyaudio`
- On macOS: `brew install portaudio && pip install pyaudio`

### "Recognition request failed"
- Check internet connection (Google Speech API requires internet)
- Try speaking louder or closer to microphone
- Reduce background noise

### Voice recognition not working:
1. Check microphone permissions
2. Test with: `python -m speech_recognition`
3. Verify microphone is working with other applications
4. Try different microphone if available

## 🎯 How It Works:

1. **Wake Word Detection**: Continuously listens for "PiDog"
2. **Command Processing**: Extracts command after wake word
3. **Action Execution**: Matches command to PiDog action
4. **Visual Feedback**: LED changes to cyan when command received
5. **Audio Feedback**: PiDog responds with appropriate sounds
6. **Emotional Response**: Commands affect PiDog's emotional state

The system runs in a separate thread, so PiDog continues autonomous behavior while listening for voice commands!