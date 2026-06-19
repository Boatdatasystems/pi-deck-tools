#!/usr/bin/env python3
"""Mission Control Daemon — mcd.py

Headless, always-on system health observer for Conachair's Pi.
Managed by systemd (mcd.service). No GUI dependencies.

Phase 1 behaviour:
  - Runs a full health check sweep every MCD_CHECK_INTERVAL_SECONDS.
  - Writes structured results to journald via the standard logger.
  - At MCD_SUMMARY_HOUR each day, appends a markdown summary to the
    Obsidian daily note under MCD_OBSIDIAN_VAULT_PATH/MCD_OBSIDIAN_SUBFOLDER.
  - Sends sd_notify(READY=1) on startup and WATCHDOG=1 each sweep.
    Falls back gracefully if python-systemd is not installed (dev machines).

Phase 2+ (not yet implemented):
  - alerting on observed patterns
  - boat-state-aware policy
  - HTTP/WebSocket status endpoint for mcdash

Usage (Pi, managed by systemd):
    systemctl start mcd.service

Usage (dev / test):
    python3 apps/mcd.py
    python3 apps/mcd.py --once   # run one sweep and exit
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import (
    MCD_CHECK_INTERVAL_SECONDS,
    MCD_OBSIDIAN_SUBFOLDER,
    MCD_OBSIDIAN_VAULT_PATH,
    MCD_SUMMARY_HOUR,
    MCD_WATCHDOG_SEC,
)
from shared.logger import get_logger
from apps.checks import CheckResult
from apps.checks.device import check_all as check_devices
from apps.checks.hardware import check_all as check_hardware
from apps.checks.http import check_all as check_http
from apps.checks.process import check_all as check_processes
from apps.checks.systemd import check_all as check_systemd_services
from apps.alerts.audio import play_critical_alert

logger = get_logger("mcd")

# Last known ok status per critical check name, used to detect alert
# start/clear transitions across sweeps. Reset on every mcd restart.
_previous_critical_state: dict[str, bool] = {}

# ---------------------------------------------------------------------------
# systemd integration (optional — absent on dev machines)
# ---------------------------------------------------------------------------

try:
    from systemd.daemon import notify as _sd_notify  # type: ignore
    _SYSTEMD_AVAILABLE = True
except ImportError:
    _SYSTEMD_AVAILABLE = False
    logger.debug("python-systemd not available; sd_notify calls are no-ops")


def sd_notify(message: str) -> None:
    """Send a notification to systemd if available; silently skip otherwise."""
    if _SYSTEMD_AVAILABLE:
        _sd_notify(message)


# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

# Each entry is a callable that returns list[CheckResult].
# Replace stubs with real modules as they are implemented.
ALL_CHECKS = [
    check_systemd_services,
    check_processes,
    check_http,
    check_devices,
    check_hardware,
]


# ---------------------------------------------------------------------------
# Core sweep
# ---------------------------------------------------------------------------

def run_sweep() -> list[CheckResult]:
    """Run all registered checks and return the combined results."""
    results: list[CheckResult] = []
    for check_fn in ALL_CHECKS:
        try:
            results.extend(check_fn())
        except Exception as exc:
            # A broken check must not crash the daemon.
            results.append(CheckResult(
                name=check_fn.__name__,
                ok=False,
                detail=f"check raised exception: {exc}",
            ))
    return results


def log_results(results: list[CheckResult], dt: datetime) -> None:
    """Write each result to journald via the project logger.

    dt is the current local time, used to timestamp any critical alert
    start/clear transitions logged to Openplotter/alerts.md.
    """
    for r in results:
        if r.ok:
            logger.info(str(r))
        else:
            logger.warning(str(r))
            if r.severity == "critical":
                play_critical_alert(r.name)
                # TODO: notify mcdash once mcdash exists

        if r.severity == "critical":
            previous_ok = _previous_critical_state.get(r.name)
            first_seen = previous_ok is None
            transitioned = (not first_seen) and (r.ok != previous_ok)
            if (first_seen and not r.ok) or transitioned:
                log_critical_alert_transition(r.name, r.ok, r.detail, dt)
            _previous_critical_state[r.name] = r.ok


# ---------------------------------------------------------------------------
# Critical alert transition log
# ---------------------------------------------------------------------------

def log_critical_alert_transition(name: str, ok: bool, detail: str, dt: datetime) -> None:
    """Append a single ALERT START / ALERT CLEAR line to alerts.md.

    This is a running incident log, separate from the daily system-health
    summary — only critical checks that change state get a line here.
    """
    alerts_dir = Path(MCD_OBSIDIAN_VAULT_PATH) / "Openplotter"
    alerts_dir.mkdir(parents=True, exist_ok=True)
    path = alerts_dir / "alerts.md"

    label = "ALERT CLEAR" if ok else "ALERT START"
    line = f"- **{label}** `{dt:%Y-%m-%d %H:%M:%S}` — `{name}`: {detail}"

    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.info("Critical alert transition logged to %s", path)
    except OSError as exc:
        logger.error("Failed to write critical alert transition: %s", exc)


# ---------------------------------------------------------------------------
# Obsidian daily summary
# ---------------------------------------------------------------------------

def obsidian_summary_path(dt: datetime) -> Path:
    """Return the path for dt's daily summary file, under vault/subfolder/YYYY/MM/.

    dt is expected to be local time, so the folder/filename date matches the
    date the crew actually experienced rather than the UTC date.
    """
    vault = Path(MCD_OBSIDIAN_VAULT_PATH)
    year_dir = dt.strftime("%Y")
    month_dir = dt.strftime("%m")
    day_dir = vault / MCD_OBSIDIAN_SUBFOLDER / year_dir / month_dir
    day_dir.mkdir(parents=True, exist_ok=True)
    filename = dt.strftime("%Y-%m-%d-%a") + ".md"
    return day_dir / filename


def write_obsidian_summary(results: list[CheckResult], dt: datetime) -> None:
    """Append a markdown health summary to the Obsidian daily note.

    dt is expected to be local time (see obsidian_summary_path).
    """
    path = obsidian_summary_path(dt)
    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    overall = "✅ All checks passed" if fail_count == 0 else f"⚠️ {fail_count} check(s) failed"

    lines = [
        f"## System health — {dt.strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"{overall} ({ok_count} ok, {fail_count} failed)",
        f"",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for r in results:
        status = "✅" if r.ok else "❌"
        lines.append(f"| `{r.name}` | {status} | {r.detail} |")

    lines += ["", "---", ""]

    try:
        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logger.info("Obsidian summary written to %s", path)
    except OSError as exc:
        logger.error("Failed to write Obsidian summary: %s", exc)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(once: bool = False) -> None:
    """Run the daemon. If once=True, do one sweep and exit (for testing)."""
    logger.info("mcd starting — interval=%ds watchdog=%ds",
                MCD_CHECK_INTERVAL_SECONDS, MCD_WATCHDOG_SEC)
    sd_notify("READY=1")

    last_summary_date: int | None = None  # day-of-year of last summary written

    while True:
        local_now = datetime.now()

        # --- Run checks ---
        results = run_sweep()
        log_results(results, local_now)
        sd_notify("WATCHDOG=1")

        # --- Daily Obsidian summary at MCD_SUMMARY_HOUR ---
        if local_now.hour == MCD_SUMMARY_HOUR and local_now.timetuple().tm_yday != last_summary_date:
            write_obsidian_summary(results, local_now)
            last_summary_date = local_now.timetuple().tm_yday

        if once:
            logger.info("mcd --once: sweep complete, exiting")
            break

        time.sleep(MCD_CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mission Control Daemon")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one sweep and exit (for testing)",
    )
    args = parser.parse_args()
    main(once=args.once)
