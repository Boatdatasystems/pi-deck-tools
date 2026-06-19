#!/usr/bin/env python3
"""Onboard hardware health checks for mcd.

Covers Raspberry Pi throttling/temperature (via vcgencmd, absent on dev
machines) and general CPU/RAM load (via psutil).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from apps.checks import CheckResult, format_uptime

RAM_PERCENT_FAIL_THRESHOLD = 85
SWAP_PERCENT_FAIL_THRESHOLD = 25


def check_throttle() -> CheckResult:
    """Check the Pi's under-voltage / throttling status via vcgencmd."""
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return CheckResult(name="throttle", ok=True, detail="vcgencmd not available (dev machine)")
    except subprocess.TimeoutExpired:
        return CheckResult(name="throttle", ok=False, detail="vcgencmd timed out", severity="critical")

    output = result.stdout.strip()
    # Expected format: "throttled=0x50000"
    try:
        hex_str = output.split("=")[1]
        value = int(hex_str, 16)
    except (IndexError, ValueError):
        return CheckResult(name="throttle", ok=False, detail=f"could not parse: {output}", severity="critical")

    ok = value == 0
    severity = "non-critical" if ok else "critical"
    return CheckResult(name="throttle", ok=ok, detail=hex_str, value=value, severity=severity)


def check_soc_temp() -> CheckResult:
    """Check the Pi's SoC temperature via vcgencmd. Informational only."""
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return CheckResult(name="soc_temp", ok=True, detail="vcgencmd not available (dev machine)")
    except subprocess.TimeoutExpired:
        return CheckResult(name="soc_temp", ok=False, detail="vcgencmd timed out")

    output = result.stdout.strip()
    # Expected format: "temp=42.1'C"
    try:
        temp_str = output.split("=")[1].rstrip("'C")
        temp = float(temp_str)
    except (IndexError, ValueError):
        return CheckResult(name="soc_temp", ok=True, detail=f"could not parse: {output}")

    return CheckResult(name="soc_temp", ok=True, detail=f"{temp}°C", value=temp)


def check_cpu() -> CheckResult:
    """Check current CPU usage. Informational only."""
    percent = psutil.cpu_percent(interval=1)
    return CheckResult(name="cpu", ok=True, detail=f"{percent}%", value=percent)


def check_ram() -> CheckResult:
    """Check current RAM usage. Fails if usage exceeds RAM_PERCENT_FAIL_THRESHOLD."""
    mem = psutil.virtual_memory()
    used_mb = mem.used / (1024 * 1024)
    total_mb = mem.total / (1024 * 1024)
    ok = mem.percent <= RAM_PERCENT_FAIL_THRESHOLD
    detail = f"{used_mb:.0f} MB / {total_mb:.0f} MB ({mem.percent}%)"
    return CheckResult(name="ram", ok=ok, detail=detail, value=mem.percent)


def check_swap() -> CheckResult:
    """Check current swap usage. Fails if usage exceeds SWAP_PERCENT_FAIL_THRESHOLD."""
    swap = psutil.swap_memory()
    used_mb = swap.used / (1024 * 1024)
    total_mb = swap.total / (1024 * 1024)
    ok = swap.percent <= SWAP_PERCENT_FAIL_THRESHOLD
    detail = f"{used_mb:.1f} MB / {total_mb:.1f} MB ({swap.percent}%)"
    return CheckResult(name="swap", ok=ok, detail=detail, value=swap.percent, severity="non-critical")


def check_uptime() -> CheckResult:
    """Check system uptime via /proc/uptime. Informational only."""
    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
    except FileNotFoundError:
        return CheckResult(
            name="uptime",
            ok=True,
            detail="uptime check unavailable on this platform",
            value=None,
        )

    return CheckResult(
        name="uptime",
        ok=True,
        detail=format_uptime(uptime_seconds),
        value=uptime_seconds,
        severity="non-critical",
    )


def check_xorg_memory() -> CheckResult:
    """Check Xorg's RSS. Informational only — see docs/mission_control_design.md
    §1 "lightdm RAM creep" for why this targets Xorg rather than lightdm."""
    total_rss = 0
    found = False
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == "Xorg":
                total_rss += proc.memory_info().rss
                found = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not found:
        return CheckResult(name="xorg_ram", ok=True, detail="Xorg not running", value=None)

    mb = total_rss / (1024 * 1024)
    return CheckResult(name="xorg_ram", ok=True, detail=f"RSS: {mb:.1f} MB", value=float(total_rss))


def check_all() -> list[CheckResult]:
    """Run all hardware health checks. Called by mcd main loop."""
    return [check_throttle(), check_soc_temp(), check_cpu(), check_ram(), check_swap(), check_uptime(), check_xorg_memory()]
