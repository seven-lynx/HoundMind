#!/usr/bin/env python3
import pyttsx3  # AI text-to-speech
import openai  # Free AI chatbot API
import time
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)
dog.wait_all_done()
time.sleep(0.5)

# Initialize AI voice engine
voice_engine = pyttsx3.init()
voice_engine.setProperty("rate", 150)
voice_engine.setProperty("volume", 1.0)

def speak(text):
    """Make PiDog speak."""
    print(f"PiDog says: {text}")
    voice_engine.say(text)
    voice_engine.runAndWait()

def get_chatbot_response(prompt):
    """Retrieve AI-generated response."""
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    return response["choices"][0]["message"]["content"]

def companion_mode():
    """Continuously chat with PiDog."""
    print("Entering Companion Mode...")
    speak("Hello! I'm PiDog! Let's talk!")

    try:
        while True:
            prompt = input("You: ")  # User input
            if prompt.lower() == "exit":
                speak("Okay, talk to you later!")
                break
            
            response = get_chatbot_response(prompt)
            speak(response)
    
    except KeyboardInterrupt:
        speak("Okay, shutting down chat mode.")
        dog.do_action("stand", speed=50)
        dog.wait_all_done()
        dog.close()

# Start Companion Mode
companion_mode()