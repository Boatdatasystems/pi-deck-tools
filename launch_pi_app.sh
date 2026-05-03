#!/usr/bin/env bash
set -euo pipefail

# Launch a pi-deck-tools app using the project-local Pi virtual environment.
#
# Usage:
#   bash launch_pi_app.sh maidenhead
#   bash launch_pi_app.sh hifiberry_volume
#   bash launch_pi_app.sh sun_moon
#   bash launch_pi_app.sh passage_planning
#   bash launch_pi_app.sh passage_planner
#   bash launch_pi_app.sh backup_utility
#
# Optional:
#   PI_DECK_DISPLAY=:0 bash launch_pi_app.sh maidenhead

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$PROJECT_DIR/.venv/bin/python"
APPS_DIR="$PROJECT_DIR/apps"

if [ $# -ne 1 ]; then
  echo "Usage: bash launch_pi_app.sh <maidenhead|hifiberry_volume|sun_moon|passage_planning|passage_planner|backup_utility|backup>"
  exit 1
fi

APP_NAME="$1"
if [ "$APP_NAME" = "passage_planner" ]; then
  APP_NAME="passage_planning"
fi
if [ "$APP_NAME" = "backup" ]; then
  APP_NAME="backup_utility"
fi
APP_PATH="$APPS_DIR/${APP_NAME}.py"

if [ ! -x "$VENV_PY" ]; then
  echo "Missing venv python at: $VENV_PY"
  echo "Run: bash setup_pi_venv.sh"
  exit 1
fi

if [ ! -f "$APP_PATH" ]; then
  echo "Unknown app: $APP_NAME"
  echo "Valid options: maidenhead, hifiberry_volume, sun_moon, passage_planning (alias: passage_planner), backup_utility (alias: backup)"
  exit 1
fi

# Keep OpenCPN's DISPLAY by default. Only override when explicitly requested.
if [ -n "${PI_DECK_DISPLAY:-}" ]; then
  export DISPLAY="$PI_DECK_DISPLAY"
fi

if [ "$APP_NAME" = "passage_planning" ]; then
  exec "$VENV_PY" "$APP_PATH" --fullscreen
fi

exec "$VENV_PY" "$APP_PATH"
