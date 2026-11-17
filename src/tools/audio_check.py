"""Speaker and microphone check for the bench dog.

`aplay` exits 0 whenever ALSA accepts the samples, which is not the same thing as
the speaker making a sound: a muted amplifier, a dead speaker coil, a stuck I2S
clock and a PulseAudio sink that points somewhere else all pass that test. This
tool closes the loop - it records with the microphone while it plays, and
measures whether the room actually got louder - so "the dog is silent" becomes a
number instead of an opinion.

Usage:
    python -m tools.audio_check --list
    python -m tools.audio_check --verify
    python -m tools.audio_check --amp on
    python -m tools.audio_check --tone 440 --device default
    python -m tools.audio_check --say "hello"
    python -m tools.audio_check --play bark.wav --device plughw:4,0

Nothing here constructs `Pidog`, so the servo bus is never touched and the dog
cannot move. Tones are short and at half scale.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import Sequence
from pathlib import Path

#: ALSA name that follows /etc/asound.conf to the Robot HAT speaker
DEFAULT_SPEAKER = "default"
#: the USB microphone on the bench dog; the V4 HAT has no onboard mic
DEFAULT_MIC = "plughw:3,0"
#: speaker-enable pin: GPIO20 on Robot HAT V4, GPIO12 on V5
AMP_PIN = 20
#: everything quieter than this is treated as digital silence
SILENCE_DB = -80.0
#: a stimulus this much louder than the room is a speaker that works
MIN_DELTA_DB = 10.0
RATE = 44100


def tone_samples(
    hz: float, seconds: float, rate: int = RATE, amplitude: float = 0.5
) -> list[int]:
    """A mono 16-bit sine at `hz`, `amplitude` of full scale."""
    peak = int(max(0.0, min(1.0, amplitude)) * 32767)
    count = max(1, int(seconds * rate))
    return [int(peak * math.sin(2.0 * math.pi * hz * i / rate)) for i in range(count)]


def write_wav(path: Path, samples: Sequence[int], rate: int = RATE) -> None:
    """Write mono 16-bit PCM, the format `arecord`/`aplay` share."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def read_wav(path: Path) -> tuple[list[int], int]:
    """Read mono 16-bit PCM; a stereo file is reduced to its first channel."""
    with wave.open(str(path), "rb") as handle:
        width = handle.getsampwidth()
        channels = handle.getnchannels()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit samples, got {width} bytes each")
    values = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    if channels > 1:
        values = values[::channels]
    return values, rate


def rms_db(samples: Sequence[int]) -> float:
    """Recording level in dBFS, floored at `SILENCE_DB`."""
    if not samples:
        return SILENCE_DB
    total = 0.0
    for value in samples:
        total += float(value) * float(value)
    rms = math.sqrt(total / len(samples)) / 32768.0
    if rms <= 0.0:
        return SILENCE_DB
    return max(SILENCE_DB, 20.0 * math.log10(rms))


def _bin_amplitude(samples: Sequence[int], k: int) -> float:
    """Amplitude of integer bin `k`, in sample units.

    One bin is enough: the question is "is the tone there", not "what is the
    spectrum". Pure Python keeps the tool free of numpy, which `lite` does not
    promise on the Pi.
    """
    count = len(samples)
    if count == 0 or k <= 0:
        return 0.0
    omega = 2.0 * math.pi * k / count
    coeff = 2.0 * math.cos(omega)
    prev = 0.0
    prev2 = 0.0
    for value in samples:
        current = float(value) + coeff * prev - prev2
        prev2 = prev
        prev = current
    power = prev * prev + prev2 * prev2 - coeff * prev * prev2
    return 2.0 * math.sqrt(max(power, 0.0)) / count


def tone_amplitude(samples: Sequence[int], rate: int, hz: float) -> float:
    """Amplitude at `hz` by Goertzel, in sample units."""
    count = len(samples)
    if count == 0:
        return 0.0
    return _bin_amplitude(samples, round(hz * count / rate))


def tone_ratio_db(samples: Sequence[int], rate: int, hz: float) -> float:
    """How far the `hz` bin sits above the recording's own level, in dB."""
    if not samples:
        return 0.0
    amplitude = tone_amplitude(samples, rate, hz)
    total = 0.0
    for value in samples:
        total += float(value) * float(value)
    rms = math.sqrt(total / len(samples))
    if amplitude <= 0.0:
        return 0.0
    if rms <= 0.0:
        return 99.0
    return 20.0 * math.log10(amplitude / rms)


