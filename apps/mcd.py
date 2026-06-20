#!/usr/bin/env python3
"""Mission Control Daemon — mcd.py

Headless, always-on system health observer for Conachair's Pi.
Managed by systemd (mcd.service). No GUI dependencies.

Phase 1 behaviour — two-speed main loop:
  - The loop ticks every MCD_ALERT_INTERVAL_SECONDS (fast, default 5s).
  - run_sweep() and check_critical_alerts() run on every tick, so an
    ongoing critical failure keeps re-alerting at the fast cadence instead
    of waiting for the next slow sweep.
  - log_check_results() (journald), sd_notify("WATCHDOG=1"), and the daily
    Obsidian summary check/write only run every Nth tick, where
    N = MCD_CHECK_INTERVAL_SECONDS // MCD_ALERT_INTERVAL_SECONDS — i.e. at
    the slower MCD_CHECK_INTERVAL_SECONDS (default 60s) cadence.
  - Sends sd_notify(READY=1) on startup.
    Falls back gracefully if python-systemd is not installed (dev machines).
  - For the first MCD_STARTUP_GRACE_SECONDS after mcd starts, critical
    alerts (audio + Obsidian transition log) are suppressed, since
    systemd's After= ordering only guarantees a dependency has started,
    not that it has finished initializing. Checks still run and log
    normally during the grace period.
  - After every fast-loop tick, the full sweep results are written to
    MCD_STATUS_JSON_PATH as JSON (atomic write). This is the shared data
    source for mcdash (a planned Tkinter app and Flask web view, both
    not yet built) — they read this file rather than talking to mcd
    directly, so status shown is never more than MCD_ALERT_INTERVAL_SECONDS
    (default 5s) stale.

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
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.config import (
    MCD_ALERT_INTERVAL_SECONDS,
    MCD_CHECK_INTERVAL_SECONDS,
    MCD_OBSIDIAN_SUBFOLDER,
    MCD_OBSIDIAN_VAULT_PATH,
    MCD_STARTUP_GRACE_SECONDS,
    MCD_STATUS_JSON_PATH,
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


def check_critical_alerts(results: list[CheckResult], dt: datetime, elapsed_seconds: float) -> None:
    """Play/log audio alerts for critical failures. Runs every fast-loop tick.

    dt is the current local time, used to timestamp any critical alert
    start/clear transitions logged to Openplotter/alerts.md.

    elapsed_seconds is the time since mcd started. During the startup
    grace period (MCD_STARTUP_GRACE_SECONDS), alerting is suppressed but
    _previous_critical_state is still updated, so that once the grace
    period ends the state tracking is already correct and won't produce
    a spurious transition log for something that was already failing
    throughout the grace window.
    """
    in_grace_period = elapsed_seconds < MCD_STARTUP_GRACE_SECONDS

    for r in results:
        if r.severity != "critical":
            continue

        if not in_grace_period:
            if not r.ok:
                # TODO: once alert_interval_seconds is set by a config layer,
                # use it here to allow per-check alert cadence instead of firing
                # on every fast-loop pass.
                play_critical_alert(r.name)
                # TODO: notify mcdash once mcdash exists

            previous_ok = _previous_critical_state.get(r.name)
            first_seen = previous_ok is None
            transitioned = (not first_seen) and (r.ok != previous_ok)
            if (first_seen and not r.ok) or transitioned:
                log_critical_alert_transition(r.name, r.ok, r.detail, dt)

        _previous_critical_state[r.name] = r.ok


def log_check_results(results: list[CheckResult]) -> None:
    """Write each result to journald via the project logger. Runs at the
    slower MCD_CHECK_INTERVAL_SECONDS cadence.
    """
    for r in results:
        if r.ok:
            logger.info(str(r))
        else:
            logger.warning(str(r))


# ---------------------------------------------------------------------------
# JSON status snapshot (for mcdash)
# ---------------------------------------------------------------------------

def write_status_json(results: list[CheckResult], dt: datetime) -> None:
    """Write the latest sweep results to MCD_STATUS_JSON_PATH as JSON.

    Runs on every fast-loop tick — this is the shared data source for
    mcdash (Tkinter and web views), so it must stay no more than
    MCD_ALERT_INTERVAL_SECONDS stale. Written atomically (temp file +
    os.replace) so a reader never sees a partial write. This write is a
    nice-to-have, not safety-critical, so any OSError is logged and
    swallowed rather than allowed to crash the main loop.
    """
    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    critical_fail_count = sum(1 for r in results if not r.ok and r.severity == "critical")

    checks = []
    for r in results:
        value = r.value
        if value is not None and not isinstance(value, (str, int, float, bool, dict, list)):
            value = str(value)
        checks.append({
            "name": r.name,
            "ok": r.ok,
            "severity": r.severity,
            "detail": r.detail,
            "value": value,
            "ts": r.ts.isoformat(),
        })

    snapshot = {
        "updated_at": dt.isoformat(),
        "summary": {
            "ok_count": ok_count,
            "fail_count": fail_count,
            "critical_fail_count": critical_fail_count,
        },
        "checks": checks,
    }

    path = Path(MCD_STATUS_JSON_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.warning("Failed to write status JSON to %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Critical alert transition log
# ---------------------------------------------------------------------------

def log_critical_alert_transition(name: str, ok: bool, detail: str, dt: datetime) -> None:
    """Append a single ALERT START / ALERT CLEAR line to alerts.md.

    This is a running incident log, separate from the daily system-health
    summary — only critical checks that change state get a line here.

    The entire body is wrapped in a broad except: this is non-critical,
    nice-to-have logging, and must never be allowed to crash the daemon.
    A filesystem problem here (permissions, missing mount, disk full)
    previously took down mcd in a tight restart loop — see
    docs/mission_control_design.md, Phase 2 — Alert Policy.
    """
    try:
        alerts_dir = Path(MCD_OBSIDIAN_VAULT_PATH) / "Openplotter"
        alerts_dir.mkdir(parents=True, exist_ok=True)
        path = alerts_dir / "alerts.md"

        label = "ALERT CLEAR" if ok else "ALERT START"
        line = f"- **{label}** `{dt:%Y-%m-%d %H:%M:%S}` — `{name}`: {detail}"

        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.info("Critical alert transition logged to %s", path)
    except Exception as exc:
        logger.error("Failed to write critical alert transition: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Obsidian daily summary
# ---------------------------------------------------------------------------

class ObsidianPathError(Exception):
    """Raised when the Obsidian summary directory can't be created/accessed."""


