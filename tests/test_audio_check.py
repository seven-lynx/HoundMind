"""Unit tests for `tools.audio_check` — no device, no audio hardware.

The measurement maths is the part that has to be right: the tool's whole
purpose is to turn "did the speaker make a sound" into a number, and a
mis-signed dB or an off-by-one bin would answer that question wrongly.
"""

from __future__ import annotations

from pathlib import Path

from tools.audio_check import (
    MIN_DELTA_DB,
    SILENCE_DB,
    band_levels,
    main,
    read_wav,
    rms_db,
    tone_amplitude,
    tone_ratio_db,
    tone_samples,
    verdict,
    write_wav,
)


def test_rms_db_of_silence_is_the_floor() -> None:
    assert rms_db([]) == SILENCE_DB
    assert rms_db([0] * 1000) == SILENCE_DB


def test_rms_db_of_a_full_scale_sine_is_minus_three() -> None:
    samples = tone_samples(440.0, 0.1, amplitude=1.0)
    assert -3.2 < rms_db(samples) < -2.9


def test_rms_db_tracks_amplitude_linearly() -> None:
    quiet = rms_db(tone_samples(440.0, 0.1, amplitude=0.1))
    loud = rms_db(tone_samples(440.0, 0.1, amplitude=1.0))
    assert 19.0 < loud - quiet < 21.0


def test_tone_amplitude_finds_the_bin_it_was_played_in() -> None:
    samples = tone_samples(440.0, 0.5, amplitude=0.5)
    played = tone_amplitude(samples, 44100, 440.0)
    elsewhere = tone_amplitude(samples, 44100, 1000.0)
    assert played > 15000.0
    assert elsewhere < played / 10.0


def test_tone_ratio_is_positive_for_the_played_tone() -> None:
    samples = tone_samples(440.0, 0.5, amplitude=0.5)
    assert tone_ratio_db(samples, 44100, 440.0) > 2.5


def test_tone_ratio_of_an_empty_recording_is_zero() -> None:
    assert tone_ratio_db([], 44100, 440.0) == 0.0


def test_verdict_needs_the_threshold() -> None:
    assert verdict(-60.0, -40.0)[0] == "EMITTED"
    assert verdict(-60.0, -59.0)[0] == "SILENT"
    assert verdict(-60.0, -52.0)[0] == "UNCLEAR"
    assert verdict(-60.0, -40.0, min_delta_db=25.0)[0] == "UNCLEAR"


def test_verdict_reports_the_delta_it_measured() -> None:
    label, delta = verdict(-50.0, -35.0)
    assert label == "EMITTED"
    assert abs(delta - 15.0) < 1e-9
    assert delta >= MIN_DELTA_DB


def test_wav_round_trip_keeps_every_sample(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    samples = tone_samples(440.0, 0.1)
    write_wav(path, samples)
    read_back, rate = read_wav(path)
    assert rate == 44100
    assert read_back == samples


def test_tone_samples_are_the_requested_length() -> None:
    assert len(tone_samples(440.0, 0.1)) == 4410
    assert len(tone_samples(440.0, 0.1, rate=8000)) == 800


def test_band_levels_names_the_played_tone() -> None:
    samples = tone_samples(1000.0, 0.5, amplitude=0.5)
    loudest = band_levels(samples, 44100)[0][0]
    assert 900.0 < loudest < 1100.0


def test_band_levels_of_an_empty_recording_is_empty() -> None:
    assert band_levels([], 44100) == []


def test_no_arguments_prints_help(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main([]) == 2
    assert "audio_check" in capsys.readouterr().out
