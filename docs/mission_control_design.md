# Mission Control — Design Overview

> **Purpose of this document:** Capture the design discussion for a proposed scope expansion of pi-deck-tools — from a set of user-launched single-purpose tools into an always-on system supervision and instrument-display layer. Drafted as input for the pi-deck-tools Claude Project so future sessions have shared context.

*Drafted: 2026-06-18. Not yet ratified into ROADMAP.*

---

## 1. Why this proposal exists

Recent observations from the boat:

- **OpenCPN freezes after display sleep.** On a recent passage, OpenCPN appeared frozen after the screen blanked. One CPU core saturated at 100% for about a minute as it caught up on buffered NMEA/SignalK input, then returned to normal. Root cause: DPMS/X11 render path pausing while the input threads keep queueing data. Symptom is benign in isolation but represents a class of "display-stack flakiness" that costs reliability offshore.
- **Chromium-based dashboards (Brave/Chrome) do not survive long runs.** Memory accumulation, GPU process leaks, and per-tab JS overhead make browser-served instrument panels (KIP, SignalK webapps) unsuitable for multi-day passages on a Pi 5 with 4 GB RAM.
- **"lightdm RAM creep" refined (2026-06-19):** Process-tree investigation during Phase 1 testing shows `lightdm` itself is negligible (~8 MB). The actual weight sits in its children: `Xorg` (~340 MB after 15h uptime) and whatever runs inside the X session — principally `opencpn` (~640 MB after 15h uptime, accumulating ~10 min CPU/hour). Future RAM-creep alerting should watch the Xorg/OpenCPN process tree specifically, not the lightdm daemon. Not yet clear whether OpenCPN's growth plateaus or is unbounded — needs a longer observation window (ideally a multi-day passage) before drawing conclusions.
- **Swap usage discovered high (2026-06-19):** `vm.swappiness` was at the Linux default of 60. With htop showing only ~400MB truly free RAM and significant buff/cache, the kernel had already pushed ~1GB into swap (likely SD card/eMMC — much slower than RAM). This is a plausible contributor to the earlier-observed OpenCPN freeze-after-sleep behaviour: if part of OpenCPN's working set had been swapped out, waking it requires reading those pages back from slow storage before it becomes responsive. Fixed by lowering vm.swappiness to 10 (`sudo sysctl vm.swappiness=10`, persisted in /etc/sysctl.conf). mcd now tracks swap usage (`apps/checks/hardware.py: check_swap()`) so this is visible in the daily Obsidian summary going forward, rather than requiring a manual htop check to notice.
- **No cross-service correlation today.** systemd restarts processes that crash, but there is no layer that recognises patterns ("OpenCPN restart-loop", "lightdm RSS climbing"), applies boat-state-aware policy, or surfaces a single health view.
- **Manual diagnostics required.** Throttling, thermal events, USB device drops, BLE scanner health, SignalK delta rate — all observable but not currently observed in one place.

These are exactly the kind of failures that matter most offshore and are hardest to diagnose at sea.

- **OpenCPN becomes unresponsive for a short period when pypilot is stopped.** Observed 2026-06-19 during Phase 2 alert testing: stopping `pypilot.service` (via the OpenPlotter pypilot app) caused OpenCPN to freeze for a brief window before recovering on its own. Root cause not yet confirmed — candidates are the OpenCPN pypilot plugin doing a blocking reconnect attempt on the UI thread, or a knock-on SignalK stall. Worth checking mcd's own `cpu` and `signalk_http` checks during the freeze window next time it's reproduced, to confirm whether SignalK is also affected or whether this is OpenCPN-plugin-specific. **Relevant to Phase 3 policy:** any future auto-restart logic for pypilot must account for this — a few seconds of frozen chart display could be worse than the pypilot outage itself if it happens while actively navigating a hazard.

---

## 2. Hard architectural distinction: supervision vs intelligence

The single most important framing for this work:

