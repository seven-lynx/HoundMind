# Voice Setup Instructions (Optional, Pi3)

Voice is optional and disabled by default. Only enable it after hardware validation.

## 1) Enable module
Edit config/settings.jsonc:
- modules.voice.enabled = true

## 2) Install audio dependencies
Use your system package manager to install audio libraries and Python wheels suitable for your Pi3 OS image.

## 3) Test availability
Run the runtime and confirm the voice module reports "ready" in logs.

## 4) Troubleshooting
- If the mic is missing, the module will disable itself and log the reason.
- Ensure your microphone is detected by the OS before enabling voice.
