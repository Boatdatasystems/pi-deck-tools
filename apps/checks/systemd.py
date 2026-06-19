#!/usr/bin/env python3
"""systemd service health checks for mcd.

Each function calls `systemctl is-failed <unit>` via subprocess and returns
a CheckResult. A unit that is active or inactive (but not failed) is
considered ok. A unit in the failed state, or one that cannot be found,
returns ok=False.

Units watched:
    Tier 1 (offshore critical):
        signalk.service, pypilot.service, pypilot_web.service,
        ssh.service, NetworkManager.service, vncserver-x11-serviced.service

    Tier 2 (data pipeline):
        influxdb.service, ble-scanner.service, grafana-server.service,
        lightdm.service
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from apps.checks import CheckResult, format_uptime

# ---------------------------------------------------------------------------
# Units to watch, grouped by tier for clarity.
# add_to_stubs_in_mcd: replace check_systemd_services stub with check_all()
# ---------------------------------------------------------------------------

# (unit_name, critical) — critical units that are not active are a failure;
# non-critical units that are not active are merely reported.
TIER1_UNITS = [
    ("signalk.service", True),
    ("pypilot.service", True),
    ("pypilot_web.service", False),
    ("ssh.service", False),
    ("NetworkManager.service", True),
    ("vncserver-x11-serviced.service", False),
]

TIER2_UNITS = [
    ("influxdb.service", False),
    ("ble-scanner.service", False),
    ("grafana-server.service", False),
    ("lightdm.service", True),
]


def _unit_uptime(unit: str) -> str | None:
    """Return how long unit has been active, formatted, or None if unknown.

    Parses `systemctl show -p ActiveEnterTimestamp --value <unit>`, e.g.
    "Thu 2026-06-18 14:23:10 BST" — the weekday and timezone abbreviation
    are dropped and the remaining "YYYY-MM-DD HH:MM:SS" is compared against
    local wall-clock time (systemd reports in the system's local timezone).
    """
    try:
        result = subprocess.run(
            ["systemctl", "show", "-p", "ActiveEnterTimestamp", "--value", unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        parts = result.stdout.strip().split()
        if len(parts) < 3:
            return None
        entered = datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
        seconds = (datetime.now() - entered).total_seconds()
        if seconds < 0:
            return None
    except Exception:
        return None
    return format_uptime(seconds)


def _check_unit(unit: str, critical: bool = False) -> CheckResult:
    """Return a CheckResult for a single systemd unit.

    Uses `systemctl is-failed` which exits 0 if the unit IS failed,
    non-zero if it is in any other state (active, inactive, not-found, etc.).
    We therefore also call `systemctl is-active` to distinguish
    active (ok) from not-found or inactive (worth noting but not a failure).

    For critical units, anything other than active is treated as a failure
    (ok=False). For non-critical units, not-active is merely reported.
    """
    name = unit.replace(".service", "")
    severity = "critical" if critical else "non-critical"

    # First check: is the unit in a failed state?
    try:
        failed = subprocess.run(
            ["systemctl", "is-failed", "--quiet", unit],
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return CheckResult(name=name, ok=False, detail=f"systemctl error: {exc}", severity=severity)

    if failed.returncode == 0:
        # is-failed exits 0 when the unit IS failed
        return CheckResult(name=name, ok=False, detail="systemd unit in failed state", severity=severity)

    # Second check: distinguish active vs inactive/not-found
    try:
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return CheckResult(name=name, ok=False, detail=f"systemctl error: {exc}", severity=severity)

    if active.returncode == 0:
        uptime_str = _unit_uptime(unit)
        detail = f"active (up {uptime_str})" if uptime_str else "active"
        return CheckResult(name=name, ok=True, detail=detail, severity=severity)
    else:
        # Get the actual state for the detail string
        try:
            state = subprocess.run(
                ["systemctl", "show", "-p", "ActiveState", "--value", unit],
                capture_output=True,
                text=True,
                timeout=5,
            )
            state_str = state.stdout.strip() or "unknown"
        except Exception:
            state_str = "unknown"
        detail = f"not active ({state_str})"
        if critical:
            # A critical service that isn't active is a failure.
            return CheckResult(name=name, ok=False, detail=detail, severity=severity)
        # inactive is not a failure for optional/situational units,
        # but we still report it so it appears in the Obsidian summary.
        return CheckResult(name=name, ok=True, detail=detail, severity=severity)


def check_tier1() -> list[CheckResult]:
    """Check all Tier 1 (offshore critical) systemd units."""
    return [_check_unit(unit, critical=critical) for unit, critical in TIER1_UNITS]


def check_tier2() -> list[CheckResult]:
    """Check all Tier 2 (data pipeline) systemd units."""
    return [_check_unit(unit, critical=critical) for unit, critical in TIER2_UNITS]


def check_all() -> list[CheckResult]:
    """Check all watched systemd units. Called by mcd main loop."""
    return check_tier1() + check_tier2()
