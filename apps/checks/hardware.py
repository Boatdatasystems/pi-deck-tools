#!/usr/bin/env python3
"""Onboard hardware health checks for mcd.

Covers Raspberry Pi throttling/temperature (via vcgencmd, absent on dev
machines) and general CPU/RAM load (via psutil).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from apps.checks import CheckResult, format_uptime
from shared.config import MCD_SWAP_TREND_RISE_THRESHOLD, MCD_SWAP_TREND_WINDOW_MINUTES

RAM_PERCENT_FAIL_THRESHOLD = 85
SWAP_PERCENT_FAIL_THRESHOLD = 25
DISK_PERCENT_FAIL_THRESHOLD = 85

# (timestamp via time.monotonic(), swap percent) history for check_swap_trend().
_swap_history: deque[tuple[float, float]] = deque()


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


def check_swap_trend() -> CheckResult:
    """Detect sustained swap growth over MCD_SWAP_TREND_WINDOW_MINUTES,
    complementing check_swap()'s absolute-threshold check. A swap percent
    that's well under SWAP_PERCENT_FAIL_THRESHOLD can still be a problem
    if it's climbing steadily — this catches that drift before it crosses
    the absolute threshold.
    """
    now = time.monotonic()
    percent = psutil.swap_memory().percent
    _swap_history.append((now, percent))

    window_seconds = MCD_SWAP_TREND_WINDOW_MINUTES * 60
    while _swap_history and (now - _swap_history[0][0]) > window_seconds:
        _swap_history.popleft()

    if len(_swap_history) < 2:
        return CheckResult(
            name="swap_trend", ok=True, detail="insufficient history",
            value=None, severity="non-critical",
        )

    oldest_percent = _swap_history[0][1]
    rise = round(percent - oldest_percent, 1)
    window_minutes = round((now - _swap_history[0][0]) / 60)

    if rise > MCD_SWAP_TREND_RISE_THRESHOLD:
        detail = f"swap risen {rise}pp over {window_minutes} min ({oldest_percent:.1f}% -> {percent:.1f}%)"
        ok = False
    else:
        detail = f"swap stable ({rise:+.1f}pp over {window_minutes} min)"
        ok = True

    return CheckResult(name="swap_trend", ok=ok, detail=detail, value=rise, severity="non-critical")


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


def check_xorg() -> CheckResult:
    """Check Xorg's RSS and CPU usage. Informational only — see
    docs/mission_control_design.md §1 "lightdm RAM creep" for why this
    targets Xorg rather than lightdm, and for the OpenCPN-post-sleep CPU
    spike scenario this CPU% tracking is meant to catch.

    name stays "xorg_ram" for backward compatibility with existing
    Obsidian history, even though this now reports CPU as well as RSS.
    """
    total_rss = 0
    total_cpu_pct = 0.0
    found = False
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == "Xorg":
                total_rss += proc.memory_info().rss
                # interval=0.1 blocks for 100ms per Xorg process to measure
                # CPU% — see apps/checks/process.py: check_opencpn() for the
                # same tradeoff (a future fix would keep Process objects
                # alive across sweeps and use cpu_percent(interval=None)).
                total_cpu_pct += proc.cpu_percent(interval=0.1)
                found = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not found:
        return CheckResult(name="xorg_ram", ok=True, detail="Xorg not running", value=None)

    rss_mb = total_rss / (1024 * 1024)
    detail = f"RSS: {rss_mb:.1f} MB, CPU: {total_cpu_pct}%"
    value = {"rss_mb": rss_mb, "cpu_percent": total_cpu_pct}
    return CheckResult(name="xorg_ram", ok=True, detail=detail, value=value)


def check_disk_space() -> CheckResult:
    """Check free space on the root filesystem. Fails if usage exceeds
    DISK_PERCENT_FAIL_THRESHOLD.

    Critical: a full disk can silently break SignalK logging, InfluxDB
    writes, and Obsidian summary writes all at once.
    """
    total, used, free = shutil.disk_usage("/")
    total_gb = total / (1024 ** 3)
    used_gb = used / (1024 ** 3)
    free_gb = free / (1024 ** 3)
    percent = used / total * 100
    ok = percent <= DISK_PERCENT_FAIL_THRESHOLD
    detail = f"{used_gb:.1f} GB / {total_gb:.1f} GB ({percent:.1f}%) free: {free_gb:.1f} GB"
    return CheckResult(name="disk_space", ok=ok, detail=detail, value=percent, severity="critical")


def check_disk_space_data() -> CheckResult:
    """Check free space on the /data mount (NVMe — InfluxDB, Obsidian
    vault, etc.). Fails if usage exceeds DISK_PERCENT_FAIL_THRESHOLD.

    Non-critical: substantial headroom currently (34% used at initial
    measurement), and a full /data degrades logging/Obsidian rather than
    threatening the OS itself, unlike a full root filesystem.
    """
    try:
        total, used, free = shutil.disk_usage("/data")
    except FileNotFoundError:
        return CheckResult(
            name="disk_space_data", ok=False, detail="/data not mounted",
            value=None, severity="non-critical",
        )

    total_gb = total / (1024 ** 3)
    used_gb = used / (1024 ** 3)
    free_gb = free / (1024 ** 3)
    percent = used / total * 100
    ok = percent <= DISK_PERCENT_FAIL_THRESHOLD
    detail = f"{used_gb:.1f} GB / {total_gb:.1f} GB ({percent:.1f}%) free: {free_gb:.1f} GB"
    return CheckResult(name="disk_space_data", ok=ok, detail=detail, value=percent, severity="non-critical")


def check_all() -> list[CheckResult]:
    """Run all hardware health checks. Called by mcd main loop."""
    return [
        check_throttle(),
        check_soc_temp(),
        check_cpu(),
        check_ram(),
        check_swap(),
        check_swap_trend(),
        check_uptime(),
        check_xorg(),
        check_disk_space(),
        check_disk_space_data(),
    ]
