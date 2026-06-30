"""Central configuration for pi-deck-tools.

All values that differ between installations or that would otherwise be
scattered as magic literals are defined here. Import the relevant constant
rather than repeating the literal value.

To customise for a different installation, change only this file.
"""

import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Signal K
# ---------------------------------------------------------------------------

# REST API base URL for the local Signal K server.
# Used by: shared/signalk.py
SIGNALK_URL = "http://localhost:3000"

# ---------------------------------------------------------------------------
# OpenCPN
# ---------------------------------------------------------------------------

# Path to OpenCPN's SQLite navigation database on the Pi.
# Used by: shared/opencpn_db.py, apps/sun_moon.py
OPENCPN_DB_PATH = "/home/pi/.opencpn/navobj.db"

# ---------------------------------------------------------------------------
# HiFiBerry DAC
# ---------------------------------------------------------------------------

# ALSA sound-card name for the HiFiBerry DAC, passed to amixer -c.
# Run `aplay -l` to find the correct name for your specific DAC model.
# Used by: apps/hifiberry_volume.py
HIFIBERRY_CARD_NAME = "sndrpihifiberry"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

# Rotating log file location. The ~ is expanded to the current user's home
# directory so the path works for any Pi username, not just 'pi'.
# Used by: shared/logger.py
LOG_PATH = os.path.expanduser("~/pi-deck-tools.log")

MCD_SWAP_TREND_WINDOW_MINUTES = 120
# Rolling window, in minutes, over which check_swap_trend() compares
# oldest vs newest swap percentage to detect sustained drift rather
# than a momentary spike.
# Used by: apps/checks/hardware.py

MCD_SWAP_TREND_RISE_THRESHOLD = 10
# Swap percentage-point rise within MCD_SWAP_TREND_WINDOW_MINUTES that
# triggers a non-critical alert — tuned from observed real-world drift
# of ~12pp over 6.75 hours (see data/mem_creep.csv from 2026-06-20).
# Used by: apps/checks/hardware.py

# ---------------------------------------------------------------------------
# Passage planning
# ---------------------------------------------------------------------------

# Width of each passage-plan column in hours. Controls the timeline step and
# the alignment of GRIB data lookups to the nearest step boundary.
# Used by: apps/passage_planning.py
GRIB_TIMELINE_STEP_HOURS = 3

# Default boat speed (knots) pre-filled in the passage planner speed entry.
# Used by: apps/passage_planning.py
PASSAGE_DEFAULT_SPEED_KNOTS = 5.0

# ---------------------------------------------------------------------------
# GQRX VHF recorder
# ---------------------------------------------------------------------------

# Hostname of the machine running GQRX with remote control enabled.
# Used by: apps/gqrx_vhf_recorder.py
GQRX_HOST = "localhost"

# TCP port for GQRX remote control (Tools → Remote control settings in GQRX).
# Used by: apps/gqrx_vhf_recorder.py
GQRX_PORT = 7356

# VHF channel selected by default when the recorder app starts.
# Must be a key in the channel_map dict in gqrx_vhf_recorder.py.
# Used by: apps/gqrx_vhf_recorder.py
GQRX_DEFAULT_CHANNEL = "Ch 11 (156.550 MHz)"

# Demodulation mode sent to GQRX on channel change.
# Used by: apps/gqrx_vhf_recorder.py
GQRX_DEFAULT_MODE = "FM"

# Passband width in Hz sent to GQRX on channel change (10 kHz = 10000 Hz).
# Used by: apps/gqrx_vhf_recorder.py
GQRX_DEFAULT_PASSBAND = 10000

# Directory where GQRX saves recordings. Must exist or be creatable on the Pi.
# Used by: apps/gqrx_vhf_recorder.py
GQRX_DEFAULT_OUTPUT_DIR = "/home/pi/gqrxReceived"

# ---------------------------------------------------------------------------
# Sun / Moon celestial tool
# ---------------------------------------------------------------------------

# Maximum star magnitude shown on the interactive sky chart. Brighter stars
# have lower magnitudes (Sirius ≈ −1.46). Increase to show more stars.
# Used by: apps/sun_moon.py
CHART_DEFAULT_MAX_MAG = 3.0

