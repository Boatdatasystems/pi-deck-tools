"""Read-side counterpart to influx_writer.py — shared/influx_reader.py

Queries the boat's local InfluxDB instance.  Two data sources:

  boatyDb          — SignalK's own bucket (navigation, wind, electrical,
                     environment, etc.), written by a SignalK-side plugin
                     independent of this project.

  MCD_data         — mcd's per-check history, written by influx_writer.py
                     under INFLUXDB_MEASUREMENT_MCD_CHECKS.

Intended as a shared foundation for two future consumers so neither
needs its own separate query logic:

  • Logbook daemon — calls query_aggregate() once per field per write
    cycle (e.g. mean apparent wind speed over the last hour).

  • Tkinter GUI app — calls query_range() and list_measurements() to
    populate a "pick what to plot" dropdown and fetch the selected
    series for ad-hoc plotting.

All three public functions are defensive: they never raise on connection,
credential, or query failure — they degrade to None (or empty DataFrame
for query_range) and log via the module logger.  Consistent with the
lesson from the 2026-06-20 Obsidian crash-loop incident: a missing or
misbehaving external data source must never crash the calling application.
"""

from __future__ import annotations

import warnings

import pandas as pd
from influxdb_client import InfluxDBClient
from influxdb_client.client.warnings import MissingPivotFunction

# The influxdb-client emits MissingPivotFunction when query_data_frame is
# used without a pivot() step.  We intentionally return the "long" format
# (one row per _field/_value) because it's simpler for callers and works
# correctly for every query this module issues.
warnings.filterwarnings("ignore", category=MissingPivotFunction)

from shared._influx_creds import load_credentials
from shared.config import INFLUXDB_SELF_CONTEXT
from shared.logger import get_logger

logger = get_logger(__name__)


def query_range(
    bucket: str,
    measurement: str,
    field: str | None = None,
    start: str = "-1h",
    stop: str = "now()",
    context: str | None = INFLUXDB_SELF_CONTEXT,
) -> pd.DataFrame | None:
    """Return all rows for *measurement* in *bucket* over [start, stop].

    Callers must distinguish two distinct return values:
      None           — the query itself failed (connection error, missing
                       credentials, InfluxDB error); treat as "unknown".
      empty DataFrame — the query succeeded but matched no rows; the
                       bucket/measurement exists but has no data in the
                       requested window.
    These mean different things: None should be surfaced as an error or
    retried; an empty DataFrame is a valid "no data" answer.

    Parameters
    ----------
    bucket:      InfluxDB bucket name.
    measurement: Value of the _measurement tag to filter on.
    field:       Optional _field filter; if None all fields are returned.
    start:       Flux range start — a duration literal ("-1h", "-30m") or
                 an RFC3339 timestamp ("2026-06-30T00:00:00Z").
    stop:        Flux range stop — same format; defaults to now().
    context:     Optional context tag filter; defaults to INFLUXDB_SELF_CONTEXT
                 (this vessel's MMSI) so AIS targets in the same bucket are
                 excluded.  Pass None to skip the context filter entirely.
    """
    creds = load_credentials()
    if creds is None:
        return None

    lines = [
        f'from(bucket: "{bucket}")',
        f'  |> range(start: {start}, stop: {stop})',
        f'  |> filter(fn: (r) => r._measurement == "{measurement}")',
    ]
    if field is not None:
        lines.append(f'  |> filter(fn: (r) => r._field == "{field}")')
    if context is not None:
        lines.append(f'  |> filter(fn: (r) => r.context == "{context}")')

    query = "\n".join(lines)

    try:
        with InfluxDBClient(url=creds["url"], token=creds["token"], org=creds["org"]) as client:
            result = client.query_api().query_data_frame(query, org=creds["org"])
        if isinstance(result, list):
            if not result:
                return pd.DataFrame()
            return pd.concat(result, ignore_index=True)
        return result if result is not None else pd.DataFrame()
    except Exception as exc:
        logger.warning("InfluxDB query_range failed for %s/%s: %s", bucket, measurement, exc)
        return None


def query_aggregate(
    bucket: str,
    measurement: str,
    field: str,
    aggregate: str,
    start: str = "-1h",
    stop: str = "now()",
    context: str | None = INFLUXDB_SELF_CONTEXT,
) -> float | None:
    """Return a single aggregate value for *field* in *measurement* over [start, stop].

    Designed for the logbook daemon: called once per field per write cycle
    to get, e.g., mean apparent wind speed or max boat speed over the
    last hour.

    Parameters
    ----------
    bucket, measurement, field, start, stop, context:
        Same semantics as query_range().
    aggregate:
        One of "mean", "max", "min".  Any other value raises ValueError
        immediately — this is a programming error, not a runtime condition.

    Returns
    -------
    float | None
        The aggregated value, or None if the window contained no data or
        the query failed.  Failures are logged; no exception is raised.
    """
    if aggregate not in ("mean", "max", "min"):
        raise ValueError(f"aggregate must be 'mean', 'max', or 'min'; got {aggregate!r}")

    creds = load_credentials()
    if creds is None:
        return None

    measurement_and_field = (
        f'r._measurement == "{measurement}" and r._field == "{field}"'
    )
    lines = [
        f'from(bucket: "{bucket}")',
        f'  |> range(start: {start}, stop: {stop})',
        f'  |> filter(fn: (r) => {measurement_and_field})',
    ]
    if context is not None:
        lines.append(f'  |> filter(fn: (r) => r.context == "{context}")')
    lines.append(f'  |> {aggregate}()')

    query = "\n".join(lines)

    try:
        with InfluxDBClient(url=creds["url"], token=creds["token"], org=creds["org"]) as client:
            df = client.query_api().query_data_frame(query, org=creds["org"])
        if isinstance(df, list):
            if not df:
                return None
            df = pd.concat(df, ignore_index=True)
        if df is None or df.empty:
            return None
        return float(df["_value"].iloc[0])
    except Exception as exc:
        logger.warning(
            "InfluxDB query_aggregate (%s) failed for %s/%s/%s: %s",
            aggregate, bucket, measurement, field, exc,
        )
        return None


def list_measurements(bucket: str) -> list[str] | None:
    """Return distinct measurement names present in *bucket*.

    Useful for a GUI's "pick what to plot" dropdown — avoids hardcoding
    measurement names that may appear or disappear as SignalK plugins are
    added or removed.

    Returns
    -------
    list[str] | None
        Sorted list of measurement names, an empty list if the bucket
        genuinely contains none, or None if the query failed.
    """
    creds = load_credentials()
    if creds is None:
        return None

    query = (
        'import "influxdata/influxdb/schema"\n'
        f'schema.measurements(bucket: "{bucket}")'
    )

    try:
        with InfluxDBClient(url=creds["url"], token=creds["token"], org=creds["org"]) as client:
            df = client.query_api().query_data_frame(query, org=creds["org"])
        if isinstance(df, list):
            if not df:
                return []
            df = pd.concat(df, ignore_index=True)
        if df is None or df.empty:
            return []
        return sorted(df["_value"].dropna().astype(str).tolist())
    except Exception as exc:
        logger.warning("InfluxDB list_measurements failed for bucket %s: %s", bucket, exc)
        return None
