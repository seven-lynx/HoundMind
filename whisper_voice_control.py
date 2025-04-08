#!/usr/bin/env python3
import whisper
import sounddevice as sd
import numpy as np
import threading
from scipy.io.wavfile import write
import importlib
from action import *  # ✅ Import all PiDog actions

# ✅ Load Whisper model
model = whisper.load_model("base")

# ✅ Define voice command mappings
commands = {
    "sit": "sit",
    "stand": "stop_and_stand",
    "bark": "bark",
    "wag tail": "wag_tail",
    "patrol": "start_patrol",
    "stop": "stop_behavior",
    "find open space": "find_open_space",
}

def record_audio(filename="command.wav", duration=3, sample_rate=44100):
    """Records voice input and saves it as a WAV file."""
    print("🎤 Listening for voice command...")
    audio_data = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype=np.int16)
    sd.wait()
    write(filename, sample_rate, audio_data)
    return filename

def process_voice_command():
    """Processes recorded voice input with Whisper and extracts commands."""
    audio_file = record_audio()
    result = model.transcribe(audio_file)
    command_text = result["text"].strip().lower()
    print(f"🗣️ Recognized command: {command_text}")
    return command_text

def execute_command(command_text):
    """Execute PiDog’s action based on recognized voice command using `action.py`."""
    for keyword, action_name in commands.items():
        if keyword in command_text:
            print(f"✅ Executing: {action_name}")
            action_function = globals().get(action_name)  # ✅ Call function from `action.py`
            if action_function:
                action_function()  # ✅ Run dynamically
            else:
                print(f"❌ Action `{action_name}` not found in `action.py`.")
            return
    
    print("❌ Unknown command. Try again.")

def listen_for_voice():
    """Continuously listen for voice commands and execute corresponding actions."""
    while True:
        command_text = process_voice_command()
        execute_command(command_text)

def start_behavior():
    """Start Whisper-based voice control for PiDog."""
    print("🎤 Voice control activated!")
    threading.Thread(target=listen_for_voice, daemon=True).start()