# Maximum magnitude loaded when building chart data. Should be >= CHART_DEFAULT_MAX_MAG
# so the slider can reveal fainter stars without reloading data.
# Used by: apps/sun_moon.py
CHART_DATA_MAX_MAG = 5.0

# ---------------------------------------------------------------------------
# Mission Control daemon (mcd)
# ---------------------------------------------------------------------------

# How often mcd runs its full check sweep, in seconds.
# Used by: apps/mcd.py
MCD_CHECK_INTERVAL_SECONDS = 60

# Default interval (seconds) between re-checking and re-alerting on a
# critical failure. Much faster than MCD_CHECK_INTERVAL_SECONDS so an
# ongoing outage keeps sounding rather than waiting a full minute between
# alerts. This is a DEFAULT — apps/checks/__init__.py's CheckResult has an
# alert_interval_seconds field so a future mcdash config UI can override
# this per-check without changing the main loop.
MCD_ALERT_INTERVAL_SECONDS = 5

# Seconds after mcd starts during which critical alerts (audio + Obsidian
# transition log) are suppressed, even though checks still run and log
# normally. Prevents false alerts while other services (SignalK, pypilot,
# etc.) are still starting up after a reboot.
MCD_STARTUP_GRACE_SECONDS = 90

# systemd watchdog timeout. Must be > MCD_CHECK_INTERVAL_SECONDS.
# Set WatchdogSec= to this value in mcd.service.
# Used by: apps/mcd.py
MCD_WATCHDOG_SEC = 90

# Path to the Obsidian vault where daily summaries are written.
# Used by: apps/mcd.py
MCD_OBSIDIAN_VAULT_PATH = "/data/Obsidian"

# Subfolder inside the vault for mcd daily summaries.
# Used by: apps/mcd.py
MCD_OBSIDIAN_SUBFOLDER = "Openplotter"

# Hour (24h, local time) at which mcd writes the daily Obsidian summary.
# Used by: apps/mcd.py
MCD_SUMMARY_HOUR = 0

# Path mcd writes its latest sweep results to, as JSON, after every fast
# loop pass. Used by mcdash (Tkinter and web views) to display current
# status without talking to mcd directly.
MCD_STATUS_JSON_PATH = "/home/pi/pi-deck-tools/data/mcd_status.json"

# How often apps/mcdash_watcher.py polls MCD_STATUS_JSON_PATH for new
# critical failures, in seconds. Independent of mcd's own
# MCD_ALERT_INTERVAL_SECONDS — the watcher only needs to be fast enough
# that a new popup feels prompt, not fast enough to drive the audio
# alert cadence (mcd already handles that itself).
# Used by: apps/mcdash_watcher.py
MCDASH_WATCHER_POLL_SECONDS = 3

# Path to per-check alert overrides, edited via mcdash. mcd reads this
# file fresh on every fast-loop sweep (cheap — small file, simple parse)
# so changes take effect within MCD_ALERT_INTERVAL_SECONDS without a
# restart. Only checks with an explicit override appear in this file —
# everything else uses its hardcoded default from the check module.
MCD_ALERT_OVERRIDES_PATH = "/home/pi/pi-deck-tools/data/mcd_alert_overrides.json"

# Max age (seconds) of the most recent Victron battery voltage reading
# before mcd considers the BLE scanner's data stale and attempts a
# recovery restart. The scanner process can stay "active" in systemd
# while producing no data at all if the underlying hci1 Bluetooth
# adapter is cycled — bleak's scan session does not survive that.
# Confirmed via manual testing 2026-06-20: hci1-up.service restart left
# ble-scanner.service "active" with zero data until manually restarted.
MCD_BLE_DATA_MAX_AGE_SECONDS = 300

# Minimum time between automatic ble-scanner.service restarts, to avoid
# a restart loop if the underlying problem isn't actually fixed by a
# simple restart (e.g. hci1 itself is down).
MCD_BLE_RESTART_COOLDOWN_SECONDS = 600

# ---------------------------------------------------------------------------
# BLE scanner (apps/ble_scanner.py)
# ---------------------------------------------------------------------------

# MAC address of the ESP32 BoatSensor (temp/humidity/voltage beacon).
# Used by: apps/ble_scanner.py
ESP32_MAC = "58:8C:81:CA:F4:81"

# SignalK UDP listener address that decoded sensor/Victron readings are
# forwarded to.
# Used by: apps/ble_scanner.py
SIGNALK_IP = "10.42.0.1"
SIGNALK_PORT = 10119

