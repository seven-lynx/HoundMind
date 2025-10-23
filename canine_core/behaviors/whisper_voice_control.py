#!/usr/bin/env python3
from importlib import import_module

def start_behavior():
    mod = import_module('canine_core.legacy.behaviors.whisper_voice_control')
    return getattr(mod, 'start_behavior')()
