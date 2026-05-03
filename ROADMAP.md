# Roadmap — pi-deck-tools

## Phase 1 — Foundation *(complete)*

- [x] Define folder structure
- [x] Create README, STATE_OF_PLAY, ROADMAP
- [x] Initialise GitHub repository (`https://github.com/boatybits/pi-deck-tools`)
- [x] Set up `.venv` on Pi (`setup_pi_venv.sh`)
- [x] Create `shared/signalk.py`
- [x] Create `shared/vnc_window.py` — standard VNCToolWindow base class
- [x] Create `shared/opencpn_db.py` — route/waypoint reader from navobj.db
- [x] Port and clean existing draft tools into `apps/`
  - [x] `maidenhead.py` — Signal K position → Maidenhead grid locator
  - [x] `hifiberry_volume.py` — HiFiBerry DAC volume via amixer
  - [x] `sun_moon.py` — celestial calculator (Skyfield, Hipparcos, de421)
- [x] Test all tools launching from OpenCPN on Pi

## Phase 2 — Passage Planning *(complete)*

- [x] `apps/passage_planning.py` — route-based passage planning tool
  - [x] Load OpenCPN routes via `shared/opencpn_db.py`
  - [x] GRIB2 wind overlay (`shared/grib_reader.py`) — TWD, TWS, TWA, AWS, AWA
  - [x] GRIB2 wave overlay — WvDir, WvAng, WvHt, WvPer
  - [x] 3-hour timeline table (tksheet)
  - [x] Per-cell amber highlight for upwind TWA rows
  - [x] GRIB departure coverage check dialog
  - [x] Departure slider snapped to GRIB valid times, auto-rebuilds table on release
  - [x] Departure UTC text entry snaps to nearest GRIB step on Build
  - [x] NaN wave values render as `--`
  - [x] Resizable window with minsize
  - [x] Windy-style transposed layout (timeline columns)
  - [x] Frozen field labels via row index (always visible)
  - [x] Wind/wave color ramps + compact legend
  - [x] Direction arrows on Course/TWD/TWA/AWA cells
  - [x] Friendly departure slider text
  - [x] Persist last-used GRIB path
- [x] `shared/grib_reader.py` — GRIB2 wind + wave reader
  - [x] cfgrib + xarray + numpy; all data as numpy arrays
  - [x] Linear time interpolation + nearest-grid-point spatial
  - [x] Independent has_wave_height / has_wave_direction / has_wave_period properties
  - [x] Graceful partial loading (e.g. height without direction)

## Phase 3 — Polish & New Tools *(active)*

- [x] `docs/opencpn_launcher_setup.md` — include passage planning launcher command
- [x] `launch_pi_app.sh` — passage_planning entry with fullscreen launcher mode
- [ ] Per-tool `--test` / offline mode for dev without Signal K
- [ ] `apps/nmea_monitor.py` — raw NMEA sentence display for diagnostics
- [ ] `apps/vhf_channels.py` — VHF marine channel quick reference with search
- [x] Passage planning: colour-code wave height and wind speed with gradient bands
- [ ] Passage planning: export table to CSV or plain text
- [ ] Passage planning: show wind barbs or arrows in a small map panel

## Phase 4 — Launcher Hub *(stretch goal)*

- A single `apps/launcher_menu.py` hub presenting all tools as large buttons.
  User launches only this from OpenCPN; avoids cluttering the Launcher Plugin.

