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
