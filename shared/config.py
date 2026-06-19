"""Central configuration for pi-deck-tools.

All values that differ between installations or that would otherwise be
scattered as magic literals are defined here. Import the relevant constant
rather than repeating the literal value.

To customise for a different installation, change only this file.
"""

import os

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
