from __future__ import annotations

import logging
import random
import time
from enum import Enum

from houndmind_ai.core.module import Module
from houndmind_ai.behavior.library import BehaviorLibrary, BehaviorLibraryConfig
from houndmind_ai.behavior.registry import BehaviorRegistry

logger = logging.getLogger(__name__)


class BehaviorState(str, Enum):
    IDLE = "idle"
    ALERT = "alert"
    AVOIDING = "avoiding"
    PATROL = "patrol"
    EXPLORE = "explore"
    INTERACT = "interact"
    PLAY = "play"
    REST = "rest"


class BehaviorModule(Module):
    def __init__(self, name: str, enabled: bool = True, required: bool = False) -> None:
        super().__init__(name, enabled=enabled, required=required)
        self.state = BehaviorState.IDLE
        self.last_action: str | None = None
        self._last_action_ts = 0.0
        self._last_state_ts = 0.0
        self._candidate_state: BehaviorState | None = None
        self._candidate_ticks = 0
        self._last_micro_ts = 0.0
        self._last_autonomy_ts = 0.0
        self._autonomy_mode: str | None = None
        self.library: BehaviorLibrary | None = None
        self.registry: BehaviorRegistry | None = None
        # habituation tracking: counts and last timestamp per stimulus type
        self._stim_counts: dict[str, int] = {}
        self._stim_last_ts: dict[str, float] = {}

    def tick(self, context) -> None:
        now = time.time()
        # Perception is fused upstream; behavior maps it to actions.
        perception = context.get("perception") or {}
        obstacle = perception.get("obstacle", False)
        touch = perception.get("touch", "N")
        sound = perception.get("sound", False)

        # Habituation: suppress repeated stimuli if enabled and threshold reached.
        # Settings: habituation_enabled (bool), habituation_threshold (int),
        # habituation_recovery_s (float) - time without stimulus to reset count.
        hab_settings = (context.get("settings") or {}).get("behavior", {})
        hab_enabled = bool(hab_settings.get("habituation_enabled", False))
        suppressed = False
        if hab_enabled:
            now = time.time()
            # decay / recovery: clear counts if enough quiet time has passed
            recovery_s = float(hab_settings.get("habituation_recovery_s", 30.0))
            recovered = False
            for k, last in list(self._stim_last_ts.items()):
                try:
                    if (now - last) >= recovery_s:
                        self._stim_counts.pop(k, None)
                        self._stim_last_ts.pop(k, None)
                        recovered = True
                except Exception:
                    self._stim_counts.pop(k, None)
                    self._stim_last_ts.pop(k, None)
                    recovered = True

            # update counts for current stimuli and possibly suppress reactions
            threshold = int(hab_settings.get("habituation_threshold", 3))
            if touch != "N":
                cnt = self._stim_counts.get("touch", 0) + 1
                self._stim_counts["touch"] = cnt
                self._stim_last_ts["touch"] = now
                if cnt >= threshold:
                    # treat as no touch when habituated
                    touch = "N"
                    suppressed = True
                    context.set("behavior_habituation", {"stimulus": "touch", "count": cnt})
            if sound:
                cnt = self._stim_counts.get("sound", 0) + 1
                self._stim_counts["sound"] = cnt
                self._stim_last_ts["sound"] = now
                if cnt >= threshold:
                    sound = False
                    suppressed = True
                    context.set("behavior_habituation", {"stimulus": "sound", "count": cnt})

            # If we recovered from habituation (quiet period elapsed), clear
            # last action so the next matching stimulus will be emitted again.
            if recovered:
                try:
                    self.last_action = None
                except Exception:
                    pass

        # Behavior settings are centralized in settings.json for easy tuning.
        settings = (context.get("settings") or {}).get("behavior", {})
        # Energy / internal state: initialize, apply stimulus boosts, decay, and persist.
        energy_settings = (context.get("settings") or {}).get("energy", {})
        energy_enabled = bool(energy_settings.get("enabled", False))
        if energy_enabled:
            try:
                initial_energy = float(energy_settings.get("initial", 0.6))
            except Exception:
                initial_energy = 0.6
            try:
                decay_per_tick = float(energy_settings.get("decay_per_tick", 0.01))
            except Exception:
                decay_per_tick = 0.01
            try:
                boost_touch = float(energy_settings.get("boost_touch", 0.08))
            except Exception:
                boost_touch = 0.08
            try:
                boost_sound = float(energy_settings.get("boost_sound", 0.05))
            except Exception:
                boost_sound = 0.05
            try:
                energy_min = float(energy_settings.get("min", 0.0))
            except Exception:
                energy_min = 0.0
            try:
                energy_max = float(energy_settings.get("max", 1.0))
            except Exception:
                energy_max = 1.0

            energy = context.get("energy_level")
            if energy is None:
                energy = initial_energy

            # Only apply boosts for non-habituated stimuli (touch/sound may have been suppressed above)
            if touch != "N":
                energy = min(energy_max, energy + boost_touch)
            if sound:
                energy = min(energy_max, energy + boost_sound)

            # Apply decay and clamp
            try:
                energy = float(energy) - decay_per_tick
            except Exception:
                pass
            energy = max(energy_min, min(energy_max, energy))
            context.set("energy_level", energy)
        idle_action = settings.get("idle_action", "stand")
        touch_action = settings.get("touch_action", "wag tail")
        sound_action = settings.get("sound_action", "shake head")
        avoid_action = settings.get("avoid_action", "backward")
        patrol_action = settings.get("patrol_action", "forward")
        explore_action = settings.get("explore_action", "forward")
        interact_action = settings.get("interact_action", "wag tail")

        # Initialize the behavior library once with action sets from config.
        if self.library is None:
            action_sets = settings.get("action_sets", {})
            catalog = settings.get("catalog", {})
            self.library = BehaviorLibrary(
                BehaviorLibraryConfig(
                    idle_actions=catalog.get(
                        action_sets.get("idle", "idle"), [idle_action]
                    ),
                    alert_actions=catalog.get(
                        action_sets.get("alert", "alert"), [touch_action, sound_action]
                    ),
                    avoid_actions=catalog.get(
                        action_sets.get("avoid", "avoid"), [avoid_action]
                    ),
                    play_actions=catalog.get(
                        action_sets.get("play", "play"), ["stretch"]
                    ),
                    rest_actions=catalog.get(action_sets.get("rest", "rest"), ["lie"]),
                    patrol_actions=catalog.get(
                        action_sets.get("patrol", "patrol"), [patrol_action]
                    ),
                    explore_actions=catalog.get(
                        action_sets.get("explore", "explore"), [explore_action]
                    ),
                    interact_actions=catalog.get(
                        action_sets.get("interact", "interact"), [interact_action]
                    ),
                    random_idle_chance=settings.get("random_idle_chance", 0.05),
                )
            )
        if self.registry is None:
            self.registry = BehaviorRegistry()
            self.registry.register("idle_behavior", self.library.pick_idle_action)
            self.registry.register("rest_behavior", self.library.pick_rest_action)
            self.registry.register("play_behavior", self.library.pick_play_action)
            self.registry.register("patrol_behavior", self.library.pick_patrol_action)
            self.registry.register("explore_behavior", self.library.pick_explore_action)
            self.registry.register(
                "interact_behavior", self.library.pick_interact_action
            )

        battery_settings = (context.get("settings") or {}).get("battery", {})
        if battery_settings.get("enabled", False):
            voltage = context.get("battery_voltage")
            percent = context.get("battery_percent")
            try:
                voltage = float(voltage) if voltage is not None else None
            except Exception:
                voltage = None
            try:
                percent = float(percent) if percent is not None else None
            except Exception:
                percent = None
            low_voltage = battery_settings.get("low_voltage_v")
            low_percent = battery_settings.get("low_percent")
            try:
                low_voltage = float(low_voltage) if low_voltage is not None else None
            except Exception:
                low_voltage = None
            try:
                low_percent = float(low_percent) if low_percent is not None else None
            except Exception:
                low_percent = None

            low = False
            if (
                voltage is not None
                and low_voltage is not None
                and voltage <= low_voltage
            ):
                low = True
            if (
                percent is not None
                and low_percent is not None
                and percent <= low_percent
            ):
                low = True

            if low:
                context.set(
                    "battery_low",
                    {
                        "timestamp": time.time(),
                        "voltage": voltage,
                        "percent": percent,
                        "low_voltage_v": low_voltage,
                        "low_percent": low_percent,
                    },
                )
                if context.get("behavior_override") is None:
                    override_name = battery_settings.get(
                        "behavior_override", "rest_behavior"
                    )
                    context.set("behavior_override", override_name)

        desired_state: BehaviorState
        desired_action: str

        override = context.get("behavior_override")
        if override:
            desired_state = BehaviorState.IDLE
            desired_action = self._resolve_override(override)
        elif obstacle:
            desired_state = BehaviorState.AVOIDING
            desired_action = (
                self.library.pick_avoid_action() if self.library else avoid_action
            )
        elif touch != "N":
            desired_state = BehaviorState.ALERT
            desired_action = (
                self.library.pick_alert_action() if self.library else touch_action
            )
        elif sound:
            desired_state = BehaviorState.ALERT
            desired_action = (
                self.library.pick_alert_action() if self.library else sound_action
            )
        else:
            if settings.get("autonomy_enabled", True):
                mode = self._select_autonomy_mode(settings, context)
                if mode == "patrol":
                    desired_state = BehaviorState.PATROL
                    desired_action = (
                        self.library.pick_patrol_action()
                        if self.library
                        else patrol_action
                    )
                elif mode == "explore":
                    desired_state = BehaviorState.EXPLORE
                    desired_action = (
                        self.library.pick_explore_action()
                        if self.library
                        else explore_action
                    )
                elif mode == "interact":
                    desired_state = BehaviorState.INTERACT
                    desired_action = (
                        self.library.pick_interact_action()
                        if self.library
                        else interact_action
                    )
                elif mode == "play":
                    desired_state = BehaviorState.PLAY
                    desired_action = (
                        self.library.pick_play_action() if self.library else "stretch"
                    )
                elif mode == "rest":
                    desired_state = BehaviorState.REST
                    desired_action = (
                        self.library.pick_rest_action() if self.library else "lie"
                    )
                else:
                    desired_state = BehaviorState.IDLE
                    desired_action = (
                        self._select_idle_behavior(settings)
                        if self.library
                        else idle_action
                    )
            else:
                desired_state = BehaviorState.IDLE
                desired_action = (
                    self._select_idle_behavior(settings)
                    if self.library
                    else idle_action
                )

        transition_guard_enabled = bool(
            settings.get("transition_guard_enabled", False)
        )
        if transition_guard_enabled:
            immediate_states = settings.get(
                "transition_immediate_states", ["avoiding", "alert"]
            )
            min_dwell_s = float(settings.get("transition_min_dwell_s", 0.6))
            confirm_ticks = int(settings.get("transition_confirm_ticks", 2))
            if desired_state != self.state:
                if override or desired_state.value in immediate_states:
                    self._candidate_state = None
                    self._candidate_ticks = 0
                    self.state = desired_state
                    self._last_state_ts = now
                else:
                    if self._candidate_state != desired_state:
                        self._candidate_state = desired_state
                        self._candidate_ticks = 1
                    else:
                        self._candidate_ticks += 1
                    if (now - self._last_state_ts) < min_dwell_s or (
                        self._candidate_ticks < confirm_ticks
                    ):
                        desired_state = self.state
                        desired_action = self._pick_action_for_state(
                            self.state,
                            settings,
                            idle_action,
                            touch_action,
                            sound_action,
                            avoid_action,
                            patrol_action,
                            explore_action,
                            interact_action,
                            touch,
                            sound,
                        )
                    else:
                        self._candidate_state = None
                        self._candidate_ticks = 0
                        self.state = desired_state
                        self._last_state_ts = now
        else:
            if desired_state != self.state:
                self.state = desired_state
                self._last_state_ts = now

        # Optional micro-idle behaviors for lifelike idle without affecting core logic.
        micro_enabled = bool(settings.get("micro_idle_enabled", False))
        micro_actions = settings.get("micro_idle_actions", [])
        micro_interval_s = float(settings.get("micro_idle_interval_s", 12.0))
        micro_chance = float(settings.get("micro_idle_chance", 0.2))
        if (
            micro_enabled
            and self.state == BehaviorState.IDLE
            and not override
            and isinstance(micro_actions, list)
            and micro_actions
            and (now - self._last_micro_ts) >= micro_interval_s
            and random.random() <= micro_chance
        ):
            try:
                desired_action = str(random.choice(micro_actions))
                self._last_micro_ts = now
            except Exception:
                pass

        # If a stimulus was habituated this tick, avoid emitting an idle action
        # to prevent swapping to a default idle action in place of the suppressed reaction.
        if suppressed and not override and desired_state == BehaviorState.IDLE:
            return

        action = desired_action

        if action != self.last_action:
            cooldown = float(settings.get("action_cooldown_s", 0.0))
            quiet = (context.get("settings") or {}).get("quiet_mode", {})
            if context.get("quiet_mode_active"):
                try:
                    quiet_cooldown = float(quiet.get("behavior_action_cooldown_s", 0.0))
                except Exception:
                    quiet_cooldown = 0.0
                cooldown = max(cooldown, quiet_cooldown)
            if cooldown > 0 and (now - self._last_action_ts) < cooldown:
                return
            context.set("behavior_action", action)
            self.last_action = action
            self._last_action_ts = now
            logger.info("Behavior -> %s (%s)", action, self.state)

    def _resolve_override(self, override: object) -> str:
        if self.registry is None:
            return str(override)
        name = str(override)
        if self.registry.has(name):
            result = self.registry.run(name)
            if result:
                return result
        return name

    def _select_idle_behavior(self, settings) -> str:
        choices = settings.get("idle_choices", ["idle_behavior"])
        selection_mode = settings.get("behavior_selection_mode", "weighted")
        weights = settings.get("behavior_weights", {})
        if self.registry is None:
            return self.library.pick_idle_action() if self.library else "stand"
        if selection_mode == "sequential":
            choice = self.registry.pick_sequential(list(choices))
        else:
            choice = self.registry.pick_weighted(list(choices), weights)
        if choice:
            result = self.registry.run(choice)
            if result:
                return result
        return self.library.pick_idle_action() if self.library else "stand"

    def _pick_action_for_state(
        self,
        state: BehaviorState,
        settings: dict,
        idle_action: str,
        touch_action: str,
        sound_action: str,
        avoid_action: str,
        patrol_action: str,
        explore_action: str,
        interact_action: str,
        touch: str,
        sound: bool,
    ) -> str:
        if state == BehaviorState.AVOIDING:
            return self.library.pick_avoid_action() if self.library else avoid_action
        if state == BehaviorState.ALERT:
            if touch != "N":
                return self.library.pick_alert_action() if self.library else touch_action
            if sound:
                return self.library.pick_alert_action() if self.library else sound_action
            return self.library.pick_alert_action() if self.library else sound_action
        if state == BehaviorState.PATROL:
            return self.library.pick_patrol_action() if self.library else patrol_action
        if state == BehaviorState.EXPLORE:
            return self.library.pick_explore_action() if self.library else explore_action
        if state == BehaviorState.INTERACT:
            return self.library.pick_interact_action() if self.library else interact_action
        if state == BehaviorState.PLAY:
            return self.library.pick_play_action() if self.library else "stretch"
        if state == BehaviorState.REST:
            return self.library.pick_rest_action() if self.library else "lie"
        return (
            self._select_idle_behavior(settings)
            if self.library
            else idle_action
        )

    def _select_autonomy_mode(self, settings, context) -> str:
        now = time.time()
        interval = float(settings.get("autonomy_interval_s", 8.0))
        energy = context.get("energy_level")
        try:
            energy = float(energy) if energy is not None else None
        except Exception:
            energy = None

        rest_max = float(settings.get("autonomy_rest_energy_max", 0.35))
        play_min = float(settings.get("autonomy_play_energy_min", 0.75))
        if energy is not None and energy <= rest_max:
            self._autonomy_mode = "rest"
            return "rest"
        if energy is not None and energy >= play_min:
            self._autonomy_mode = "play"
            return "play"

        if self._autonomy_mode and (now - self._last_autonomy_ts) < interval:
            return self._autonomy_mode

        modes = settings.get("autonomy_modes", ["idle", "patrol", "play", "rest"])
        if not isinstance(modes, list) or not modes:
            modes = ["idle"]
        weights = settings.get("autonomy_weights", {})
        choice = (
            self.registry.pick_weighted(list(modes), weights) if self.registry else None
        )
        self._autonomy_mode = choice or "idle"
        self._last_autonomy_ts = now
        return self._autonomy_mode