def band_levels(
    samples: Sequence[int],
    rate: int,
    low: float = 50.0,
    high: float = 4000.0,
) -> list[tuple[float, float]]:
    """The loudest frequencies in a recording, as (hz, dBFS), loudest first.

    This is the one place that uses numpy: a full spectrum is not worth
    reimplementing by hand, and numpy is present everywhere the optional
    features are. The verification path above stays pure stdlib because it only
    ever measures one known frequency.

    Returns an empty list when numpy is missing or the recording is empty.
    """
    try:
        import numpy as np  # type: ignore
    except ImportError:
        return []
    if not samples:
        return []
    data = np.asarray(samples, dtype=float) / 32768.0
    window = np.hanning(len(data))
    spectrum = np.abs(np.fft.rfft(data * window)) * 2.0 / window.sum()
    freqs = np.fft.rfftfreq(len(data), 1.0 / rate)
    picked: list[tuple[float, float]] = []
    for index in np.nonzero((freqs >= low) & (freqs <= high))[0]:
        amplitude = float(spectrum[index])
        level = 20.0 * math.log10(amplitude) if amplitude > 0.0 else SILENCE_DB
        picked.append((float(freqs[index]), max(SILENCE_DB, level)))
    picked.sort(key=lambda pair: pair[1], reverse=True)
    return picked


def verdict(
    baseline_db: float, stimulus_db: float, min_delta_db: float = MIN_DELTA_DB
) -> tuple[str, float]:
    """Classify one play-and-record pair as EMITTED, SILENT or UNCLEAR."""
    delta = stimulus_db - baseline_db
    if delta >= min_delta_db:
        return "EMITTED", delta
    if delta <= 3.0:
        return "SILENT", delta
    return "UNCLEAR", delta



def _have(name: str) -> bool:
    return shutil.which(name) is not None


def set_amp(enabled: bool, pin: int = AMP_PIN) -> str | None:
    """Drive the speaker-enable pin, the way `enable_speaker()` does.

    Returns a description of what ran, or None when neither `pinctrl` nor
    `raspi-gpio` is available (the pin cannot be reached from Python here).
    """
    level = "dh" if enabled else "dl"
    for tool in ("pinctrl", "raspi-gpio"):
        if not _have(tool):
            continue
        result = subprocess.run(
            [tool, "set", str(pin), "op", level], capture_output=True, text=True
        )
        if result.returncode == 0:
            return f"{tool} set {pin} op {level}"
        print(f"[audio] {tool} failed: {(result.stderr or '').strip()}")
    return None


