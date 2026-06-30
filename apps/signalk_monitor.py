#!/usr/bin/env python3
"""SignalK notification stream monitor — apps/signalk_monitor.py

Maintains ONE WebSocket connection to SignalK's delta stream, subscribed
to a set of notification paths (see shared.config.NotificationWatch /
SIGNALK_NOTIFICATION_WATCHES), and dispatches each incoming notification
value to a caller-supplied callback. Built as the shared connection layer
for apps/anchor_alarm.py, designed so additional notification paths
(depth, AIS proximity, etc.) can be watched later by adding entries to
SIGNALK_NOTIFICATION_WATCHES — no changes to this module are required.

Why the REST resync on every (re)connect: SignalK's WebSocket stream only
emits a delta when a value *changes*. A notification that is already in
the "alarm" state when this daemon starts (or reconnects after a network
blip) won't be re-sent over the WebSocket, since nothing changed from
SignalK's point of view — the daemon would silently miss an ongoing
emergency. Querying the REST API for the current value immediately after
subscribing closes that gap: it's a one-time poll per (re)connect, not a
replacement for the WebSocket subscription.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Callable, Optional

import websockets

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import SIGNALK_URL, NotificationWatch
from shared.logger import get_logger
from shared.signalk import get_sk_value

logger = get_logger("anchor_alarm")

RECONNECT_BACKOFF_SECONDS = [2, 5, 10, 30, 60]


def _default_ws_url() -> str:
    url = SIGNALK_URL
    if url.startswith("https://"):
        url = "wss://" + url[len("https://"):]
    elif url.startswith("http://"):
        url = "ws://" + url[len("http://"):]
    return url.rstrip("/") + "/signalk/v1/stream?subscribe=none"


SIGNALK_WS_URL = _default_ws_url()


def _path_to_rest_value_path(path: str) -> str:
    """Convert a dot-separated delta path to the slash-separated REST
    path (relative to vessels/self/) expected by shared.signalk.get_sk_value().

    e.g. "notifications.navigation.anchor" -> "notifications/navigation/anchor/value"
    """
    return path.replace(".", "/") + "/value"


class SignalKMonitor:
    """Watches one or more SignalK notification paths over a single
    WebSocket connection, calling on_notification for every value seen
    (from the initial REST resync and from subsequent deltas alike).
    """

    def __init__(
        self,
        watches: list[NotificationWatch],
        on_notification: Callable[[NotificationWatch, dict], None],
        on_connection_status_change: Optional[Callable[[str], None]] = None,
        ws_url: str = SIGNALK_WS_URL,
    ) -> None:
        self._watches = watches
        self._watches_by_path = {w.path: w for w in watches}
        self._on_notification = on_notification
        self._on_connection_status_change = on_connection_status_change
        self._ws_url = ws_url
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Request graceful shutdown. Checked at the top of the reconnect
        loop and inside the message-consuming loop."""
        self._stop_event.set()

    def _notify_connection_status(self, status: str) -> None:
        if self._on_connection_status_change is None:
            return
        try:
            self._on_connection_status_change(status)
        except Exception:
            logger.exception("on_connection_status_change callback raised for status '%s'", status)

    async def _resync_current_state(self) -> None:
        """Immediately after subscribing, poll the REST API for each
        watch's current value so an already-alarming notification isn't
        missed (see module docstring)."""
        for watch in self._watches:
            rest_path = _path_to_rest_value_path(watch.path)
            value = await asyncio.to_thread(get_sk_value, rest_path)
            if isinstance(value, dict):
                self._dispatch(watch, value)
            else:
                logger.debug("Resync: no current value at '%s' (path not present yet)", watch.path)

    def _dispatch(self, watch: NotificationWatch, value: dict) -> None:
        try:
            self._on_notification(watch, value)
        except Exception:
            logger.exception("on_notification callback raised for watch '%s'", watch.name)

    def _handle_message(self, raw: str) -> None:
        try:
            delta = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Received non-JSON WebSocket message: %s", exc)
            return

        for update in delta.get("updates", []):
            for entry in update.get("values", []):
                path = entry.get("path")
                watch = self._watches_by_path.get(path)
                if watch is None:
                    continue

                value = entry.get("value")
                if not isinstance(value, dict):
                    logger.warning("Notification value at '%s' is not a dict; skipping: %r", path, value)
                    continue

                self._dispatch(watch, value)

    async def _run_connection(self) -> None:
        subscribe_msg = {
            "context": "vessels.self",
            "subscribe": [
                {"path": watch.path, "policy": "instant"} for watch in self._watches
            ],
        }

        async with websockets.connect(self._ws_url) as ws:
            self._notify_connection_status("connected")

            await ws.send(json.dumps(subscribe_msg))
            await self._resync_current_state()

            while not self._stop_event.is_set():
                recv_task = asyncio.ensure_future(ws.recv())
                stop_task = asyncio.ensure_future(self._stop_event.wait())
                try:
                    done, pending = await asyncio.wait(
                        {recv_task, stop_task}, return_when=asyncio.FIRST_COMPLETED,
                    )
                    if recv_task in done:
                        self._handle_message(recv_task.result())
                    else:
                        break
                finally:
                    for task in pending:
                        task.cancel()

    async def run(self) -> None:
        """Connect-and-reconnect loop with escalating backoff. Runs until
        stop() is called.

        _run_connection() only returns without raising once the message
        loop notices stop_event is set, so a normal return here always
        means a deliberate shutdown, never a dropped connection — those
        surface as exceptions (ConnectionClosed, OSError, etc.) instead.
        """
        backoff_idx = 0

        while not self._stop_event.is_set():
            try:
                await self._run_connection()
                break  # stop() was called — clean shutdown.
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.warning("SignalK WebSocket connection lost: %s", exc)
                self._notify_connection_status("reconnecting")

                delay = RECONNECT_BACKOFF_SECONDS[min(backoff_idx, len(RECONNECT_BACKOFF_SECONDS) - 1)]
                backoff_idx += 1
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
