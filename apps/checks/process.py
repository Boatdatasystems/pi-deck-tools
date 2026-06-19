#!/usr/bin/env python3
"""Process presence checks for mcd.

Checks whether key user-facing applications are running, distinct from
the systemd checks which only confirm the managing service is active.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from apps.checks import CheckResult, format_uptime


def check_opencpn() -> CheckResult:
    """Check whether the OpenCPN process is running."""
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] and "opencpn" in proc.info["name"].lower():
                uptime = format_uptime(time.time() - proc.create_time())
                detail = f"running (PID {proc.pid}, up {uptime})"
                return CheckResult(name="opencpn", ok=True, detail=detail, severity="critical")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return CheckResult(name="opencpn", ok=False, detail="not running", severity="critical")


def _check_situational_process(name: str) -> CheckResult:
    """Report presence/RSS of a situational, user-launched process.

    Always ok=True, non-critical — these apps are expected to be started
    and stopped manually, so their absence is never a failure.
    """
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == name:
                rss = proc.memory_info().rss
                mb = rss / (1024 * 1024)
                detail = f"running (PID {proc.pid}, RSS {mb:.1f} MB)"
                return CheckResult(name=name, ok=True, detail=detail, value=float(rss))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return CheckResult(name=name, ok=True, detail="not running", value=None)


def check_gqrx() -> CheckResult:
    """Check whether gqrx is running. Situational, informational only."""
    return _check_situational_process("gqrx")


def check_clementine() -> CheckResult:
    """Check whether Clementine is running. Situational, informational only."""
    return _check_situational_process("clementine")


def check_all() -> list[CheckResult]:
    """Run all process presence checks. Called by mcd main loop."""
    return [check_opencpn(), check_gqrx(), check_clementine()]
