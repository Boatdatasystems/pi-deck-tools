#!/usr/bin/env python3
"""Generate beep-pattern wav files for mcd's critical alerts.

Standard-library only (wave, struct, math) — no numpy, no external deps.
Each critical check gets a distinct beep pattern so the watch crew can
identify the failure by ear. Run this once (or whenever patterns change)
to (re)populate assets/sounds/.

Usage:
    python3 apps/alerts/generate_beeps.py
"""

from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

SOUNDS_DIR = Path(__file__).parent.parent.parent / "assets" / "sounds"

SAMPLE_RATE = 44100
AMPLITUDE = 0.6  # fraction of full scale, keeps headroom against clipping

# Each pattern is a list of (frequency_hz, beep_duration_s, gap_after_s) tuples.
PATTERNS: dict[str, list[tuple[float, float, float]]] = {
    "alert_default": [(880, 0.5, 0.0)],
    "alert_pypilot": [(660, 0.15, 0.1)] * 3,
    "alert_signalk": [(880, 0.15, 0.1)] * 3,
    "alert_signalk_http": [(880, 0.15, 0.1)] * 3,
    "alert_signalk_position": [(550, 0.2, 0.15)] * 2,
    "alert_opencpn": [(660, 0.15, 0.1)] * 3,
    "alert_lightdm": [(440, 0.2, 0.15)] * 2,
    "alert_NetworkManager": [(440, 0.2, 0.15)] * 2,
    "alert_ttyOP_gps": [(550, 0.2, 0.15)] * 2,
    "alert_ttyOP_ais": [(550, 0.2, 0.15)] * 2,
    "alert_ttyOP_wind": [(440, 0.5, 0.0)],
    "alert_ttyOP_comp": [(440, 0.5, 0.0)],
    "alert_throttle": [(1000, 0.1, 0.07)] * 4,
}


def _tone_samples(freq_hz: float, duration_s: float) -> list[int]:
    """Generate signed 16-bit PCM samples for a sine tone."""
    n_samples = int(SAMPLE_RATE * duration_s)
    samples = []
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        value = AMPLITUDE * math.sin(2 * math.pi * freq_hz * t)
        samples.append(int(value * 32767))
    return samples


def _silence_samples(duration_s: float) -> list[int]:
    return [0] * int(SAMPLE_RATE * duration_s)


def write_pattern(path: Path, pattern: list[tuple[float, float, float]]) -> None:
    """Write a wav file containing the given beep/gap pattern."""
    samples: list[int] = []
    for freq_hz, beep_s, gap_s in pattern:
        samples.extend(_tone_samples(freq_hz, beep_s))
        if gap_s > 0:
            samples.extend(_silence_samples(gap_s))

    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def main() -> None:
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    for name, pattern in PATTERNS.items():
        path = SOUNDS_DIR / f"{name}.wav"
        write_pattern(path, pattern)
        print(path)


if __name__ == "__main__":
    main()