> **systemd runs the processes. Python observes the system and applies boat-aware policy on top.**

systemd already provides excellent process supervision: restart-on-failure, cgroup resource limits, boot sequencing, journald capture, watchdog support, signal handling, zombie reaping. Reimplementing any of this in Python would be a waste of effort and a stability regression.

What systemd does **not** provide:

- Cross-service correlation (e.g. "OpenCPN crashed 4 times in 5 min — stop restarting and alert")
- Boat-state-aware policy (e.g. "cycle X if RSS >2GB but only when not in pilotage waters")
- Unified health surfacing
- Trend-based alerting from InfluxDB
- A coherent instrument-display layer for the helm

That intelligence layer is what this proposal calls **Mission Control**.

---

## 3. Proposed components

Two distinct programs, both within pi-deck-tools:

### 3.1 `apps/mcd.py` — Mission Control Daemon

- Headless, always-on, no GUI dependencies
- Managed by a systemd unit (`mcd.service`)
- Hardware-watchdog enabled via systemd `WatchdogSec=`
- Reads:
  - `systemctl status` / journald via subprocess or dbus
  - `/proc`, `vcgencmd`, `psutil` for resource telemetry
  - SignalK REST/WS for boat state (anchored, underway, dockside)
  - InfluxDB for trend windows (already present via signalk-to-influxdb)
- Writes:
  - Structured status to journald (`journalctl -u mcd`)
  - Daily Obsidian summary note (system health, alarms, throttle events)
  - HTTP/WebSocket status endpoint for dashboard consumers
- Applies policy (eventually) — see phasing in §6

### 3.2 `apps/mcdash.py` — Mission Control Dashboard

- Tkinter-based, consistent with existing pi-deck-tools convention
- Builds on `shared/vnc_window.py` as the base
- Subscribes to SignalK + mcd status endpoint; holds no persistent state itself
- Replaces Chromium-based instrument displays for cockpit/helm use
- Killable and restartable without affecting supervision (mcd keeps running)

### 3.3 Why two programs, not one

If mcdash crashes, supervision must continue. If the dashboard had its own monitoring logic, a GUI bug could take out the watchdog. Separation is the safety-critical structure.

---

## 4. Why this fits the existing pi-deck-tools structure

| Existing piece | How Mission Control uses it |
|---|---|
| `shared/signalk.py` | mcd and mcdash both consume SignalK via this helper |
| `shared/vnc_window.py` | mcdash extends `VNCToolWindow` for visual consistency |
| `.venv` + `requirements.txt` | Adds `psutil`, `dbus-python` or `pystemd`, `influxdb-client` |
| `launch_pi_app.sh` | mcdash launches via existing helper; mcd via systemd (not OpenCPN) |
| docs/ pattern | This file, plus future `mission_control_runbook.md` |
| Black formatting | Same code style across the project |

This is a scope expansion, not a rewrite. The existing tools (passage_planning, maidenhead, sun_moon, hifiberry_volume, backup_utility) are unaffected.

---

## 5. Strict scope: what Mission Control deliberately does **not** do

Scope discipline is the biggest predictor of whether this project ships. Mission Control will not:

- **Replace systemd unit files.** Services are defined in systemd. mcd reads state via dbus or `systemctl`; it does not spawn processes itself.
- **Build a metrics database.** InfluxDB exists. mcd queries it; it does not accumulate ring buffers.
- **Replace OpenCPN or chart-plotter functionality.** Chart display, routes, AIS overlay, radar remain in OpenCPN. mcdash shows instruments and health.
- **Be a data hub.** SignalK is the data hub. mcd is a consumer.
- **Own persistent state.** Anything that needs to survive restart lives on disk (config), in SignalK, or in InfluxDB. mcd restart = rediscover the world.
- **Define a custom alerting protocol.** Alerts go to journald or one webhook. No bespoke pubsub.
- **Replace existing pi-deck-tools apps.** passage_planning et al. stay as user-launched tools.

