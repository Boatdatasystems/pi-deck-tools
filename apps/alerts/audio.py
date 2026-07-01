#!/usr/bin/env python3
"""Per-alert audio player for critical mcd alerts.

Each critical check has its own alarm wav so the watch crew can identify
the failure by ear without looking at a screen. Sound files live in
assets/sounds/, named alert_<check_name>.wav (e.g. alert_pypilot.wav).
If a check-specific file is missing, alert_default.wav is used instead.
Generate them with apps/alerts/generate_beeps.py.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.logger import get_logger

logger = get_logger("alerts.audio")

SOUNDS_DIR = Path("/home/pi/pi-deck-tools/assets/sounds")
DEFAULT_ALERT_WAV = SOUNDS_DIR / "alert_default.wav"


def play_wav_once(wav_path: Path, timeout: int = 30) -> bool:
    """Play a single wav file via paplay, blocking until done.

    Uses the same paplay --volume=65536 invocation already proven to
    work reliably on this hardware (PipeWire/HiFiBerry). Returns True
    if paplay ran successfully, False if it was missing, timed out,
    or failed for any other reason. Does not raise.
    """
    try:
        subprocess.run(
            ["paplay", "--volume=65536", str(wav_path)],
            capture_output=True, timeout=timeout,
        )
        return True
    except FileNotFoundError:
        logger.warning("paplay not found; skipping audio alert")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("paplay timed out playing %s", wav_path)
        return False
    except Exception:
        logger.exception("paplay failed playing %s", wav_path)
        return False


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

    play_wav_once(wav_path)


# Simultaneous mcd alerts (e.g. several services down after a reboot) used
# to each get their own thread and play at once, overlapping into
# unintelligible noise. A single serial queue + worker thread ensures each
# alert is heard clearly before the next one starts.
_alert_queue: queue.Queue = queue.Queue()
_worker_started = False


def _alert_worker() -> None:
    while True:
        item = _alert_queue.get()
        if item is None:
            break  # sentinel for clean shutdown if ever needed
        check_name, sound_file = item
        _play(check_name, sound_file)
        _alert_queue.task_done()


def _start_worker() -> None:
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    threading.Thread(target=_alert_worker, daemon=True).start()


_start_worker()


def play_critical_alert(check_name: str, sound_file: str | None = None) -> None:
    """Queue the alert sound for check_name to play on the serial worker thread.

    Returns immediately (non-blocking from the caller's perspective), but
    sounds play sequentially rather than overlapping when several alerts
    fire close together.

    sound_file, if given, is an explicit override (filename only, looked
    up in SOUNDS_DIR) that takes priority over the default
    alert_<check_name>.wav / alert_default.wav lookup.
    """
    _start_worker()
    _alert_queue.put((check_name, sound_file))


def list_available_sounds() -> list[str]:
    """Return the filenames (not full paths) of all .wav files in
    SOUNDS_DIR, sorted alphabetically. Used by mcdash to offer sound
    choices for per-check overrides.
    """
    if not SOUNDS_DIR.is_dir():
        return []
    return sorted(p.name for p in SOUNDS_DIR.glob("*.wav"))
