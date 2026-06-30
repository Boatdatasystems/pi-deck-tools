# Deploy

Deployment files for running pi-deck-tools daemons under systemd on the Pi.

## Mission Control daemon (mcd)

`mcd.service` runs `apps/mcd.py` as the always-on system health observer.
It starts after `signalk.service` and `network-online.target`, runs as user
`pi` from `/home/pi/pi-deck-tools`, and restarts automatically on failure.

### Install

On the Pi, from the repo root:

```bash
sudo deploy/install-mcd.sh
sudo systemctl start mcd.service
```

This copies `mcd.service` to `/etc/systemd/system/`, reloads systemd, and
enables the service to start on boot. The script does not start the service
itself — start it manually the first time so you can watch the logs.

### Logs

mcd logs to journald (via the project logger and `StandardOutput=journal` /
`StandardError=journal`) — there's no separate log file to tail. Follow it
live with:

```bash
journalctl -u mcd -f
```

### Notes

- The service is currently `Type=simple`. Once `python-systemd` is added to
  the venv, switch `mcd.service` to `Type=notify` so systemd's watchdog
  (`MCD_WATCHDOG_SEC` in `shared/config.py`) actually takes effect.
- Re-run `sudo deploy/install-mcd.sh` after editing `mcd.service` to pick up
  changes, then `sudo systemctl restart mcd.service`.

## Mission Control alert watcher (mcdash_watcher)

`apps/mcdash_watcher.py` polls mcd's status JSON
(`MCD_STATUS_JSON_PATH`) and pops up an always-on-top alert window when a
new critical failure appears. Unlike mcd, this needs a display — it runs
inside the Pi's desktop (X) session via XDG autostart, not as a headless
systemd service.

### Install

```bash
mkdir -p ~/.config/autostart
cp deploy/mcdash-watcher.desktop ~/.config/autostart/
```

It will start automatically on the next desktop login. To start it
immediately without logging out:

```bash
/home/pi/pi-deck-tools/.venv/bin/python3 apps/mcdash_watcher.py &
```

### Notes

- `deploy/mcdash-watcher.desktop` is the version-controlled source of
  truth; `~/.config/autostart/mcdash-watcher.desktop` (outside the
  project tree, per the XDG autostart spec) is just a copy of it. Re-copy
  after editing.
- Poll interval is `MCDASH_WATCHER_POLL_SECONDS` in `shared/config.py`,
  independent of mcd's own alert cadence.

## Mission Control web dashboard (mcdash_web)

`mcdash-web.service` runs `apps/mcdash_web.py`, a read-only Flask web server
on port 8765 that serves mcd's current status to any browser on the boat's
hotspot network. No JavaScript, no authentication — open `http://10.42.0.1:8765/`
from a phone, tablet, or laptop and see the same check data as mcdash_tk's
Overview tab.

### Install

On the Pi, from the repo root:

```bash
sudo cp deploy/mcdash-web.service /etc/systemd/system/mcdash-web.service
sudo systemctl daemon-reload
sudo systemctl enable mcdash-web.service
sudo systemctl start mcdash-web.service
```

Start it manually the first time so you can watch the logs.

### Logs

```bash
journalctl -u mcdash-web -f
```

### Notes

- Port 8765 is hardcoded in `apps/mcdash_web.py` (constant `PORT`). Change it
  there and re-copy the service file if something else claims that port.
- The service has `After=mcd.service` but does not `Require=` it — mcdash_web
  starts independently and shows a "data not available" page gracefully if mcd
  hasn't written its first snapshot yet.
- No `XDG_RUNTIME_DIR` needed — this is a headless web server, no audio output.

---

## SignalK notification alarm daemon (anchor_alarm)

`anchor_alarm.service` runs `apps/anchor_alarm.py`, watching SignalK
notification paths (anchor drag today — see
`SIGNALK_NOTIFICATION_WATCHES` in `shared/config.py`) and sounding an
audible alert when one fires. It starts after `signalk.service` and
`network-online.target`, runs as user `pi` from
`/home/pi/pi-deck-tools`, and restarts automatically on failure — same
structure as `mcd.service`, but an independent daemon: the two don't
depend on each other.

### Install

On the Pi, from the repo root:

```bash
sudo cp deploy/anchor_alarm.service /etc/systemd/system/anchor_alarm.service
sudo systemctl daemon-reload
sudo systemctl enable anchor_alarm.service
sudo systemctl start anchor_alarm.service
```

Start it manually the first time so you can watch the logs.

### Logs

anchor_alarm logs to journald (via the project logger and
`StandardOutput=journal` / `StandardError=journal`) — there's no
separate log file to tail. Follow it live with:

```bash
journalctl -u anchor_alarm -f
```

### Notes

- The service is currently `Type=simple`. Once `python-systemd` is added
  to the venv, switch `anchor_alarm.service` to `Type=notify` so
  systemd's watchdog actually takes effect.
- Re-run the install commands above after editing `anchor_alarm.service`
  to pick up changes, then `sudo systemctl restart anchor_alarm.service`.
