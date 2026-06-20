#!/usr/bin/env python3
"""HTTP health checks for mcd.

Checks Signal K over its REST API rather than just probing the TCP port,
so we catch the case where the process is up but not actually serving
useful data (e.g. no GPS fix flowing through).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from apps.checks import CheckResult
from shared.config import MCD_BLE_DATA_MAX_AGE_SECONDS

SIGNALK_BASE_URL = "http://localhost:3000"
REQUEST_TIMEOUT_SECONDS = 3


def check_signalk_http() -> CheckResult:
    """Check that the Signal K REST API is reachable and responding."""
    url = f"{SIGNALK_BASE_URL}/signalk/v1/api/"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        return CheckResult(name="signalk_http", ok=False, detail=f"timeout after {REQUEST_TIMEOUT_SECONDS}s", severity="critical")
    except requests.exceptions.ConnectionError as exc:
        return CheckResult(name="signalk_http", ok=False, detail=f"connection error: {exc}", severity="critical")

    if resp.status_code == 200:
        return CheckResult(name="signalk_http", ok=True, detail="HTTP 200", severity="critical")
    return CheckResult(name="signalk_http", ok=False, detail=f"HTTP {resp.status_code}", severity="critical")


def check_signalk_position() -> CheckResult:
    """Check that Signal K is actually reporting a GPS position value."""
    url = f"{SIGNALK_BASE_URL}/signalk/v1/api/vessels/self/navigation/position"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        return CheckResult(name="signalk_position", ok=False, detail=f"timeout after {REQUEST_TIMEOUT_SECONDS}s", severity="critical")
    except requests.exceptions.ConnectionError as exc:
        return CheckResult(name="signalk_position", ok=False, detail=f"connection error: {exc}", severity="critical")

    if resp.status_code == 200 and "value" in resp.text:
        return CheckResult(name="signalk_position", ok=True, detail="position value present", severity="critical")
    return CheckResult(name="signalk_position", ok=False, detail=f"HTTP {resp.status_code}, no position value", severity="critical")


def check_ble_data_freshness() -> CheckResult:
    """Check that the BLE scanner is still actually delivering data.

    ble-scanner.service can stay "active" in systemd while producing
    zero data, if the underlying hci1 Bluetooth adapter is cycled —
    bleak's scan session does not survive that. So instead of watching
    the service unit, watch the most recent Victron battery voltage
    value SignalK has received, which only updates if the scanner is
    genuinely still receiving and forwarding BLE advertisements.
    """
    url = f"{SIGNALK_BASE_URL}/signalk/v1/api/vessels/self/electrical/batteries/house/voltage"
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.exceptions.Timeout:
        return CheckResult(
            name="ble_data_freshness", ok=False,
            detail=f"timeout after {REQUEST_TIMEOUT_SECONDS}s", severity="non-critical",
        )
    except requests.exceptions.ConnectionError as exc:
        return CheckResult(
            name="ble_data_freshness", ok=False,
            detail=f"connection error: {exc}", severity="non-critical",
        )

    if resp.status_code != 200:
        return CheckResult(
            name="ble_data_freshness", ok=False,
            detail="no data found", severity="non-critical",
        )

    try:
        data = resp.json()
        timestamp_str = data["timestamp"]
    except (ValueError, KeyError):
        return CheckResult(
            name="ble_data_freshness", ok=False,
            detail="no data found", severity="non-critical",
        )

    try:
        last_update = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except ValueError:
        return CheckResult(
            name="ble_data_freshness", ok=False,
            detail="no data found", severity="non-critical",
        )

    age_seconds = (datetime.now(timezone.utc) - last_update).total_seconds()
    ok = age_seconds <= MCD_BLE_DATA_MAX_AGE_SECONDS

    if ok:
        detail = f"fresh ({age_seconds:.0f}s ago)"
    else:
        minutes, seconds = divmod(int(age_seconds), 60)
        detail = f"last update {minutes}m {seconds}s ago"

    return CheckResult(
        name="ble_data_freshness", ok=ok, detail=detail,
        value=age_seconds, severity="non-critical",
    )


def check_all() -> list[CheckResult]:
    """Run all HTTP health checks. Called by mcd main loop."""
    return [check_signalk_http(), check_signalk_position(), check_ble_data_freshness()]
