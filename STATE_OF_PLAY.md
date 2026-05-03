# State of Play — pi-deck-tools

> **Purpose of this document:** Onboarding context for an AI assistant (or returning developer) to get up to speed quickly. Updated as the project progresses.

*Last updated: 2026-05-03*

---

## Project Goal

Build a curated set of small, single-purpose Python/tkinter tools that run on a Raspberry Pi 5 aboard a small boat. Each tool is launched directly from the **OpenCPN Launcher Plugin**, which calls `python3 /path/to/script.py` inside a VNC session. Tools must be self-contained, open quickly, and be usable on a small touchscreen or via mouse in VNC.

---

## Physical Setup

| Item | Details |
|---|---|
| Computer | Raspberry Pi 5, 4 GB RAM |
| OS | Raspberry Pi OS (Debian Bookworm) |
| Python | 3.11.2 |
| Audio DAC | HiFiBerry (ALSA — controlled via `amixer`) |
| Display | Touchscreen + remote VNC |
| Chart plotter | OpenCPN (with Launcher Plugin) |
| Data bus | Signal K server on `localhost:3000` |
| Sync | Syncthing between Pi and Windows dev machine |
| Remote dev | SSH + VS Code Remote-SSH |

---

## Repository

- GitHub: `https://github.com/boatybits/pi-deck-tools`
- Pi path: `/home/pi/pi-deck-tools`
- Pi venv: `/home/pi/pi-deck-tools/.venv` (set up via `setup_pi_venv.sh`)
- Launch helper: `launch_pi_app.sh <app_name>` (e.g. `launch_pi_app.sh passage_planning`)

---

## Key Software & APIs

### Signal K REST API
Base URL: `http://localhost:3000/signalk/v1/api/vessels/self/`

Paths used:
- `navigation/position/value` → `{ latitude, longitude }`
- `environment/outside/temperature/value` → float (Kelvin)
- `environment/outside/pressure/value` → float (Pascals)

### OpenCPN
- Routes/waypoints stored in SQLite: `/home/pi/.opencpn/navobj.db`
- Launcher Plugin fires a shell command per button
- `shared/opencpn_db.py` provides `list_routes()` and `route_with_waypoints()`

### GRIB Weather Files
- Downloaded from XyGrib as GFS 0.25° + WW3 GRIB2 files
- Stored in `data/` (gitignored — download fresh per passage)
- Read by `shared/grib_reader.py` via `cfgrib` + `xarray` + `numpy`
- Known variables in XyGrib WW3 files: `10u`, `10v`, `swh`, `shww`, `wvdir`, `mpww`, `t2m`, `tcc`, `tp`, `gust`

---

## Shared Modules (`shared/`)

| Module | Purpose |
|---|---|
| `signalk.py` | `get_sk_value(path)` helper — all apps import this |
| `opencpn_db.py` | Read routes/waypoints from OpenCPN SQLite navobj.db |
| `vnc_window.py` | Base class `VNCToolWindow` — standard window size, colours, fonts |
| `grib_reader.py` | Load GRIB2 wind + wave data; `wind_at()`, `wave_height_at()`, `wave_direction_at()` |

---

## Apps (`apps/`)

| App | Status | Notes |
|---|---|---|
| `passage_planning.py` | **Active / working** | Route loader + GRIB wind + wave overlay, transposed Windy-style timeline, frozen field labels, color ramps + legend, departure slider |
| `sun_moon.py` | Working | Celestial calculator using Skyfield + `data/de421.bsp`; sun/moon rise/set/transit; requires `hip_main.dat` for star chart |
| `maidenhead.py` | Working | Gets position from Signal K, calculates 6-char Maidenhead grid locator |
| `hifiberry_volume.py` | Working | tkinter sliders → `amixer sset` for HiFiBerry DAC volume |
| `opencpn_db_probe.py` | Utility | Interactive probe for navobj.db schema/content |

---

## passage_planning.py — Detail

