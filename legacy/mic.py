import speech_recognition as sr

def test_microphone():
    recognizer = sr.Recognizer()

    # Use the default microphone (ensure your USB mic is detected)
    with sr.Microphone() as source:
        print("Testing microphone... Speak into the mic.")
        recognizer.adjust_for_ambient_noise(source)  # Reduce background noise
        audio = recognizer.listen(source)

    try:
        print("Processing audio...")
        text = recognizer.recognize_google(audio)  # Convert speech to text
        print(f"Recognized Speech: {text}")
    except sr.UnknownValueError:
        print("Could not understand audio")
    except sr.RequestError:
        print("Error with recognition service")

    # Save the recorded audio for review
    with open("mic_test.wav", "wb") as f:
        f.write(audio.get_wav_data())
    print("Recording saved as 'mic_test.wav'. You can play it to verify.")

# Run the test function
if __name__ == "__main__":
    test_microphone()
