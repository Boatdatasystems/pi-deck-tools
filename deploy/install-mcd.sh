#!/usr/bin/env bash
# Install and enable the Mission Control daemon (mcd) systemd service.
#
# Usage (on the Pi):
#   sudo deploy/install-mcd.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sudo cp "$SCRIPT_DIR/mcd.service" /etc/systemd/system/mcd.service
sudo systemctl daemon-reload
sudo systemctl enable mcd.service

echo ""
echo "mcd.service installed and enabled."
echo "Start it with: sudo systemctl start mcd.service"
echo "Follow logs with: journalctl -u mcd -f"
