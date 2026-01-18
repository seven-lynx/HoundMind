"""
WiFi-based localization module for PiDog.
Scans for nearby WiFi APs, records RSSI for each SSID, and provides fingerprint-based localization.
Disabled by default in config.
"""
import threading
import time
import subprocess
import re
from houndmind_ai.core.module import Module

import json
import os

class WifiLocalizationModule(Module):
    def __init__(self, name: str, enabled: bool = False, required: bool = False, scan_interval: float = 10.0, ignore_ssids=None, fingerprint_file: str = "wifi_fingerprints.json", max_fingerprint_file_size: int = 262144):
        super().__init__(name, enabled=enabled, required=required)
        self.scan_interval = scan_interval
        self.ignore_ssids = set(ignore_ssids or [])
        self.fingerprint_file = fingerprint_file
        self.max_fingerprint_file_size = max_fingerprint_file_size
        self._thread = None
        self._stop_event = threading.Event()
        self._last_scan = None
        self._fingerprints = self._load_fingerprints()

    def start(self, context):
        if not self.status.enabled:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._scan_loop, args=(context,), daemon=True)
        self._thread.start()

    def stop(self, context):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._save_fingerprints()

    def _scan_loop(self, context):
        while not self._stop_event.is_set():
            scan = self.scan_wifi()
            # Filter ignored SSIDs
            if scan and "networks" in scan:
                scan["networks"] = [n for n in scan["networks"] if n["ssid"] not in self.ignore_ssids]
            self._last_scan = scan
            context.set("wifi_scan", scan)
            # Optionally update fingerprints if location is known
            loc = context.get("current_location")
            if loc and scan and "networks" in scan:
                self._update_fingerprint(loc, scan["networks"])
            time.sleep(self.scan_interval)

    @staticmethod
    def scan_wifi():
        # Windows: use 'netsh wlan show networks mode=Bssid'
        try:
            output = subprocess.check_output(["netsh", "wlan", "show", "networks", "mode=Bssid"], encoding="utf-8")
        except Exception as exc:
            return {"error": str(exc)}
        networks = []
        ssid = None
        for line in output.splitlines():
            m = re.match(r"\s*SSID (\d+) : (.+)", line)
            if m:
                ssid = m.group(2)
                networks.append({"ssid": ssid, "bssids": []})
            m = re.match(r"\s*BSSID (\d+) : ([0-9A-Fa-f:]+)", line)
            if m and networks:
                networks[-1]["bssids"].append({"bssid": m.group(2)})
            m = re.match(r"\s*Signal\s*:\s*(\d+)%", line)
            if m and networks and networks[-1]["bssids"]:
                networks[-1]["bssids"][-1]["signal"] = int(m.group(1))
        return {"networks": networks, "timestamp": time.time()}

    def _load_fingerprints(self):
        if os.path.exists(self.fingerprint_file):
            try:
                with open(self.fingerprint_file, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_fingerprints(self):
        try:
            data = json.dumps(self._fingerprints)
            # Enforce file size limit
            if len(data.encode("utf-8")) > self.max_fingerprint_file_size:
                # Remove oldest entries until under limit
                keys = list(self._fingerprints.keys())
                while len(data.encode("utf-8")) > self.max_fingerprint_file_size and keys:
                    del self._fingerprints[keys[0]]
                    keys.pop(0)
                    data = json.dumps(self._fingerprints)
            with open(self.fingerprint_file, "w") as f:
                f.write(data)
        except Exception:
            pass

    def _update_fingerprint(self, location, networks):
        # Store the latest scan for a given location
        self._fingerprints[location] = networks
        self._save_fingerprints()
