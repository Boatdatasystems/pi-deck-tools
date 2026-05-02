#!/usr/bin/env python3
"""
Passage Planning Tool

Route-based passage planning with GRIB wind overlay.

Capabilities:
- Load a route from OpenCPN.
- Select and load a GRIB2 weather file (e.g. from XyGrib).
- Generate a 3-hour timeline from a departure time and assumed boat speed.
- Populate TWD°, TWS kt, TWA°, AWS kt, AWA° columns from GRIB data
  via spatial + temporal interpolation.

Pi dependencies (install once):
    sudo apt install libeccodes-dev libeccodes-tools
    pip install cfgrib xarray scipy
"""

from __future__ import annotations

import math
import sys
import tkinter as tk
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import filedialog, ttk

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.grib_reader import GribReader
from shared.opencpn_db import OpenCPNDbError, list_routes, route_with_waypoints
from shared.vnc_window import VNCToolWindow


EARTH_RADIUS_NM = 3440.065
TIMELINE_STEP_HOURS = 3


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in nautical miles."""
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_NM * c


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return initial course from point A to point B in degrees true."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon_rad = math.radians(lon2 - lon1)

    x = math.sin(dlon_rad) * math.cos(lat2_rad)
    y = (
        math.cos(lat1_rad) * math.sin(lat2_rad)
        - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon_rad)
    )
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def interpolate_lat_lon(start: dict, end: dict, fraction: float) -> tuple[float, float]:
    """Linear interpolation between two route points."""
    lat = start["lat"] + ((end["lat"] - start["lat"]) * fraction)
    lon = start["lon"] + ((end["lon"] - start["lon"]) * fraction)
    return lat, lon


def next_three_hour_utc() -> datetime:
    """Return the next rounded 3-hour UTC departure suggestion."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    next_hour_block = ((now.hour // TIMELINE_STEP_HOURS) + 1) * TIMELINE_STEP_HOURS
    if next_hour_block >= 24:
        now = now + timedelta(days=1)
        next_hour_block = 0
    return now.replace(hour=next_hour_block)


