# Quick Start Programming (HoundMind Pi3)

This quick start shows how to run the HoundMind AI and customize its behavior safely.

## 1) Run the runtime
```bash
python -m houndmind_ai
```

## 2) Tune behavior
Edit config/settings.jsonc to adjust:
- sensors.poll_hz
- navigation.scan_interval_s
- behavior.idle_action / behavior.action_sets
- safety.emergency_stop_cm

### Autonomy tuning (Pi3)
HoundMind can patrol, play, and rest without user input. Tune these settings:
- behavior.autonomy_enabled
- behavior.autonomy_interval_s
- behavior.autonomy_modes
- behavior.autonomy_weights
- behavior.autonomy_rest_energy_max
- behavior.autonomy_play_energy_min

Example (lightweight Pi3 defaults):
```jsonc
"behavior": {
	"autonomy_enabled": true,
	"autonomy_interval_s": 8.0,
	"autonomy_modes": ["idle", "patrol", "play", "rest"],
	"autonomy_weights": {"idle": 0.4, "patrol": 0.3, "play": 0.2, "rest": 0.1},
	"autonomy_rest_energy_max": 0.35,
	"autonomy_play_energy_min": 0.75
}
```

## 3) Validate on-device
Use docs/PI3_VALIDATION.md to confirm sensors, scanning, navigation, and safety.

## 4) Optional modules
Enable optional modules only after hardware validation:
- modules.vision.enabled
- modules.voice.enabled
- modules.energy_emotion.enabled

## 5) Safe shutdown
Stop the runtime and let the process exit cleanly so motors can stop safely.
xz