**Table layout (transposed Windy-style):**
- Columns = timeline steps (3-hour spacing)
- Frozen row-index labels = `UTC | Leg | Run NM | Remain NM | Course T | TWD° | TWA° | AWA° | TWS kt | AWS kt | WvDir° | WvAng° | WvHt m | WvPer s`

**Key features:**
- Load route from OpenCPN and build 3h-step timeline from departure time + boat speed
- GRIB wind: TWD, TWS, TWA (signed), AWS, AWA with linear time interpolation + nearest-grid-point spatial
- GRIB wave: wave direction, wave angle relative to bow, significant wave height, wave period
- Frozen field-label column via tksheet row index (always visible while timeline columns scroll)
- Course and wind-angle directional arrows (16-point) in table cells
- Wind-speed Beaufort color ramp (TWS/AWS) and wave-height color ramp (WvHt)
- Compact in-app legend for wind and wave color bands
- Upwind TWA cells highlighted amber (about −50° to +50°)
- Departure timeline slider with friendly labels (for example: "Leave Monday 5th May at 12:00")
- GRIB coverage check dialog — warns if ETA exceeds GRIB end, offers adjust/proceed/cancel
- Last-used GRIB path persistence in `.last_grib_path`
- OpenCPN launcher mode starts passage planning in fullscreen
- Table widget: `tksheet` 7.6.0 (with compatibility wrappers for API differences across versions)

**GRIB wave loading notes:**
- `shortName: "wvdir"` is the wave direction field in XyGrib WW3 files (not `mwd`)
- `shortName: "swh"` or `"shww"` for wave height
- cfgrib dataset variable names are CF standard names, not shortNames — loader uses `next(iter(ds.data_vars))` to avoid KeyError
- `has_wave_height` and `has_wave_direction` are independent properties — table shows height even if direction unavailable

---

## Data Files (`data/`)

| File | Tracked in git | Notes |
|---|---|---|
| `de421.bsp` | Yes (16 MB) | JPL planetary ephemeris — required for sun_moon.py |
| `hip_main.dat` | Yes (53 MB) | Hipparcos star catalogue — required for sun_moon.py star chart |
| `*.grb2`, `*.idx` | No (gitignored) | GRIB weather files — download fresh from XyGrib per passage |

---

## Pi Setup

```bash
git clone https://github.com/boatybits/pi-deck-tools ~/pi-deck-tools
cd ~/pi-deck-tools
bash setup_pi_venv.sh        # installs libeccodes, creates .venv, pip installs requirements.txt
```

**Key requirements (from `requirements.txt`):**
`tksheet>=7.3`, `cfgrib>=0.9.10`, `xarray>=2023.1`, `scipy>=1.11`, `skyfield`, `reportlab`, `requests`

---

## Known Issues / TODOs

- [x] Passage planning screenshot committed in `docs/images/`
- [ ] `opencpn_db_probe.py` is a dev utility — consider moving to `tools/` or `dev/`
- [ ] Passage planning: export table to CSV or plain text
- [ ] Passage planning: optional map mini-panel with wind barbs/arrows
- [x] Passage planning: manual Departure UTC entry snaps to nearest GRIB step on Build
- [x] Wave period column (`mpww`) now shown in table as `WvPer s`

---

## Useful Links

| Topic | Link |
|---|---|
| OpenCPN Launcher Plugin | https://opencpn-manuals.github.io/main/opencpn-plugins/launcher/docs/ |
| Signal K specification | https://signalk.org/specification/1.7.0/doc/ |
| Skyfield (celestial) | https://rhodesmill.org/skyfield/ |
| cfgrib documentation | https://github.com/ecmwf/cfgrib |
| tksheet documentation | https://github.com/ragardner/tksheet |
| XyGrib | https://opengribs.org/en/xygrib |
| OpenCPN navobj.db schema | https://github.com/OpenCPN/OpenCPN/blob/master/model/src/navobj_db.cpp |