# Bluetooth adapter used for scanning. Must match the adapter brought up
# by hci1-up.service (a second, dedicated BLE adapter — the Pi's onboard
# adapter is left for other uses).
# Used by: apps/ble_scanner.py
BT_ADAPTER = "hci1"

# Victron BLE devices to decode, keyed by MAC address. Each entry has:
#   name: human-readable label used in log output.
#   key:  the device's Instant Readout encryption key (from the VictronConnect app).
#   type: "shunt" or "mppt" — selects which parser to use.
#   tag:  (mppt only) short identifier used in the SignalK path, since
#         multiple MPPTs report under electrical.solar.<tag>.*.
# Used by: apps/ble_scanner.py
VICTRON_DEVICES = {
    "D4:F1:1E:AC:9F:87": {
        "name": "BoatyShunt",
        "key":  "106ca6492744d06008342454c5fe4bb8",
        "type": "shunt",
    },
    "F1:78:DC:43:40:22": {
        "name": "Boaty guard rails MPPT",
        "key":  "e52f09105d485dc4ba9ba5d4054e44ec",
        "type": "mppt",
        "tag":  "rails",
    },
    "E4:A1:1F:2A:35:68": {
        "name": "Boaty Radar Arch MPPT",
        "key":  "749d38db2943640ddcfc2a8f9cbe5762",
        "type": "mppt",
        "tag":  "arch",
    },
}

# ---------------------------------------------------------------------------
# SignalK notification alarms (apps/anchor_alarm.py)
# ---------------------------------------------------------------------------

# Volume (%) set via pactl while any SignalK notification alarm is
# active. Same fixed level for every alarm — see
# SIGNALK_NOTIFICATION_WATCHES for per-alarm sound files.
SIGNALK_ALARM_VOLUME_PERCENT = 80

ALSA_CARD_NAME = "sndrpihifiberry"
# ALSA card name for the HiFiBerry DAC's hardware "Digital" mixer
# control, confirmed via `amixer -c sndrpihifiberry sset Digital`.
# Independent of and in series with PipeWire's own sink volume.

SIGNALK_ALARM_DIGITAL_VOLUME_PERCENT = 80
# Level (%) to boost the ALSA Digital mixer to while any SignalK
# notification alarm is active, so the alarm can be heard above
# whatever level normal listening has the hardware mixer set to.
# Restored to its pre-alarm level on clear.

# Pause between repeats of the alarm sound while a notification is in
# the alarm/emergency state.
SIGNALK_ALARM_LOOP_GAP_SECONDS = 2

# Atomic JSON snapshot of current alarm state per watch, written on
# every state transition and connection-status change. Shared data
# source for a planned mcdash tab — see
# docs/mission_control_design.md.
ANCHOR_ALARM_STATUS_JSON_PATH = "data/anchor_alarm_status.json"

# ---------------------------------------------------------------------------
# InfluxDB (local Pi instance, mcd check history)
# ---------------------------------------------------------------------------

INFLUXDB_CREDENTIALS_PATH = "influxdb_credentials.json"
# Path (relative to project root) to the gitignored/stignore'd file
# containing url/token/org/bucket for the LOCAL InfluxDB instance on
# this Pi. Not committed or synced — must be created manually per
# machine that actually needs to write (i.e. only the Pi running
# mcd; the Windows dev machine doesn't need this file at all).

INFLUXDB_MEASUREMENT_MCD_CHECKS = "mcd_checks"
# Measurement name for mcd's per-check numeric values.


@dataclass(frozen=True)
class NotificationWatch:
    """One SignalK notification path to watch for alarm states."""
    path: str          # delta-style path, e.g. "notifications.navigation.anchor"
    name: str          # short identifier, used in logs and status JSON keys
    audio_path: Path   # wav file to loop while this watch is alarming


SIGNALK_NOTIFICATION_WATCHES = [
    NotificationWatch(
        path="notifications.navigation.anchor",
        name="anchor_drag",
        audio_path=Path("/home/pi/pi-deck-tools/assets/sounds/alarm_anchor_drag.wav"),
    ),
    # Add further NotificationWatch entries here for future alarms
    # (e.g. depth, AIS proximity) — no other code changes required.
]
