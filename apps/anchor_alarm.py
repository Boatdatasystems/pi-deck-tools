#!/usr/bin/env python3
# pi-deck-tools: headless
"""SignalK notification alarm daemon — anchor_alarm.py

Headless, always-on daemon managed by systemd (anchor_alarm.service).
Watches SignalK notification paths for alarm states (anchor drag today;
see shared.config.SIGNALK_NOTIFICATION_WATCHES for the full list) and
sounds an audible alert when one fires.

One AlarmHandler is created per entry in SIGNALK_NOTIFICATION_WATCHES,
all sharing a single AudioManager instance so volume save/restore and
the single alert-loop slot are correctly serialized across watches (see
apps/alarm_handler.py and apps/audio_manager.py docstrings). Connectivity
to SignalK is handled by apps.signalk_monitor.SignalKMonitor, a single
WebSocket connection subscribed to every watched path at once.

This is intentionally a separate daemon from apps/mcd.py, not a check
bolted onto mcd's sweep loop: the I/O model is fundamentally different
(asyncio driving one persistent WebSocket connection here, vs. mcd's
synchronous poll-everything-every-N-seconds sweep), and "tell the crew
the anchor is dragging" is a distinct safety-critical concern from
"observe general system health" — a bug or restart in one must not be
able to silence the other.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import (
    ANCHOR_ALARM_STATUS_JSON_PATH,
    SIGNALK_ALARM_LOOP_GAP_SECONDS,
    SIGNALK_ALARM_VOLUME_PERCENT,
    SIGNALK_NOTIFICATION_WATCHES,
)
from shared.logger import get_logger
from apps.alarm_handler import AlarmHandler
from apps.audio_manager import AudioManager
from apps.signalk_monitor import SignalKMonitor

logger = get_logger("anchor_alarm")

WATCHDOG_INTERVAL_SECONDS = 30

# ---------------------------------------------------------------------------
# systemd integration (optional — absent on dev machines)
# ---------------------------------------------------------------------------

try:
    from systemd.daemon import notify as _sd_notify  # type: ignore
    _SYSTEMD_AVAILABLE = True
except ImportError:
    _SYSTEMD_AVAILABLE = False
    logger.debug("python-systemd not available; sd_notify calls are no-ops")


def sd_notify(message: str) -> None:
    """Send a notification to systemd if available; silently skip otherwise."""
    if _SYSTEMD_AVAILABLE:
        _sd_notify(message)


# ---------------------------------------------------------------------------
# JSON status snapshot (for a planned mcdash tab)
# ---------------------------------------------------------------------------

def write_status_json(handlers: dict[str, AlarmHandler], connection_status: str) -> None:
    """Write current alarm state for every watch to ANCHOR_ALARM_STATUS_JSON_PATH
    as JSON, atomically (temp file + os.replace), same pattern as
    apps/mcd.py: write_status_json(). Nice-to-have status reporting, not
    safety-critical, so any OSError is logged and swallowed rather than
    allowed to crash the daemon.
    """
    snapshot = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "connection_status": connection_status,
        "alarms": {
            name: {
                "state": handler.last_state,
                "currently_alarming": handler.currently_alarming,
                "digital_boost_failed": handler.digital_boost_failed,
            }
            for name, handler in handlers.items()
        },
    }

    path = Path(ANCHOR_ALARM_STATUS_JSON_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.warning("Failed to write status JSON to %s: %s", path, exc)


class _ConnectionState:
    """Mutable shared state for the connection status, captured by the
    on_notification/on_connection_status_change closures in main()."""

    def __init__(self) -> None:
        self.status = "reconnecting"


async def _watchdog_loop() -> None:
    """Notify systemd's watchdog every WATCHDOG_INTERVAL_SECONDS, independent
    of whether any notification has fired recently — this confirms the
    event loop itself is alive, not just that SignalK is sending data."""
    while True:
        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)
        sd_notify("WATCHDOG=1")


async def main() -> None:
    logger.info(
        "anchor_alarm starting — %d watch(es) configured, alarm_volume=%d%% loop_gap=%ds",
        len(SIGNALK_NOTIFICATION_WATCHES), SIGNALK_ALARM_VOLUME_PERCENT, SIGNALK_ALARM_LOOP_GAP_SECONDS,
    )

    audio_manager = AudioManager()
    handlers: dict[str, AlarmHandler] = {
        watch.name: AlarmHandler(watch, audio_manager) for watch in SIGNALK_NOTIFICATION_WATCHES
    }

    connection_state = _ConnectionState()

    def on_notification(watch, value: dict) -> None:
        handler = handlers[watch.name]
        handler.handle_notification(value)
        write_status_json(handlers, connection_state.status)

    def on_connection_status_change(status: str) -> None:
        connection_state.status = status
        write_status_json(handlers, status)

    monitor = SignalKMonitor(
        watches=SIGNALK_NOTIFICATION_WATCHES,
        on_notification=on_notification,
        on_connection_status_change=on_connection_status_change,
    )

    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_shutdown_signal() -> None:
        logger.info("shutdown signal received")
        monitor.stop()
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_shutdown_signal)
        except NotImplementedError:
            # Signal handlers via the event loop aren't available on this
            # platform (e.g. Windows during dev) — not fatal, just no
            # graceful-shutdown-on-signal there.
            pass

    sd_notify("READY=1")

    monitor_task = asyncio.create_task(monitor.run())
    watchdog_task = asyncio.create_task(_watchdog_loop())

    await shutdown_event.wait()

    monitor_task.cancel()
    watchdog_task.cancel()
    logger.info("anchor_alarm stopped")


if __name__ == "__main__":
    asyncio.run(main())
