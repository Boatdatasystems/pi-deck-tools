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

# ALSA device for aplay. Update here if the card number shifts.
ALSA_DEVICE = "plughw:CARD=sndrpihifiberry,DEV=0"


def _alert_wav_for(check_name: str) -> Path | None:
    """Return the wav path to play for check_name, falling back to default."""
    specific = SOUNDS_DIR / f"alert_{check_name}.wav"
    if specific.exists():
        return specific
    if DEFAULT_ALERT_WAV.exists():
        return DEFAULT_ALERT_WAV
    return None


def _play(check_name: str) -> None:
    wav_path = _alert_wav_for(check_name)
    if wav_path is None:
        logger.warning(
            "No alert wav found for '%s' (checked %s and %s); skipping audio alert",
            check_name, SOUNDS_DIR / f"alert_{check_name}.wav", DEFAULT_ALERT_WAV,
        )
        return

    try:
        subprocess.run(["aplay", "-D", ALSA_DEVICE, str(wav_path)], capture_output=True, timeout=30)
    except FileNotFoundError:
        logger.warning("aplay not found; skipping audio alert")
    except subprocess.TimeoutExpired:
        logger.warning("aplay timed out playing alert for '%s'", check_name)


def play_critical_alert(check_name: str) -> None:
    """Play the alert sound for check_name in a non-blocking background thread."""
    threading.Thread(target=_play, args=(check_name,), daemon=True).start()
