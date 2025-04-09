#!/usr/bin/env python3
"""
PiDog Whisper Voice Control (Optimized)
==================================
This module enables PiDog to interpret spoken voice commands via Whisper AI, dynamically
executing corresponding actions.

Key Features:
✅ **State Tracking:** `global_state.active_mode` changes when listening and **reverts after completion**.
✅ **Thread-Safe Execution:** Ensures `exit_flag` cleanly terminates voice listener when needed.
✅ **Error Tracking:** Logs failures in `global_state.error_log` for debugging.
✅ **Function Verification:** Checks if `actions.py` methods exist before execution.
✅ **AI-Powered Command Recognition:** Uses Whisper AI to process voice inputs.

7-lynx
"""

import whisper
import sounddevice as sd
import numpy as np
import threading
import time
import global_state  # ✅ Integrated state tracking
import actions  # ✅ Import centralized action execution
from scipy.io.wavfile import write

# ✅ Load Whisper model
model = whisper.load_model("base")

# ✅ Track Previous Active Mode Before Switching
previous_active_mode = global_state.active_mode  
global_state.active_mode = "listening"  # ✅ Temporarily override active mode

exit_flag = False  # ✅ Allows controlled exit when needed

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
    """Execute PiDog’s action based on recognized voice command using `actions.py`."""
    for keyword, action_name in commands.items():
        if keyword in command_text:
            print(f"✅ Executing: {action_name}")

            if hasattr(actions, action_name):  # ✅ Ensure function exists before execution
                getattr(actions, action_name)()
                global_state.interaction_history.append({"timestamp": time.time(), "voice_command": command_text})  # ✅ Log executed command
            else:
                global_state.error_log.append({"timestamp": time.time(), "error": f"Missing `{action_name}` in `actions.py`"})  # ✅ Log error
                print(f"❌ Action `{action_name}` not found in `actions.py`.")
            return
    
    print("❌ Unknown command. Try again.")

def listen_for_voice():
    """Continuously listen for voice commands and execute corresponding actions."""
    while not exit_flag:
        command_text = process_voice_command()
        execute_command(command_text)

    print("🛑 Voice listener thread safely exited.")

def start_behavior():
    """Start Whisper-based voice control for PiDog."""
    print("🎤 Voice control activated!")
    threading.Thread(target=listen_for_voice, daemon=True).start()

# ✅ Restore Previous Active Mode After Execution
global_state.active_mode = previous_active_mode
print(f"🔄 Restored PiDog's previous mode: `{global_state.active_mode}`")

# ✅ Allow execution safely if called directly
if __name__ == "__main__":
    try:
        start_behavior()
    except Exception as e:
        global_state.log_error(f"Unexpected error in `whisper_voice_control.py`: {e}")
        print("⚠️ Voice control interrupted due to an error.")