class PassagePlanningTool(VNCToolWindow):
    """Route-based passage planning scaffold for later GRIB integration."""

    def __init__(self):
        super().__init__(title="Passage Planning", width=1140, height=760)
        self.route_data: dict | None = None
        self.route_names: list[str] = []
        self.grib_reader: GribReader | None = None
        self.setup_ui()
        self.refresh_routes()
        self._preseed_grib_path()

    def setup_ui(self) -> None:
        controls = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        controls.pack(fill=tk.X, pady=(0, 10))

        route_row = tk.Frame(controls, bg=self.COLOR_BG)
        route_row.pack(fill=tk.X, pady=3)
        tk.Label(route_row, text="Route", font=self.font_normal, bg=self.COLOR_BG, fg=self.COLOR_FG, width=12, anchor="w").pack(side=tk.LEFT)
        self.route_var = tk.StringVar()
        self.route_combo = ttk.Combobox(route_row, textvariable=self.route_var, state="readonly", width=42)
        self.route_combo.pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(route_row, text="Refresh", command=self.refresh_routes, bg="#34495e", fg="white", padx=12).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(route_row, text="Load Route", command=self.load_selected_route, bg="#2980b9", fg="white", padx=12).pack(side=tk.LEFT)

        grib_row = tk.Frame(controls, bg=self.COLOR_BG)
        grib_row.pack(fill=tk.X, pady=3)
        tk.Label(grib_row, text="GRIB File", font=self.font_normal, bg=self.COLOR_BG, fg=self.COLOR_FG, width=12, anchor="w").pack(side=tk.LEFT)
        self.grib_var = tk.StringVar()
        tk.Entry(grib_row, textvariable=self.grib_var, width=62, font=self.font_small).pack(side=tk.LEFT, padx=(0, 8), fill=tk.X, expand=True)
        tk.Button(grib_row, text="Browse", command=self.browse_grib, bg="#34495e", fg="white", padx=12).pack(side=tk.LEFT)
        tk.Button(grib_row, text="Load GRIB", command=self.load_grib, bg="#8e44ad", fg="white", padx=12).pack(side=tk.LEFT, padx=(6, 0))

        plan_row = tk.Frame(controls, bg=self.COLOR_BG)
        plan_row.pack(fill=tk.X, pady=3)
        tk.Label(plan_row, text="Departure UTC", font=self.font_normal, bg=self.COLOR_BG, fg=self.COLOR_FG, width=12, anchor="w").pack(side=tk.LEFT)
        self.departure_var = tk.StringVar(value=next_three_hour_utc().strftime("%Y-%m-%d %H:%M"))
        tk.Entry(plan_row, textvariable=self.departure_var, width=20, font=self.font_small).pack(side=tk.LEFT, padx=(0, 14))
        tk.Label(plan_row, text="Boat Speed (kt)", font=self.font_normal, bg=self.COLOR_BG, fg=self.COLOR_FG).pack(side=tk.LEFT)
        self.speed_var = tk.StringVar(value="5.0")
        tk.Entry(plan_row, textvariable=self.speed_var, width=8, font=self.font_small).pack(side=tk.LEFT, padx=(8, 14))
        tk.Button(plan_row, text="Build 3h Table", command=self.generate_plan, bg="#27ae60", fg="white", padx=14).pack(side=tk.LEFT)

        self.summary_var = tk.StringVar(value="Load an OpenCPN route to begin.")
        tk.Label(self.content_frame, textvariable=self.summary_var, font=self.font_normal, bg=self.COLOR_BG, fg=self.COLOR_FG, anchor="w", justify=tk.LEFT).pack(fill=tk.X, pady=(0, 10))

        self.status_var = tk.StringVar(value="Load a route, select a GRIB file, then Build 3h Table.")
        tk.Label(self.content_frame, textvariable=self.status_var, font=self.font_small, bg=self.COLOR_BG, fg="#a8d8ff", anchor="w").pack(fill=tk.X, pady=(0, 8))

        table_frame = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = (
            "time",
            "leg",
            "lat",
            "lon",
            "course",
            "run_nm",
            "remain_nm",
            "twd",
            "tws",
            "twa",
            "aws",
            "awa",
        )
        self.plan_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=20)
        self.plan_tree.heading("time", text="UTC")
        self.plan_tree.heading("leg", text="Leg")
        self.plan_tree.heading("lat", text="Lat")
        self.plan_tree.heading("lon", text="Lon")
        self.plan_tree.heading("course", text="Course T")
        self.plan_tree.heading("run_nm", text="Run NM")
        self.plan_tree.heading("remain_nm", text="Remain NM")
        self.plan_tree.heading("twd", text="TWD°")
        self.plan_tree.heading("tws", text="TWS kt")
        self.plan_tree.heading("twa", text="TWA°")
        self.plan_tree.heading("aws", text="AWS kt")
        self.plan_tree.heading("awa", text="AWA°")

        widths = {
            "time": 130,
            "leg": 115,
            "lat": 88,
            "lon": 88,
            "course": 68,
            "run_nm": 70,
            "remain_nm": 82,
            "twd": 58,
            "tws": 58,
            "twa": 58,
            "aws": 58,
            "awa": 58,
        }
        for name, width in widths.items():
            self.plan_tree.column(name, width=width, anchor=tk.CENTER)

        y_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.plan_tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.plan_tree.xview)
        self.plan_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self.plan_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)

    def refresh_routes(self) -> None:
        try:
            routes = list_routes()
        except OpenCPNDbError as exc:
            self.show_error("OpenCPN Route Error", str(exc))
            self.status_var.set("Could not read OpenCPN route list.")
            return

        self.route_names = [route.name for route in routes if route.name]
        self.route_combo["values"] = self.route_names
        if self.route_names and not self.route_var.get():
            self.route_var.set(self.route_names[0])
        self.status_var.set(f"Loaded {len(self.route_names)} routes from OpenCPN.")

    def _preseed_grib_path(self) -> None:
        """If the data/ directory has a GRIB file and no path is set, pre-populate it."""
        if self.grib_var.get():
            return
        data_dir = Path(__file__).parent.parent / "data"
        if data_dir.is_dir():
            candidates = sorted(data_dir.glob("*.grb2")) + sorted(data_dir.glob("*.grb"))
            if candidates:
                self.grib_var.set(str(candidates[0]))

    def browse_grib(self) -> None:
        initial_dir = str(Path(__file__).parent.parent / "data")
        file_path = filedialog.askopenfilename(
            title="Select GRIB File",
            initialdir=initial_dir,
            filetypes=[
                ("GRIB files", "*.grb *.grib *.grb2 *.grib2"),
                ("All files", "*.*"),
            ],
        )
        if file_path:
            self.grib_var.set(file_path)
            self.grib_reader = None
            self.status_var.set("GRIB file selected — click Load GRIB to read coverage.")

    def load_grib(self) -> None:
        path = self.grib_var.get().strip()
        if not path:
            self.show_error("No GRIB File", "Select a GRIB file first.")
            return
        self.status_var.set("Loading GRIB file…")
        self.update_idletasks()
        try:
            self.grib_reader = GribReader(path)
            self.status_var.set(f"GRIB loaded – {self.grib_reader.coverage_summary()}")
        except ImportError as exc:
            self.grib_reader = None
            self.show_error(
                "GRIB Library Missing",
                str(exc),
            )
        except Exception as exc:
            self.grib_reader = None
            self.show_error("GRIB Load Error", str(exc))

    def load_selected_route(self) -> None:
        route_name = self.route_var.get().strip()
        if not route_name:
            self.show_error("Route Required", "Select a route first.")
            return

        try:
            self.route_data = route_with_waypoints(route_name)
        except OpenCPNDbError as exc:
            self.show_error("Route Load Error", str(exc))
            return

        waypoint_count = self.route_data["waypoint_count"]
        total_nm = self.route_total_nm(self.route_data["waypoints"])
        self.summary_var.set(
            f"Route: {route_name}    Waypoints: {waypoint_count}    Total Distance: {total_nm:.1f} NM\n"
            f"Apparent wind will require a boat-speed assumption. Current scaffold uses a constant speed in knots."
        )
        self.status_var.set("Route loaded. Build the 3-hour timeline now; GRIB columns are placeholders for the next step.")
        self.populate_route_preview()

    def populate_route_preview(self) -> None:
        self.clear_table()
        if not self.route_data:
            return

        for waypoint in self.route_data["waypoints"]:
            sequence = waypoint.get("sequence")
            label = waypoint.get("name") or f"WP {sequence if sequence is not None else '?'}"
            self.plan_tree.insert(
                "",
                tk.END,
                values=(
                    f"WP {sequence}" if sequence is not None else "WP",
                    label,
                    f"{waypoint['lat']:.4f}",
                    f"{waypoint['lon']:.4f}",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                    "--",
                ),
            )

    def generate_plan(self) -> None:
        if not self.route_data:
            self.show_error("No Route", "Load a route before building the passage table.")
            return

        try:
            departure_utc = datetime.strptime(self.departure_var.get().strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            self.show_error("Departure Format", "Use departure format YYYY-MM-DD HH:MM in UTC.")
            return

        try:
            speed_kn = float(self.speed_var.get())
        except ValueError:
            self.show_error("Boat Speed", "Boat speed must be a number in knots.")
            return

        if speed_kn <= 0:
            self.show_error("Boat Speed", "Boat speed must be greater than zero.")
            return

        rows = self.build_passage_rows(self.route_data["waypoints"], departure_utc, speed_kn)
        self.clear_table()
        for row in rows:
            self.plan_tree.insert("", tk.END, values=row)

        total_nm = self.route_total_nm(self.route_data["waypoints"])
        total_hours = total_nm / speed_kn if speed_kn > 0 else 0.0
        eta = departure_utc + timedelta(hours=total_hours)
        grib_note = "Wind data from GRIB." if self.grib_reader else "No GRIB loaded — wind columns are placeholders."
        self.status_var.set(
            f"Built {len(rows)} timeline rows at {TIMELINE_STEP_HOURS}-hour spacing. "
            f"ETA approx {eta.strftime('%Y-%m-%d %H:%M UTC')}. {grib_note}"
        )

    def build_passage_rows(self, waypoints: list[dict], departure_utc: datetime, speed_kn: float) -> list[tuple]:
        if len(waypoints) < 2:
            return []

        segments = []
        cumulative_nm = 0.0
        for index in range(len(waypoints) - 1):
            start = waypoints[index]
            end = waypoints[index + 1]
            distance_nm = haversine_nm(start["lat"], start["lon"], end["lat"], end["lon"])
            bearing_deg = initial_bearing_deg(start["lat"], start["lon"], end["lat"], end["lon"])
            segments.append(
                {
                    "start": start,
                    "end": end,
                    "distance_nm": distance_nm,
                    "bearing_deg": bearing_deg,
                    "start_cumulative_nm": cumulative_nm,
                }
            )
            cumulative_nm += distance_nm

        total_nm = cumulative_nm
        rows = []
        step_index = 0
        elapsed_hours = 0.0

        while True:
            run_nm = min(total_nm, speed_kn * elapsed_hours)
            row = self.row_for_distance(
                segments, run_nm, total_nm,
                departure_utc + timedelta(hours=elapsed_hours),
                speed_kn,
            )
            rows.append(row)
            if run_nm >= total_nm:
                break
            step_index += 1
            elapsed_hours = step_index * TIMELINE_STEP_HOURS

        if rows:
            last_time = rows[-1][0]
            final_eta = departure_utc + timedelta(hours=(total_nm / speed_kn))
            if last_time != final_eta.strftime("%Y-%m-%d %H:%M"):
                final_row = self.row_for_distance(segments, total_nm, total_nm, final_eta, speed_kn)
                rows.append(final_row)

        return rows

    def _wind_columns(self, lat: float, lon: float, time_utc: datetime, course_deg: float, speed_kn: float) -> tuple[str, str, str, str, str]:
        """Return (twd, tws, twa, aws, awa) strings; '--' if GRIB not loaded or outside coverage."""
        if self.grib_reader is None:
            return "--", "--", "--", "--", "--"
        try:
            w = self.grib_reader.wind_at(lat, lon, time_utc, course_deg, speed_kn)
            twa_str = f"{'+' if w.twa_deg >= 0 else ''}{w.twa_deg:.0f}°"
            awa_str = f"{'+' if w.awa_deg >= 0 else ''}{w.awa_deg:.0f}°"
            return (
                f"{w.twd_deg:.0f}°",
                f"{w.tws_kn:.1f}",
                twa_str,
                f"{w.aws_kn:.1f}",
                awa_str,
            )
        except Exception:
            return "--", "--", "--", "--", "--"

    def row_for_distance(self, segments: list[dict], run_nm: float, total_nm: float, time_utc: datetime, speed_kn: float = 5.0) -> tuple:
        for segment in segments:
            seg_start = segment["start_cumulative_nm"]
            seg_end = seg_start + segment["distance_nm"]
            if run_nm <= seg_end or math.isclose(run_nm, seg_end):
                if segment["distance_nm"] <= 0:
                    fraction = 0.0
                else:
                    fraction = max(0.0, min(1.0, (run_nm - seg_start) / segment["distance_nm"]))
                lat, lon = interpolate_lat_lon(segment["start"], segment["end"], fraction)
                start_name = segment["start"].get("name") or f"WP {segment['start'].get('sequence', '?')}"
                end_name = segment["end"].get("name") or f"WP {segment['end'].get('sequence', '?')}"
                twd, tws, twa, aws, awa = self._wind_columns(lat, lon, time_utc, segment["bearing_deg"], speed_kn)
                return (
                    time_utc.strftime("%Y-%m-%d %H:%M"),
                    f"{start_name}->{end_name}",
                    f"{lat:.4f}",
                    f"{lon:.4f}",
                    f"{segment['bearing_deg']:.0f}°",
                    f"{run_nm:.1f}",
                    f"{max(0.0, total_nm - run_nm):.1f}",
                    twd,
                    tws,
                    twa,
                    aws,
                    awa,
                )

        final = segments[-1]
        lat = final["end"]["lat"]
        lon = final["end"]["lon"]
        end_name = final["end"].get("name") or f"WP {final['end'].get('sequence', '?')}"
        twd, tws, twa, aws, awa = self._wind_columns(lat, lon, time_utc, final["bearing_deg"], speed_kn)
        return (
            time_utc.strftime("%Y-%m-%d %H:%M"),
            end_name,
            f"{lat:.4f}",
            f"{lon:.4f}",
            f"{final['bearing_deg']:.0f}°",
            f"{total_nm:.1f}",
            "0.0",
            twd,
            tws,
            twa,
            aws,
            awa,
        )

    def route_total_nm(self, waypoints: list[dict]) -> float:
        total_nm = 0.0
        for index in range(len(waypoints) - 1):
            total_nm += haversine_nm(
                waypoints[index]["lat"],
                waypoints[index]["lon"],
                waypoints[index + 1]["lat"],
                waypoints[index + 1]["lon"],
            )
        return total_nm

    def clear_table(self) -> None:
        for item in self.plan_tree.get_children():
            self.plan_tree.delete(item)


if __name__ == "__main__":
    app = PassagePlanningTool()
    app.mainloop()