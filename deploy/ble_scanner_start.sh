#!/bin/bash
export HOME=/home/pi
cd /home/pi/pi-deck-tools
exec /home/pi/pi-deck-tools/.venv/bin/python3 apps/ble_scanner.py
