#!/usr/bin/env python3
import pyttsx3  # AI text-to-speech library
import speech_recognition as sr  # Speech recognition
import time
from pidog import Pidog

# Initialize Pidog
dog = Pidog()
dog.do_action("stand", speed=80)  # Ensure PiDog is ready
dog.wait_all_done()
time.sleep(0.5)

# Initialize AI voice engine
voice_engine = pyttsx3.init()
voice_engine.setProperty("rate", 150)  # Adjust speaking speed
voice_engine.setProperty("volume", 1.0)  # Max volume

def speak(text):
    """Make PiDog speak using AI text-to-speech."""
    print(f"PiDog says: {text}")
    voice_engine.say(text)
    voice_engine.runAndWait()

def listen_for_command():
    """Use microphone to listen for voice commands."""
    recognizer = sr.Recognizer()
    
    with sr.Microphone() as source:
        print("PiDog is listening for commands...")
        recognizer.adjust_for_ambient_noise(source)  # Reduce background noise
        try:
            audio = recognizer.listen(source, timeout=5)  # Listen for input
            command = recognizer.recognize_google(audio)  # Convert speech to text
            print(f"Detected command: {command.lower()}")
            return command.lower()
        except sr.UnknownValueError:
            speak("I didn't understand that. Try again!")
            return None
        except sr.RequestError:
            speak("There was an error with speech recognition.")
            return None

def voice_personality_mode():
    """Continuously listen for voice interactions and respond with personality."""
    print("Entering AI Voice Personality Mode...")
    speak("Hello! I'm PiDog! Let's talk!")

    try:
        while True:
            command = listen_for_command()
            if command:
                if "hello" in command:
                    speak("Hi there! How's your day going?")
                elif "what can you do" in command:
                    speak("I can patrol, guard, follow, and talk with you! Isn't that awesome?")
                elif "good dog" in command:
                    speak("Aww, thanks! That makes me happy!")
                    dog.do_action("tail_wag", speed=80)
                elif "stop" in command:
                    speak("Alright, I'll wait here!")
                    dog.do_action("stand", speed=80)
                elif "tell me a joke" in command:
                    speak("Why did the robot dog fail obedience school? It kept rebooting!")
                else:
                    speak("Hmm, I don't know that command yet. Try asking me something else!")

    except KeyboardInterrupt:
        speak("Okay, shutting down voice mode. Talk to you later!")
        print("Exiting AI Voice Mode...")
        dog.do_action("stand", speed=50)  # Stop movement safely
        dog.wait_all_done()
        dog.close()  # Shut down Pidog properly

# Start AI Voice Personality Mode
voice_personality_mode()