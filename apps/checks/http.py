#!/usr/bin/env python3
"""HTTP health checks for mcd.

Checks Signal K over its REST API rather than just probing the TCP port,
so we catch the case where the process is up but not actually serving
useful data (e.g. no GPS fix flowing through).
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from apps.checks import CheckResult

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


def check_all() -> list[CheckResult]:
    """Run all HTTP health checks. Called by mcd main loop."""
    return [check_signalk_http(), check_signalk_position()]