If any of those boundaries get blurry in implementation, that is a red flag.

---

## 6. Phasing — observe before automating

Smart restart logic for failures that have not been observed is technical debt. The recommended sequence:

### Phase 1 — Passive observability (1–2 weekends)

- mcd reads systemctl + /proc + journald + SignalK + InfluxDB
- Emits structured records to journald
- Writes a daily Obsidian summary: services restarted, RSS peaks, throttle events, temperature, USB drops, SignalK delta rate, battery trend
- **No automated actions beyond what systemd already provides**
- mcdash: minimal Tkinter window with wind / SOG / depth / battery + service health badges

### Phase 2 — Alerting on observed patterns (after 4–6 weeks of Phase 1 data)

- Patterns identified from Phase 1 logs drive specific alerts
- Example: "lightdm RSS exceeded 1.5 GB three times this week" — alert worth having
- Still no automatic destructive actions
- mcdash: add trend sparklines, log feed, alarm acknowledgement UI

### Phase 3 — Boat-state-aware policy (selective, evidence-led)

- Rules of the form "cycle X if RSS >2GB AND state != pilotage AND state != anchor-approach"
- Each rule justified by Phase 1–2 data
- Each rule has manual override
- All policy decisions logged to Obsidian for review

Each phase is independently useful. Phase 1 alone delivers most of the diagnostic value.

---

## 7. Watch targets

Concrete boat-specific telemetry, each a small check function:

| Target | Source | Why it matters |
|---|---|---|
| Pi 5 throttling | `vcgencmd get_throttled` | Undervoltage is silent and corrosive offshore |
| CPU/SoC temperature | `vcgencmd measure_temp` | Cooling failure detection |
| Per-process RSS | `psutil` | Catches lightdm, XORG, Chromium memory growth |
| systemd service health | `systemctl is-failed`, journald | OpenCPN, SignalK, ble-scanner, hci1-up, pypilot |
| USB device presence | `/dev/serial/by-id` | GPS, AIS, Signalink, IC-7000 dropouts |
| BLE scanner health | journalctl + heartbeat | Victron data flow integrity |
| SignalK delta rate | SignalK REST stats endpoint | Detects upstream stall before downstream symptoms |
| InfluxDB disk usage | `df` + `du` on data dir | Capacity planning before passage |
| Filesystem free space | `df` per mount | Especially Obsidian vault partition |
| Network: hotspot clients, link quality | `iw`, `nmcli` | Phone-tether failures, client drops |
| Battery voltage trend | SignalK (via BLE Victron pipeline) | Early warning regardless of process state |
| Engine state | SignalK propulsion paths | Cross-correlate with electrical load |
| GPS time discipline | chrony status, SignalK time | Time sync sanity offshore |

Each is a five-to-fifteen line function. The value is in the framework that runs them and correlates outputs.

---

## 8. Display-stack footprint context

Why mcdash on Tkinter rather than browser-served:

| Stack | Idle RAM (approx) | Long-run behaviour |
|---|---|---|
| Chromium + KIP / SignalK webapps | 600 MB – 1.5 GB | V8 + GPU process leaks, degrades over days |
| Tkinter + matplotlib | 30 – 60 MB | Bulletproof, instant startup, project-consistent |
| PyQt5 / PySide6 | 80 – 150 MB | Considered but rejected — would introduce a parallel GUI stack |

Tkinter is the right pick for pi-deck-tools because it is already the project's GUI toolkit and `VNCToolWindow` exists. The aesthetic ceiling is lower than Qt, but the operational ceiling is much higher.

---

## 9. Open design decisions

Items still to be settled before implementation begins:

