#!/usr/bin/env python3
"""Per-watch alarm state machine — apps/alarm_handler.py

Each AlarmHandler owns the state machine for exactly ONE SignalK
notification path (one NotificationWatch), independently of any other
watches the caller has set up. Multiple AlarmHandlers are expected to
share a single AudioManager instance, so that volume save/restore and
the single alert-loop slot are correctly shared/serialized across
watches — e.g. if both an anchor-drag and a depth alarm exist later,
the system volume is only saved once even if both go into alarm state,
and only one alert sound plays at a time.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from apps.audio_manager import AudioManager
from shared.config import NotificationWatch
from shared.logger import get_logger

logger = get_logger("anchor_alarm")

_ALARM_STATES = {"alarm", "emergency"}
_CLEAR_STATES = {"normal", "nominal"}
_PRE_ALARM_STATES = {"alert", "warn"}


class AlarmHandler:
    """State machine for one NotificationWatch, sharing audio_manager
    with any sibling AlarmHandlers the caller creates."""

    def __init__(self, watch: NotificationWatch, audio_manager: AudioManager) -> None:
        self._watch = watch
        self._audio_manager = audio_manager
        self._last_state: str | None = None
        self._currently_alarming: bool = False

    @property
    def last_state(self) -> str | None:
        return self._last_state

    @property
    def currently_alarming(self) -> bool:
        return self._currently_alarming

    @property
    def digital_boost_failed(self) -> bool:
        return self._audio_manager.digital_boost_failed

    def handle_notification(self, value: dict) -> None:
        """Process one notification value for this watch's path.

        Identical-to-previous states are a safe no-op (debug-logged and
        returned immediately) — this is what makes REST resync
        duplicates and repeated deltas while actively alarming harmless
        rather than re-triggering side effects on every message.
        """
        state = value.get("state")
        message = value.get("message", "")

        if state == self._last_state:
            logger.debug("'%s': state unchanged (%s), no action", self._watch.name, state)
            return

        logger.info("'%s': state transition %s -> %s", self._watch.name, self._last_state, state)
        self._last_state = state

        if state in _ALARM_STATES:
            self._enter_alarm(message)
        elif state in _CLEAR_STATES:
            self._clear_alarm()
        elif state in _PRE_ALARM_STATES:
            # Intentional design decision, not a placeholder: alert/warn
            # states are informational only. No audio, no player
            # stopping, no volume change — those are reserved for actual
            # alarm/emergency states so the crew isn't woken or
            # interrupted for a pre-alarm warning.
            logger.info("'%s': pre-alarm warning: %s", self._watch.name, message)
        else:
            logger.warning("'%s': unrecognized notification state: %r", self._watch.name, state)

    def _enter_alarm(self, message: str) -> None:
        if not self._currently_alarming:
            self._audio_manager.stop_players()
            self._audio_manager.save_and_lower_volume()
            self._audio_manager.save_and_boost_digital_volume()
            self._audio_manager.start_alert_loop(self._watch.audio_path)
        self._currently_alarming = True
        logger.warning("'%s': ALARM — %s", self._watch.name, message)

    def _clear_alarm(self) -> None:
        if self._currently_alarming:
            self._audio_manager.stop_alert_loop()
            self._audio_manager.restore_volume()
            self._audio_manager.restore_digital_volume()
        self._currently_alarming = False
        logger.info("'%s': cleared", self._watch.name)
