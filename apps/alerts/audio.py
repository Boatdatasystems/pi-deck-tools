#!/usr/bin/env python3
"""Per-alert audio player for critical mcd alerts.

Each critical check has its own alarm wav so the watch crew can identify
the failure by ear without looking at a screen. Sound files live in
assets/sounds/, named alert_<check_name>.wav (e.g. alert_pypilot.wav).
If a check-specific file is missing, alert_default.wav is used instead.
Generate them with apps/alerts/generate_beeps.py.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.logger import get_logger

logger = get_logger("alerts.audio")

SOUNDS_DIR = Path("/home/pi/pi-deck-tools/assets/sounds")
DEFAULT_ALERT_WAV = SOUNDS_DIR / "alert_default.wav"


def _alert_wav_for(check_name: str, sound_file: str | None = None) -> Path | None:
    """Return the wav path to play for check_name, falling back to default.

    If sound_file is given (an explicit override from mcdash), it takes
    priority over the alert_<check_name>.wav lookup.
    """
    if sound_file:
        explicit = SOUNDS_DIR / sound_file
        if explicit.exists():
            return explicit
        logger.warning("Override sound_file '%s' for '%s' not found; falling back", sound_file, check_name)

    specific = SOUNDS_DIR / f"alert_{check_name}.wav"
    if specific.exists():
        return specific
    if DEFAULT_ALERT_WAV.exists():
        return DEFAULT_ALERT_WAV
    return None


def _play(check_name: str, sound_file: str | None = None) -> None:
    wav_path = _alert_wav_for(check_name, sound_file)
    if wav_path is None:
        logger.warning(
            "No alert wav found for '%s' (checked %s and %s); skipping audio alert",
            check_name, SOUNDS_DIR / f"alert_{check_name}.wav", DEFAULT_ALERT_WAV,
        )
        return

    try:
        subprocess.run(["paplay", "--volume=65536", str(wav_path)], capture_output=True, timeout=30)
    except FileNotFoundError:
        logger.warning("paplay not found; skipping audio alert")
    except subprocess.TimeoutExpired:
        logger.warning("paplay timed out playing alert for '%s'", check_name)


def play_critical_alert(check_name: str, sound_file: str | None = None) -> None:
    """Play the alert sound for check_name in a non-blocking background thread.

    sound_file, if given, is an explicit override (filename only, looked
    up in SOUNDS_DIR) that takes priority over the default
    alert_<check_name>.wav / alert_default.wav lookup.
    """
    threading.Thread(target=_play, args=(check_name, sound_file), daemon=True).start()


def list_available_sounds() -> list[str]:
    """Return the filenames (not full paths) of all .wav files in
    SOUNDS_DIR, sorted alphabetically. Used by mcdash to offer sound
    choices for per-check overrides.
    """
    if not SOUNDS_DIR.is_dir():
        return []
    return sorted(p.name for p in SOUNDS_DIR.glob("*.wav"))
