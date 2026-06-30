#!/usr/bin/env python3
"""System audio control for SignalK notification alarms — apps/audio_manager.py

AudioManager owns the side effects an alarm needs around the actual
looped sound: stopping other audio players so the alarm is heard clearly,
saving/lowering/restoring the system volume, and running the alert loop
itself (via apps.alerts.audio.play_wav_once, not duplicated here).

Designed to be shared across multiple apps/alarm_handler.py instances
(one per watched notification path) so volume save/restore and the
single alert-loop slot are correctly serialized — only one alarm sound
plays at a time, and the original volume is saved exactly once no matter
how many watches go into alarm state.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from apps.alerts.audio import play_wav_once
from shared.config import (
    ALSA_CARD_NAME,
    SIGNALK_ALARM_DIGITAL_VOLUME_PERCENT,
    SIGNALK_ALARM_LOOP_GAP_SECONDS,
    SIGNALK_ALARM_VOLUME_PERCENT,
)
from shared.logger import get_logger

logger = get_logger("anchor_alarm")

_VOLUME_PERCENT_RE = re.compile(r"(\d+)%")


class AudioManager:
    """Shared audio side-effects for one or more alarm watches.

    Players are never auto-resumed by this class — confirmed behaviour
    is manual restart by the crew once the alarm is dealt with.
    """

    def __init__(self) -> None:
        self._saved_volume_percent: int | None = None
        self._saved_digital_percent: int | None = None
        self._digital_boost_failed: bool = False
        self._loop_thread: threading.Thread | None = None
        self._loop_stop_event = threading.Event()
        self._active_audio_path: Path | None = None

    @property
    def digital_boost_failed(self) -> bool:
        """True if the most recent save_and_boost_digital_volume() call
        failed to read or set the ALSA Digital mixer. Surfaced so
        callers (status JSON) can flag that the alarm may not be at
        full volume — this is treated as more serious than other audio
        side-effect failures, since it's specifically about whether the
        alarm itself can be heard."""
        return self._digital_boost_failed

    # ------------------------------------------------------------------
    # Other audio players
    # ------------------------------------------------------------------

    def stop_players(self) -> None:
        """Pause Clementine and kill gqrx so the alarm is heard clearly."""
        try:
            result = subprocess.run(
                ["playerctl", "--player=clementine", "pause"],
                capture_output=True, timeout=2,
            )
            if result.returncode == 0:
                logger.info("Paused Clementine")
            else:
                logger.debug("playerctl pause returned %d (Clementine likely not running)", result.returncode)
        except Exception as exc:
            logger.debug("Could not pause Clementine: %s", exc)

        try:
            result = subprocess.run(["pkill", "-x", "gqrx"], capture_output=True, timeout=2)
            if result.returncode == 0:
                logger.info("Stopped gqrx")
            else:
                logger.debug("pkill gqrx returned %d (gqrx likely not running)", result.returncode)
        except Exception as exc:
            logger.debug("Could not stop gqrx: %s", exc)

    # ------------------------------------------------------------------
    # Volume save / lower / restore
    # ------------------------------------------------------------------

    def save_and_lower_volume(self) -> None:
        """Save the current sink volume (only if nothing is already
        saved — see class docstring) and lower it to
        SIGNALK_ALARM_VOLUME_PERCENT.
        """
        if self._saved_volume_percent is not None:
            logger.debug(
                "Volume already saved (%d%%); not overwriting with a possibly-already-lowered value",
                self._saved_volume_percent,
            )
        else:
            try:
                result = subprocess.run(
                    ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                    capture_output=True, timeout=2, text=True,
                )
                match = _VOLUME_PERCENT_RE.search(result.stdout)
                if match:
                    self._saved_volume_percent = int(match.group(1))
                    logger.info("Saved current volume: %d%%", self._saved_volume_percent)
                else:
                    logger.warning("Could not parse volume from pactl output: %r", result.stdout)
            except Exception as exc:
                logger.warning("Failed to read current volume via pactl: %s", exc)

        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{SIGNALK_ALARM_VOLUME_PERCENT}%"],
                capture_output=True, timeout=2,
            )
            logger.info("Set volume to alarm level (%d%%)", SIGNALK_ALARM_VOLUME_PERCENT)
        except Exception as exc:
            logger.warning("Failed to set alarm volume via pactl: %s", exc)

    def restore_volume(self) -> None:
        """Restore the previously-saved volume, if any. Resets the saved
        value to None regardless of whether the pactl call itself
        succeeded, so the next alarm starts a fresh save."""
        if self._saved_volume_percent is None:
            logger.debug("No saved volume to restore")
            return

        saved = self._saved_volume_percent
        try:
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{saved}%"],
                capture_output=True, timeout=2,
            )
            logger.info("Restored volume to %d%%", saved)
        except Exception as exc:
            logger.warning("Failed to restore volume via pactl: %s", exc)
        finally:
            self._saved_volume_percent = None

    # ------------------------------------------------------------------
    # ALSA Digital mixer save / boost / restore
    # ------------------------------------------------------------------

    def save_and_boost_digital_volume(self) -> None:
        """Save the current ALSA Digital mixer level (only if nothing is
        already saved — see class docstring) and boost it to
        SIGNALK_ALARM_DIGITAL_VOLUME_PERCENT.

        Failure to read or set the mixer is treated as more serious than
        other audio side-effect failures here, since it directly affects
        whether the alarm can be heard — logged at ERROR level and
        surfaced via digital_boost_failed.
        """
        if self._saved_digital_percent is not None:
            logger.debug(
                "Digital volume already saved (%d%%); not overwriting with a possibly-already-boosted value",
                self._saved_digital_percent,
            )
        else:
            try:
                result = subprocess.run(
                    ["amixer", "-c", ALSA_CARD_NAME, "sget", "Digital"],
                    capture_output=True, timeout=2, text=True,
                )
                match = _VOLUME_PERCENT_RE.search(result.stdout)
                if match:
                    self._saved_digital_percent = int(match.group(1))
                    logger.info("Saved current ALSA Digital volume: %d%%", self._saved_digital_percent)
                else:
                    self._digital_boost_failed = True
                    logger.error("Could not parse ALSA Digital volume from amixer output: %r", result.stdout)
            except Exception as exc:
                self._digital_boost_failed = True
                logger.error("Failed to read ALSA Digital volume via amixer: %s", exc)

        try:
            subprocess.run(
                ["amixer", "-c", ALSA_CARD_NAME, "sset", "Digital", f"{SIGNALK_ALARM_DIGITAL_VOLUME_PERCENT}%"],
                capture_output=True, timeout=2, check=True,
            )
            self._digital_boost_failed = False
            logger.info("Set ALSA Digital volume to alarm level (%d%%)", SIGNALK_ALARM_DIGITAL_VOLUME_PERCENT)
        except subprocess.CalledProcessError as exc:
            self._digital_boost_failed = True
            stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
            logger.error("amixer sset Digital failed (exit %d): %s", exc.returncode, stderr.strip())
        except Exception as exc:
            self._digital_boost_failed = True
            logger.error("Failed to set ALSA Digital alarm volume via amixer: %s", exc)

    def restore_digital_volume(self) -> None:
        """Restore the previously-saved ALSA Digital volume, if any.
        Resets the saved value to None regardless of whether the amixer
        call itself succeeded, so the next alarm starts a fresh save.
        Also resets digital_boost_failed to False so a stale True from a
        previous alarm doesn't linger after this one has cleared."""
        if self._saved_digital_percent is None:
            logger.debug("No saved ALSA Digital volume to restore")
            self._digital_boost_failed = False
            return

        saved = self._saved_digital_percent
        try:
            subprocess.run(
                ["amixer", "-c", ALSA_CARD_NAME, "sset", "Digital", f"{saved}%"],
                capture_output=True, timeout=2,
            )
            logger.info("Restored ALSA Digital volume to %d%%", saved)
        except Exception as exc:
            logger.error("Failed to restore ALSA Digital volume via amixer: %s", exc)
        finally:
            self._saved_digital_percent = None
            self._digital_boost_failed = False

    def _boost_digital_volume_only(self) -> None:
        """Set (but do not save) the ALSA Digital mixer to
        SIGNALK_ALARM_DIGITAL_VOLUME_PERCENT. Called before every loop
        repeat during an active alarm, since the mixer has been observed
        to revert toward its pre-alarm level between repeats when no
        other audio stream is holding the device open (which is always
        the case during a real alarm, since stop_players() runs first).
        Unlike save_and_boost_digital_volume(), this never touches
        self._saved_digital_percent and is safe to call repeatedly —
        it only sets digital_boost_failed on actual failure, mirroring
        the ERROR-level logging of the existing boost method, since a
        failure here means the same "alarm may not be at full volume"
        concern as the original boost failing.
        """
        try:
            subprocess.run(
                ["amixer", "-c", ALSA_CARD_NAME, "sset", "Digital",
                 f"{SIGNALK_ALARM_DIGITAL_VOLUME_PERCENT}%"],
                capture_output=True, timeout=2, check=True,
            )
            self._digital_boost_failed = False
        except subprocess.CalledProcessError as exc:
            self._digital_boost_failed = True
            stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
            logger.error("amixer sset Digital failed (exit %d): %s", exc.returncode, stderr.strip())
        except Exception as exc:
            self._digital_boost_failed = True
            logger.error("Failed to re-boost Digital mixer before repeat: %s", exc)

    # ------------------------------------------------------------------
    # Alert loop
    # ------------------------------------------------------------------

    def start_alert_loop(self, audio_path: Path) -> None:
        """Start looping audio_path in a background daemon thread. If a
        loop is already running, the new alarm is silenced (logged) until
        the active one clears — only one alert sound plays at a time."""
        if self._loop_thread is not None and self._loop_thread.is_alive():
            logger.warning(
                "Alert loop already running for '%s'; new alarm for '%s' will stay silent until it clears",
                self._active_audio_path, audio_path,
            )
            return

        self._active_audio_path = audio_path
        self._loop_stop_event.clear()
        self._loop_thread = threading.Thread(
            target=self._loop_worker, args=(audio_path,), daemon=True,
        )
        self._loop_thread.start()
        logger.info("Started alert loop for '%s'", audio_path)

    def _loop_worker(self, audio_path: Path) -> None:
        while not self._loop_stop_event.is_set():
            playback_done = threading.Event()
            reboost_thread = threading.Thread(
                target=self._reboost_during_playback,
                args=(playback_done,),
                daemon=True,
            )
            reboost_thread.start()
            try:
                play_wav_once(audio_path)
            finally:
                playback_done.set()
                reboost_thread.join(timeout=1)
            self._loop_stop_event.wait(SIGNALK_ALARM_LOOP_GAP_SECONDS)

    def _reboost_during_playback(self, playback_done: threading.Event) -> None:
        """Repeatedly re-assert the Digital mixer boost every ~200ms
        for as long as the current repeat's playback is in progress,
        signaled by playback_done. Brute-force mitigation for an
        ALSA mixer revert whose exact trigger/timing is not fully
        understood — a single boost before playback was not reliably
        surviving the full duration of every repeat on real hardware.
        """
        self._boost_digital_volume_only()
        while not playback_done.wait(timeout=0.2):
            self._boost_digital_volume_only()

    def stop_alert_loop(self) -> None:
        """Signal the loop thread to stop and wait briefly for it to exit."""
        if self._loop_thread is None:
            return

        self._loop_stop_event.set()
        self._loop_thread.join(timeout=3)
        logger.info("Stopped alert loop for '%s'", self._active_audio_path)
        self._loop_thread = None
        self._active_audio_path = None
