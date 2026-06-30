"""Write-through of mcd's per-check numeric values to the local InfluxDB
instance on the Pi — shared/influx_writer.py

Separate from and unrelated to the website's remote droplet InfluxDB.
Lets mcd's health-check trends (swap, ram, cpu, soc_temp, RSS, etc.) be
graphed in Grafana and queried properly instead of grep-ing journald.

Inert until influxdb_credentials.json (gitignored/stignore'd, Pi-only)
is created — see shared.config.INFLUXDB_CREDENTIALS_PATH.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from shared.config import INFLUXDB_CREDENTIALS_PATH, INFLUXDB_MEASUREMENT_MCD_CHECKS
from shared.logger import get_logger

if TYPE_CHECKING:
    from apps.checks import CheckResult

logger = get_logger(__name__)

_credentials_warning_logged = False


def _load_credentials() -> dict | None:
    """Load url/token/org/bucket from INFLUXDB_CREDENTIALS_PATH.

    Logs a WARNING only the first time the file is missing or malformed
    (module-level flag) so a genuinely-absent credentials file doesn't
    spam the log every mcd tick — the feature is meant to stay silently
    inert until someone sets it up on the Pi.
    """
    global _credentials_warning_logged

    path = Path(INFLUXDB_CREDENTIALS_PATH)
    try:
        with open(path, "r", encoding="utf-8") as f:
            creds = json.load(f)
        for key in ("url", "token", "org", "bucket"):
            if key not in creds:
                raise KeyError(key)
        return creds
    except Exception as exc:
        if not _credentials_warning_logged:
            logger.warning(
                "InfluxDB credentials not available (%s); mcd check history will not be written until %s is set up",
                exc, path,
            )
            _credentials_warning_logged = True
        return None


def _is_plain_numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _build_points(check_results: list["CheckResult"]) -> list[Point]:
    """Build one Point per numeric value found in check_results.

    A plain int/float value becomes one point tagged check_name = the
    check's own name. A dict value (e.g. opencpn's
    {"rss_mb": ..., "cpu_percent": ...}) is split into one point per
    numeric sub-key, tagged check_name = f"{name}_{key}" — this keeps
    every sub-metric as its own independently filterable series in
    Grafana, consistent with how every other check is one check_name =
    one numeric series. Non-numeric values (None, strings, non-numeric
    dict entries) are skipped silently. Every point derived from a
    given check, including split-out sub-metric points, carries that
    check's own top-level ok status.
    """
    points = []
    for r in check_results:
        if _is_plain_numeric(r.value):
            points.append(
                Point(INFLUXDB_MEASUREMENT_MCD_CHECKS)
                .tag("check_name", r.name)
                .field("value", float(r.value))
                .field("ok", bool(r.ok))
            )
        elif isinstance(r.value, dict):
            for key, sub_value in r.value.items():
                if not _is_plain_numeric(sub_value):
                    continue
                points.append(
                    Point(INFLUXDB_MEASUREMENT_MCD_CHECKS)
                    .tag("check_name", f"{r.name}_{key}")
                    .field("value", float(sub_value))
                    .field("ok", bool(r.ok))
                )
    return points


def write_check_values(check_results: list["CheckResult"]) -> None:
    """Write every numeric check value from this mcd loop tick to the
    local InfluxDB instance, tagged by check_name, under
    INFLUXDB_MEASUREMENT_MCD_CHECKS. Never raises — any failure
    (missing credentials file, connection error, write error) is logged
    and swallowed, since InfluxDB availability must never block or
    crash mcd's main loop. Skips non-numeric values silently (e.g. a
    check whose value is a string); a dict value is split into one
    point per numeric sub-key (see _build_points).
    """
    creds = _load_credentials()
    if creds is None:
        return

    points = _build_points(check_results)
    if not points:
        return

    try:
        with InfluxDBClient(url=creds["url"], token=creds["token"], org=creds["org"]) as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)
            write_api.write(bucket=creds["bucket"], org=creds["org"], record=points)
    except Exception as exc:
        logger.warning("Failed to write mcd check values to InfluxDB: %s", exc)