1. **Anchor-state detection source.** Trust the Hoekins anchor plugin's SignalK key exclusively, or combine with a SOG threshold fallback (e.g. SOG <0.5 kn for >5 min)? Combined-with-priority probably correct; specific SignalK path to be confirmed.
2. **dbus-python vs pystemd vs subprocess for systemd interaction.** dbus is the right answer technically; subprocess is the cheapest to ship. Worth deciding once Phase 1 is sketched.
3. **mcdash layout.** Single-window dense panel, or tabbed (instruments / health / log)? Touch-first vs mouse/VNC?
4. **Where mcd publishes its status.** Options: HTTP endpoint, WS, Unix socket, or pushed into SignalK as a custom path. The SignalK-native approach is elegant but couples to SignalK uptime.
5. **Obsidian daily-summary format.** Plain markdown section in the existing daily note, or its own subfolder under `Logbook/`?

---

## 10. Adjacent work — SignalK → Obsidian logbook

A separate but related project also under discussion: a SignalK-driven boat logbook that writes periodic entries to Obsidian (hourly when anchored, every 10 min underway, plus manual free-text entries, with min/max from InfluxDB). This replaces LogbookKonni, which does not run under OpenCPN 5.12 or 5.14.

Mission Control and the logbook are independent but converge naturally:

- Both consume SignalK and InfluxDB
- Both write to the Obsidian vault
- mcd's boat-state detection (anchored/underway/dockside) is the same state the logbook needs

A clean factoring is: `shared/boat_state.py` provides the state detector, consumed by both mcd and the logbook tool. mcd does not own the logbook; the logbook does not own supervision.

---

## 11. Decision summary

Recommended starting position:

- **Build mcd first as a pure observer.** One shipped behaviour for Phase 1: daily Obsidian summary of system health. Run for 4–6 weeks underway and observe what actually breaks before adding any active policy.
- **Build mcdash as a minimal Tkinter window** extending `VNCToolWindow`, showing wind / SOG / depth / battery / service health badges. Subscribes to SignalK + mcd status endpoint.
- **Run both as systemd-managed services** (mcd as `Type=notify` with watchdog; mcdash as a user session service launched at desktop start).
- **Hold the line on what Mission Control is not** (§5). Scope discipline is the project's biggest enemy.

This proposal does not yet belong in ROADMAP. The intent of this document is to make the design discussion sticky across Claude sessions so the next conversation in this project can pick up coherently.

---

## Phase 2 — Alert Policy

Severity split agreed for Phase 2 alerting, implemented as a `severity` field
("critical" or "non-critical") on every `CheckResult`:

**Critical (audio + mcdash):**

- `pypilot`, `signalk`, `signalk_http`, `signalk_position`, `opencpn`,
  `lightdm`, `NetworkManager` down
- Any `ttyOP_*` device missing (`ttyOP_gps`, `ttyOP_ais`, `ttyOP_wind`,
  `ttyOP_comp`, `ttyOP_pp`)
- `throttle` non-zero
- `disk_space` > 85% used (a full disk can silently break SignalK logging,
  InfluxDB writes, and Obsidian summary writes all at once)

**Non-critical (mcdash only):**

- `pypilot_web`, `influxdb`, `ble-scanner`, `grafana-server`, `vncserver`,
  `ssh` down
- `ram` > 85%, `cpu` > 90% sustained
- `disk_space_data` > 85% used (see "Two-tier disk layout" note below)

Critical alerts trigger an audio alarm (`apps/alerts/audio.py`) in addition
to surfacing in mcdash. Non-critical issues surface in mcdash only — no
audio, no Obsidian-summary escalation beyond the normal daily table.

**Two-speed main loop:** critical checks are evaluated and re-alerted every
`MCD_ALERT_INTERVAL_SECONDS` (5s) so an ongoing outage keeps sounding until
cleared, while routine journald logging and the daily summary stay on the
slower `MCD_CHECK_INTERVAL_SECONDS` (60s) cadence. `CheckResult` has an
`alert_interval_seconds` field as a forward-compatible seam for a future
mcdash config UI to override alert cadence per check, but it is not yet
wired into the loop — every check currently uses the global default.

