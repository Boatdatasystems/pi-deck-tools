"""
GRIB weather file reader for pi-deck-tools.

Reads 10m U/V wind components from GRIB/GRIB2 files using cfgrib + xarray.
All data is loaded into numpy arrays at init time so that wind_at() is fast
and free from xarray coordinate-selection edge cases.

Dependencies (Pi install):
    sudo apt install libeccodes-dev libeccodes-tools
    pip install cfgrib xarray scipy
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class WindAtPoint:
    twd_deg: float   # True Wind Direction (degrees, 0–360, FROM)
    tws_kn: float    # True Wind Speed (knots)
    twa_deg: float   # True Wind Angle relative to course (-180 to +180)
    aws_kn: float    # Apparent Wind Speed (knots)
    awa_deg: float   # Apparent Wind Angle (-180 to +180, +ve starboard)


# ---------------------------------------------------------------------------
# Internal math helpers
# ---------------------------------------------------------------------------

def _ms_to_knots(ms: float) -> float:
    return ms * 1.94384


def _uv_to_dir_speed(u: float, v: float) -> tuple[float, float]:
    """u/v → (meteorological direction the wind comes FROM °, speed m/s)."""
    speed = math.sqrt(u * u + v * v)
    direction = (math.degrees(math.atan2(u, v)) + 180.0) % 360.0
    return direction, speed


def _twa(twd_deg: float, course_deg: float) -> float:
    """Signed True Wind Angle relative to course (-180 to +180, +ve starboard)."""
    return (twd_deg - course_deg + 180.0) % 360.0 - 180.0


def _apparent_wind(tws_ms: float, twa_deg: float, boat_speed_kn: float) -> tuple[float, float]:
    """Return (AWS knots, AWA degrees) from TWS m/s, TWA °, boat speed knots."""
    boat_ms = boat_speed_kn / 1.94384
    twa_rad = math.radians(twa_deg)
    aw_x = tws_ms * math.cos(twa_rad) + boat_ms
    aw_y = tws_ms * math.sin(twa_rad)
    aws_ms = math.sqrt(aw_x * aw_x + aw_y * aw_y)
    return _ms_to_knots(aws_ms), math.degrees(math.atan2(aw_y, aw_x))


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class GribReader:
    """
    Load a GRIB/GRIB2 file and interpolate wind at (lat, lon, time) points.

    All u10/v10 data is loaded into numpy arrays on construction so that
    wind_at() is a simple array lookup with no xarray overhead.

    Usage:
        reader = GribReader("path/to/file.grb2")
        wind = reader.wind_at(lat=37.5, lon=-8.3, time_utc=dt,
                              course_deg=245.0, boat_speed_kn=5.0)
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lats: "np.ndarray | None" = None
        self._lons: "np.ndarray | None" = None
        self._u10: "np.ndarray | None" = None   # shape (N_times, N_lat, N_lon)
        self._v10: "np.ndarray | None" = None
        self.valid_times: list[datetime] = []
        self.lat_min = self.lat_max = self.lon_min = self.lon_max = 0.0
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            import xarray as xr
        except ImportError as exc:
            raise ImportError(
                "cfgrib and xarray are required for GRIB reading.\n"
                "On the Pi: sudo apt install libeccodes-dev libeccodes-tools\n"
                "           pip install cfgrib xarray scipy"
            ) from exc

        import numpy as np
        import pandas as pd

        if not self.path.exists():
            raise FileNotFoundError(f"GRIB file not found: {self.path}")

        ds_u = xr.open_dataset(
            str(self.path), engine="cfgrib",
            filter_by_keys={"shortName": "10u"}, indexpath=None,
        )
        ds_v = xr.open_dataset(
            str(self.path), engine="cfgrib",
            filter_by_keys={"shortName": "10v"}, indexpath=None,
        )

        # --- latitude / longitude arrays ---------------------------------
        self._lats = ds_u.coords["latitude"].values.flatten()
        self._lons = ds_u.coords["longitude"].values.flatten()

        # --- valid times -------------------------------------------------
        # GFS files: valid_time is a 1-D coord indexed by "step".
        # Fall back to "time" for analysis-only files.
        if "valid_time" in ds_u.coords:
            raw_times = ds_u.coords["valid_time"].values
        elif "time" in ds_u.coords:
            raw_times = ds_u.coords["time"].values
        else:
            raise ValueError("No time coordinate found in GRIB dataset.")

        raw_times = np.atleast_1d(raw_times).flatten()
        parsed = [
            pd.Timestamp(t).to_pydatetime().replace(tzinfo=timezone.utc)
            for t in raw_times
        ]
        # Sort chronologically, keeping the mapping to original step indices.
        order = sorted(range(len(parsed)), key=lambda i: parsed[i])
        self.valid_times = [parsed[i] for i in order]

        # --- wind arrays -------------------------------------------------
        u_raw = ds_u["u10"].values
        v_raw = ds_v["v10"].values
        ds_u.close()
        ds_v.close()

        # Guarantee shape (N_times, N_lat, N_lon)
        if u_raw.ndim == 2:
            u_raw = u_raw[np.newaxis]
            v_raw = v_raw[np.newaxis]

        self._u10 = u_raw[order]
        self._v10 = v_raw[order]

        # --- spatial coverage summary ------------------------------------
        self.lat_min = float(self._lats.min())
        self.lat_max = float(self._lats.max())
        self.lon_min = float(self._lons.min())
        self.lon_max = float(self._lons.max())

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def coverage_summary(self) -> str:
        if not self.valid_times:
            return "No time steps found."
        start = self.valid_times[0].strftime("%Y-%m-%d %H:%MZ")
        end = self.valid_times[-1].strftime("%Y-%m-%d %H:%MZ")
        return (
            f"{len(self.valid_times)} steps  {start} → {end}  "
            f"Lat {self.lat_min:.1f}–{self.lat_max:.1f}  "
            f"Lon {self.lon_min:.1f}–{self.lon_max:.1f}"
        )

    def wind_at(
        self,
        lat: float,
        lon: float,
        time_utc: datetime,
        course_deg: float,
        boat_speed_kn: float,
    ) -> WindAtPoint:
        """
        Nearest-grid-point lookup + linear time interpolation.

        Args:
            lat / lon: decimal degrees (lon negative = West is fine).
            time_utc: UTC datetime (naive or aware).
            course_deg: True course for TWA calculation.
            boat_speed_kn: Boat speed for apparent wind calculation.
        """
        if time_utc.tzinfo is None:
            time_utc = time_utc.replace(tzinfo=timezone.utc)

        n = len(self.valid_times)
        if n == 1 or time_utc <= self.valid_times[0]:
            u, v = self._uv_at(0, lat, lon)
        elif time_utc >= self.valid_times[-1]:
            u, v = self._uv_at(n - 1, lat, lon)
        else:
            i_before = max(i for i, t in enumerate(self.valid_times) if t <= time_utc)
            i_after = i_before + 1
            span = (self.valid_times[i_after] - self.valid_times[i_before]).total_seconds()
            frac = (time_utc - self.valid_times[i_before]).total_seconds() / span
            u0, v0 = self._uv_at(i_before, lat, lon)
            u1, v1 = self._uv_at(i_after, lat, lon)
            u = u0 + (u1 - u0) * frac
            v = v0 + (v1 - v0) * frac

        twd_deg, tws_ms = _uv_to_dir_speed(u, v)
        twa_deg = _twa(twd_deg, course_deg)
        aws_kn, awa_deg = _apparent_wind(tws_ms, twa_deg, boat_speed_kn)

        return WindAtPoint(
            twd_deg=round(twd_deg, 1),
            tws_kn=round(_ms_to_knots(tws_ms), 1),
            twa_deg=round(twa_deg, 1),
            aws_kn=round(aws_kn, 1),
            awa_deg=round(awa_deg, 1),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _uv_at(self, time_idx: int, lat: float, lon: float) -> tuple[float, float]:
        """Nearest-grid-point u10, v10 at a given time index."""
        import numpy as np

        # Wrap lon to match dataset convention (0–360 vs −180–180).
        lon_q = lon + 360.0 if (self._lons.min() >= 0.0 and lon < 0.0) else lon

        lat_i = int(np.argmin(np.abs(self._lats - lat)))
        lon_i = int(np.argmin(np.abs(self._lons - lon_q)))

        return float(self._u10[time_idx, lat_i, lon_i]), float(self._v10[time_idx, lat_i, lon_i])
