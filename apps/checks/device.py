#!/usr/bin/env python3
"""Hardware device presence checks for mcd.

Each function checks whether a given device path exists on disk and
returns a CheckResult. Missing devices are not necessarily failures
(e.g. a USB sensor that is unplugged in port) but are always worth
surfacing in the daily summary.

Devices watched:
    Serial devices (ttyOP aliases — OpenPlotter udev):
        /dev/ttyOP_gps, /dev/ttyOP_ais, /dev/ttyOP_wind, /dev/ttyOP_comp

    USB devices:
        /dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0
            (Arduino Nano, pypilot)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from apps.checks import CheckResult

# ---------------------------------------------------------------------------
# Devices to watch: (CheckResult name, device path)
# ---------------------------------------------------------------------------

SERIAL_DEVICES = [
    ("ttyOP_gps", "/dev/ttyOP_gps"),
    ("ttyOP_ais", "/dev/ttyOP_ais"),
    ("ttyOP_wind", "/dev/ttyOP_wind"),
    ("ttyOP_comp", "/dev/ttyOP_comp"),
]

USB_DEVICES = [
    ("arduino_nano", "/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0"),
]


def _check_device(name: str, path: str, severity: str) -> CheckResult:
    """Return a CheckResult for a single device path."""
    if Path(path).exists():
        return CheckResult(name=name, ok=True, detail=f"present ({path})", severity=severity)
    return CheckResult(name=name, ok=False, detail=f"missing ({path})", severity=severity)


def check_serial() -> list[CheckResult]:
    """Check all watched ttyOP serial device aliases. All critical."""
    return [_check_device(name, path, "critical") for name, path in SERIAL_DEVICES]


def check_usb() -> list[CheckResult]:
    """Check all watched USB devices. All non-critical."""
    return [_check_device(name, path, "non-critical") for name, path in USB_DEVICES]


def check_all() -> list[CheckResult]:
    """Check all watched devices. Called by mcd main loop."""
    return check_serial() + check_usb()
