#!/usr/bin/env python3
from importlib import import_module

def start_behavior():
    mod = import_module('canine_core.legacy.behaviors.find_open_space')
    return getattr(mod, 'start_behavior')()