**Startup grace period:** mcd suppresses critical alerts for the first
`MCD_STARTUP_GRACE_SECONDS` (default 90s) after starting, since systemd's
`After=` ordering only guarantees a dependency has started, not that it has
finished initializing and is actually responding — observed directly during
reboot testing on 2026-06-19, where mcd briefly logged a false
`pypilot_web` alert transition before the service had finished starting.

**Xorg CPU tracking:** the `xorg_ram` check (`apps/checks/hardware.py:
check_xorg()`) now reports Xorg's summed CPU% alongside its RSS, not just
RSS. This is specifically to give mcd visibility into the "OpenCPN freezes
after display sleep" scenario from §1 — the one-core-saturated-for-a-minute
CPU spike that mcd previously had no way to observe.

**Two-tier disk layout:** the Pi has two separate disks watched at
different severities. OS and swap live on the SD card (`mmcblk0`, the root
filesystem `/`), watched as critical `disk_space`
(`apps/checks/hardware.py: check_disk_space()`) since a full root
filesystem can take down the OS itself. Application data — InfluxDB,
the Obsidian vault, etc. — lives on a separate NVMe drive mounted at
`/data`, watched as non-critical `disk_space_data`
(`check_disk_space_data()`) since it currently has substantial headroom
(34% used at initial measurement) and a full `/data` degrades
logging/Obsidian rather than threatening the OS.

**Obsidian-writer crash incident (2026-06-19/20):** an unhandled
`PermissionError` inside `obsidian_summary_path()`'s `mkdir()` call
crashed mcd in a tight restart loop overnight — each crash also
re-triggered the 90s startup grace period (`MCD_STARTUP_GRACE_SECONDS`),
degrading critical alerting far more than a missed daily summary alone
would have. Root cause: `/data/Obsidian/Openplotter` had somehow lost its
write bit (`dr-xr-xr-x` instead of `drwxr-xr-x`); fixed with
`chmod u+w`. Beyond the immediate permissions fix, this revealed that the
Obsidian-writing code paths had no defensive exception handling at all,
despite being explicitly non-critical/nice-to-have functionality.
`write_obsidian_summary()` and `log_critical_alert_transition()` are now
each wrapped in a broad `except Exception`, and `main()`'s call site for
`write_obsidian_summary()` has its own belt-and-suspenders try/except —
so a similar issue (or any other filesystem problem) degrades to a
logged error rather than crashing the daemon.

### Per-alert audio file naming convention

Each critical check has its own wav so the watch crew can identify the
failure by ear, without looking at a screen. Files live in
`assets/sounds/`, named `alert_<check_name>.wav` — e.g. `alert_pypilot.wav`,
`alert_signalk.wav`, `alert_ttyOP_gps.wav`. If a check-specific file is
missing, `apps/alerts/audio.py` falls back to `alert_default.wav`; if that
is also missing, it logs a warning and skips the alert rather than failing
the sweep.

`apps/alerts/generate_beeps.py` generates a placeholder set of these files
(standard-library only — `wave`/`struct`/`math`, no numpy) using distinct
beep patterns per failure class: rapid triple beeps for navigation-critical
services (pypilot, signalk, opencpn), double beeps for the display stack
(lightdm, NetworkManager) and ttyOP GPS/AIS, single beeps for ttyOP wind/
compass, and four rapid high-pitched beeps for `throttle` (hardware
distress). These are meant to be replaced with louder, more attention-
grabbing recordings once Phase 2 implementation starts in earnest.

### Audio stack: PipeWire, not raw ALSA

Discovered 2026-06-19 while testing critical alerts against music playback.
This Pi's audio stack is **PipeWire with PulseAudio compatibility**
(`pactl info` reports `Server Name: PulseAudio (on PipeWire 1.2.7)`), not
plain ALSA. This has two practical consequences for anything that needs to
play sound on this system:

