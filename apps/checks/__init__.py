"""apps/checks — Mission Control check functions.

Each check module exposes one or more functions that return CheckResult.
The main loop in apps/mcd.py imports and calls these; it does not care
which module produced a result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CheckResult:
    """Outcome of a single health check.

    Attributes:
        name:   Short identifier used in logs and Obsidian output.
                Use lowercase_with_underscores, e.g. 'signalk', 'ttyOP_gps'.
        ok:     True if the check passed, False if a problem was detected.
        detail: Human-readable one-line description of the outcome.
                Goes directly into journald and Obsidian — keep it concise.
        value:  Optional raw numeric or structured value (temperature float,
                RSS bytes, etc.) for future trend use.  Not logged by default.
        ts:     UTC timestamp set automatically at construction time.
        severity: "critical" or "non-critical". Critical failures trigger an
                audio alert in addition to surfacing in mcdash. See
                docs/mission_control_design.md, Phase 2 — Alert Policy.
        alert_interval_seconds: None means use the default
                MCD_ALERT_INTERVAL_SECONDS. A future config layer (e.g.
                mcdash) may set this per check name to override how often
                a specific failing check re-triggers its alert.
        enabled: If False, this check's audio alert and Obsidian
                transition logging are suppressed entirely, but it still
                runs and still appears in the journald log and the
                mcdash status JSON — disabling silences alerting for a
                known, accepted issue without hiding the check's current
                status.

    enabled, severity, and alert_interval_seconds may be overridden at
    runtime by apps/mcd.py before alerting logic runs, via
    apps/alert_overrides.py: apply_overrides() — check modules remain
    the source of DEFAULT values; overrides are applied centrally, not
    inside each check module.
    """

    name: str
    ok: bool
    detail: str
    value: Any = None
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    severity: str = "non-critical"  # "critical" or "non-critical"
    alert_interval_seconds: int | None = None
    enabled: bool = True

    def __str__(self) -> str:
        status = "OK" if self.ok else "FAIL"
        return f"[{status}] {self.name}: {self.detail}"


def format_uptime(seconds: float) -> str:
    """Format a duration in seconds as the largest two relevant units.

    Shared by check modules that report how long something has been
    running (system uptime, process uptime, systemd unit active time).
    """
    total_minutes = int(seconds // 60)
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)

    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