def obsidian_summary_path(dt: datetime) -> Path:
    """Return the path for dt's daily summary file, under vault/subfolder/YYYY/MM/.

    dt is expected to be local time, so the folder/filename date matches the
    date the crew actually experienced rather than the UTC date.

    Raises ObsidianPathError if the directory can't be created (e.g. a
    permissions problem on the vault mount). Callers must catch this —
    see write_obsidian_summary(), which wraps this call in a broad
    except so a filesystem problem here degrades to a logged error
    rather than crashing the daemon.
    """
    vault = Path(MCD_OBSIDIAN_VAULT_PATH)
    year_dir = dt.strftime("%Y")
    month_dir = dt.strftime("%m")
    day_dir = vault / MCD_OBSIDIAN_SUBFOLDER / year_dir / month_dir
    try:
        day_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error("Cannot create Obsidian summary directory %s: %s", day_dir, exc)
        raise ObsidianPathError(f"Cannot create {day_dir}: {exc}") from exc
    filename = dt.strftime("%Y-%m-%d-%a") + ".md"
    return day_dir / filename


def write_obsidian_summary(results: list[CheckResult], dt: datetime) -> None:
    """Append a markdown health summary to the Obsidian daily note.

    dt is expected to be local time (see obsidian_summary_path).

    The entire body is wrapped in a broad except: this is non-critical,
    nice-to-have functionality, and must never be allowed to crash the
    daemon. A PermissionError from obsidian_summary_path()'s mkdir() call
    previously escaped uncaught and crashed mcd in a tight restart loop
    overnight — see docs/mission_control_design.md, Phase 2 — Alert Policy.
    """
    try:
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

        with path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logger.info("Obsidian summary written to %s", path)
    except Exception as exc:
        logger.error("Failed to write Obsidian summary: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main(once: bool = False) -> None:
    """Run the daemon. If once=True, do one sweep and exit (for testing)."""
    logger.info("mcd starting — alert_interval=%ds check_interval=%ds watchdog=%ds",
                MCD_ALERT_INTERVAL_SECONDS, MCD_CHECK_INTERVAL_SECONDS, MCD_WATCHDOG_SEC)
    sd_notify("READY=1")
    start_time = time.monotonic()

    # Number of fast (alert) ticks per slow (check/log) cycle.
    slow_tick_every = MCD_CHECK_INTERVAL_SECONDS // MCD_ALERT_INTERVAL_SECONDS

    last_summary_date: int | None = None  # day-of-year of last summary written
    iteration = 0
    grace_period_logged = False

    while True:
        local_now = datetime.now()
        elapsed_seconds = time.monotonic() - start_time

        if elapsed_seconds < MCD_STARTUP_GRACE_SECONDS and not grace_period_logged:
            logger.debug(
                "mcd startup grace period active (%ds remaining)",
                MCD_STARTUP_GRACE_SECONDS - int(elapsed_seconds),
            )
            grace_period_logged = True

        # --- Run checks and alert on critical failures (every tick) ---
        results = run_sweep()
        check_critical_alerts(results, local_now, elapsed_seconds)
        write_status_json(results, local_now)

        # --- Slower-cadence work: journald logging, watchdog, daily summary ---
        if iteration % slow_tick_every == 0:
            log_check_results(results)
            sd_notify("WATCHDOG=1")

            if local_now.hour == MCD_SUMMARY_HOUR and local_now.timetuple().tm_yday != last_summary_date:
                # Belt-and-suspenders: write_obsidian_summary() already
                # catches everything internally, but this is explicitly
                # non-critical functionality and must never be allowed to
                # take down the main loop, even via some future bug.
                try:
                    write_obsidian_summary(results, local_now)
                except Exception as exc:
                    logger.error("Unexpected error calling write_obsidian_summary: %s", exc, exc_info=True)
                last_summary_date = local_now.timetuple().tm_yday

        if once:
            logger.info("mcd --once: sweep complete, exiting")
            break

        iteration += 1
        time.sleep(MCD_ALERT_INTERVAL_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mission Control Daemon")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one sweep and exit (for testing)",
    )
    args = parser.parse_args()
    main(once=args.once)