def play_file(path: Path, device: str = DEFAULT_SPEAKER) -> bool:
    """Play one file on `device` and wait for it to finish."""
    if not _have("aplay"):
        print("[audio] aplay not found (sudo apt install alsa-utils)")
        return False
    result = subprocess.run(
        ["aplay", "-q", "-D", device, str(path)], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[audio] aplay -D {device} failed: {(result.stderr or '').strip()}")
        return False
    return True


def record(path: Path, seconds: float, mic: str = DEFAULT_MIC) -> bool:
    """Record `seconds` of mono 16-bit audio."""
    if not _have("arecord"):
        print("[audio] arecord not found (sudo apt install alsa-utils)")
        return False
    result = subprocess.run(
        [
            "arecord",
            "-q",
            "-D",
            mic,
            "-f",
            "S16_LE",
            "-r",
            str(RATE),
            "-c",
            "1",
            "-d",
            str(max(1, int(seconds))),
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[audio] arecord -D {mic} failed: {(result.stderr or '').strip()}")
        return False
    return True


def speak(text: str, device: str = DEFAULT_SPEAKER) -> bool:
    """Render `text` with espeak and play the result."""
    engine = "espeak" if _have("espeak") else ("espeak-ng" if _have("espeak-ng") else None)
    if engine is None:
        print("[audio] neither espeak nor espeak-ng is installed")
        return False
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "say.wav"
        result = subprocess.run(
            [engine, "-w", str(wav), text], capture_output=True, text=True
        )
        if result.returncode != 0 or not wav.exists():
            print(f"[audio] {engine} failed: {(result.stderr or '').strip()}")
            return False
        return play_file(wav, device)


def list_devices() -> int:
    """Print what ALSA exposes for capture and playback."""
    found = False
    for cmd in (["arecord", "-l"], ["aplay", "-l"]):
        if not _have(cmd[0]):
            print(f"[audio] {cmd[0]} not found")
            continue
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        if output:
            print(output)
            found = True
    return 0 if found else 1


def verify(
    device: str,
    mic: str,
    hz: float,
    seconds: float,
    min_delta_db: float,
    amp: bool,
) -> int:
    """Play a tone while recording it, then say whether the speaker emitted it."""
    missing = [tool for tool in ("arecord", "aplay") if not _have(tool)]
    if missing:
        print(f"[audio] missing {', '.join(missing)} (sudo apt install alsa-utils)")
        return 1

    if amp:
        note = set_amp(True)
        print("[audio] amplifier: %s" % (note or "enable pin could not be driven"))
    time.sleep(0.2)

    with tempfile.TemporaryDirectory() as tmp:
        tone = Path(tmp) / "tone.wav"
        baseline = Path(tmp) / "baseline.wav"
        stimulus = Path(tmp) / "stimulus.wav"
        write_wav(tone, tone_samples(hz, seconds))

        print(f"[audio] baseline: {seconds:.1f}s of the room on {mic}")
        if not record(baseline, seconds, mic):
            return 1

        print(f"[audio] stimulus: {seconds:.1f}s while playing {hz:.0f} Hz on {device}")
        recorder = subprocess.Popen(
            [
                "arecord",
                "-q",
                "-D",
                mic,
                "-f",
                "S16_LE",
                "-r",
                str(RATE),
                "-c",
                "1",
                "-d",
                str(max(1, int(seconds))),
                str(stimulus),
            ],
            stderr=subprocess.PIPE,
        )
        time.sleep(0.4)
        player = subprocess.Popen(
            ["aplay", "-q", "-D", device, str(tone)], stderr=subprocess.PIPE
        )
        player.wait(timeout=seconds + 20)
        recorder.wait(timeout=seconds + 20)

        if player.returncode != 0:
            error = ""
            if player.stderr is not None:
                error = player.stderr.read().decode("utf-8", "replace").strip()
            print(f"[audio] aplay -D {device} failed: {error}")
            return 1
        if recorder.returncode != 0 or not stimulus.exists():
            print(f"[audio] recording failed on {mic}")
            return 1

        base_samples, rate = read_wav(baseline)
        stim_samples, _ = read_wav(stimulus)

    base_db = rms_db(base_samples)
    stim_db = rms_db(stim_samples)
    label, delta = verdict(base_db, stim_db, min_delta_db)
    band_db = tone_ratio_db(stim_samples, rate, hz)

    print(
        f"[audio] room {base_db:.1f} dB, speaker {stim_db:.1f} dB, "
        f"delta {delta:+.1f} dB (need {min_delta_db:+.0f})"
    )
    print(f"[audio] {hz:.0f} Hz bin sits {band_db:+.1f} dB above the recording")
    print(f"[audio] verdict: {label}")

    if label == "EMITTED":
        return 0
    if label == "UNCLEAR":
        print(
            "[audio] move the microphone nearer the speaker, or set the threshold "
            "for this room with --min-delta"
        )
    else:
        print(
            "[audio] ALSA accepted the samples and nothing came out: check the "
            "microphone gain first (amixer -c 3 sset 'Mic' 16), then the speaker "
            "connector, then the speaker on another source "
            "(docs/TROUBLESHOOTING.md section 6)"
        )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.audio_check",
        description="Play, record and measure the PiDog speaker path",
    )
    parser.add_argument("--list", action="store_true", help="list ALSA devices")
    parser.add_argument(
        "--amp", choices=("on", "off"), default=None, help="drive the speaker-enable pin"
    )
    parser.add_argument("--pin", type=int, default=AMP_PIN, help="enable pin (default 20)")
    parser.add_argument(
        "--device", default=DEFAULT_SPEAKER, help="playback ALSA name or hw address"
    )
    parser.add_argument("--mic", default=DEFAULT_MIC, help="capture ALSA name")
    parser.add_argument("--tone", type=float, default=None, help="play a tone at this Hz")
    parser.add_argument("--say", default=None, help="speak this text")
    parser.add_argument("--play", default=None, help="play this wav file")
    parser.add_argument("--analyse", default=None, help="report the spectrum of a wav")
    parser.add_argument("--seconds", type=float, default=2.0, help="clip length")
    parser.add_argument(
        "--min-delta",
        type=float,
        default=MIN_DELTA_DB,
        help="dB the speaker must add for EMITTED (default 10)",
    )
    parser.add_argument(
        "--verify", action="store_true", help="closed loop: play, record, measure"
    )
    parser.add_argument("--no-amp", action="store_true", help="leave the enable pin alone")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.list:
        return list_devices()

    plays = any((args.tone, args.say, args.play, args.verify))

    if args.amp is not None and not plays:
        note = set_amp(args.amp == "on", args.pin)
        print("[audio] %s" % (note or "enable pin could not be driven"))
        return 0 if note else 1

    if plays and not args.no_amp:
        set_amp(True, args.pin)

    if args.analyse:
        source = Path(args.analyse)
        if not source.exists():
            print(f"[audio] no such file: {source}")
            return 1
        samples, rate = read_wav(source)
        length = len(samples) / rate if rate else 0.0
        print(f"[audio] {source}: {length:.2f}s at {rate} Hz, {rms_db(samples):.1f} dB")
        bands = band_levels(samples, rate)
        if not bands:
            print("[audio] a full spectrum needs numpy: pip install numpy")
            return 1
        for hz, level in bands[:6]:
            print(f"[audio]   {hz:7.0f} Hz  {level:6.1f} dB")
        return 0

    if args.tone is not None:
        with tempfile.TemporaryDirectory() as tmp:
            tone = Path(tmp) / "tone.wav"
            write_wav(tone, tone_samples(args.tone, args.seconds))
            return 0 if play_file(tone, args.device) else 1

    if args.say:
        return 0 if speak(args.say, args.device) else 1

    if args.play:
        source = Path(args.play)
        if not source.exists():
            print(f"[audio] no such file: {source}")
            return 1
        return 0 if play_file(source, args.device) else 1

    if args.verify:
        code = verify(
            args.device, args.mic, args.tone or 440.0, args.seconds, args.min_delta, not args.no_amp
        )
        if args.json:
            print(json.dumps({"verdict": "EMITTED" if code == 0 else "SILENT"}))
        return code

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