1. **Use `paplay`, not `aplay`.** `aplay` talks to ALSA hardware devices
   directly and will fail with "Device or resource busy" if PipeWire (or
   another app such as Clementine) already holds the device. `paplay`
   goes through PipeWire's mixer, which correctly mixes multiple
   concurrent streams (alert + music) onto the same output.
2. **Explicit volume is required to be heard over other audio.** A bare
   `paplay file.wav` plays at a quiet default per-stream volume — audible
   in silence but easily masked by music or gqrx. `apps/alerts/audio.py`
   calls `paplay --volume=65536` (max) so alerts reliably cut through.
3. **`XDG_RUNTIME_DIR` must be set explicitly for systemd services.**
   PipeWire's per-user socket lives at `/run/user/<uid>/pulse/native`.
   Interactive shells have `XDG_RUNTIME_DIR` set automatically by the
   login session; systemd services do not get this for free. Without it,
   `paplay` fails immediately with `Connection refused` — silently, since
   `apps/alerts/audio.py` only logs `FileNotFoundError`/timeout, not a
   non-zero exit code (a logging gap worth closing). `mcd.service` sets
   `Environment=XDG_RUNTIME_DIR=/run/user/1000` to fix this. If the `pi`
   user's UID ever changes, this must be updated to match (`id -u pi`).

This class of bug — alerts silently failing to play under systemd despite
working fine when run by hand from a terminal — is worth remembering for
any future Pi service that needs audio output (e.g. the anchor drag alarm).

### Critical alert transition log

Critical alert transitions (start/clear) are appended to
`Openplotter/alerts.md` as a running incident log, separate from the daily
system-health summary table. Each line records when a critical check went
from ok to failing (`ALERT START`) or from failing back to ok
(`ALERT CLEAR`), with a timestamp and the check's detail string.

State is tracked in memory only (`_previous_critical_state` in
`apps/mcd.py`) — a mcd restart resets the transition baseline, so a check
that was already failing before a restart will log a fresh `ALERT START`
on the next sweep after restart. This is expected behaviour, not a bug:
the alternative (persisting state across restarts) would require mcd to
own state, which §5 deliberately rules out.

---

## Document history

- 2026-06-18 — Initial draft, captured from design discussion in chat. Not yet ratified.
- 2026-06-18 — Added Phase 2 alert policy severity split.
- 2026-06-18 — Documented per-alert audio file naming convention and the
  generate_beeps.py placeholder generator.
- 2026-06-19 — Noted observed OpenCPN unresponsiveness when pypilot is
  stopped, flagged for Phase 3 auto-restart policy consideration.
- 2026-06-19 — Diagnosed and fixed critical alerts being inaudible: the
  Pi's actual audio stack is PipeWire (with PulseAudio compatibility),
  not raw ALSA. See "Audio stack" note under Phase 2 — Alert Policy.
- 2026-06-19 — Added critical alert transition log (Openplotter/alerts.md),
  noted in-memory-only state tracking and its restart implications.
- 2026-06-19 — Diagnosed high swap usage caused by default
  vm.swappiness=60; lowered to 10 and added a swap check to mcd.
- 2026-06-19 — Switched the pypilot Arduino Nano device check to the
  stable /dev/ttyOP_pp alias and reclassified it as critical, after
  testing showed unplugging it produced no alert under the prior
  non-critical severity.
- 2026-06-19 — Added Xorg CPU% tracking alongside its RSS (renamed
  check_xorg_memory() to check_xorg()), and added a critical disk_space
  check.
- 2026-06-19 — Added a second, non-critical disk_space_data check for the
  /data NVMe mount, documenting the two-tier SD-card/NVMe disk layout.
- 2026-06-20 — Fixed a production crash: an unhandled PermissionError in
  the daily Obsidian summary writer put mcd into a tight restart loop
  overnight. Wrapped all Obsidian-writing functions in broad exception
  handlers so a similar filesystem problem degrades to a logged error
  instead of crashing the daemon.
