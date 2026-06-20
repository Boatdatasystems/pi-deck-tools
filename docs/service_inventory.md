# Service Inventory — Conachair Pi

> **Purpose:** Definitive list of services that must run continuously aboard Conachair.
> Used by Mission Control daemon (mcd) to determine what to watch and how.
>
> *Last updated: 2026-06-18*

---

## Watch method key

| Method | Meaning |
|---|---|
| `systemctl` | `systemctl is-failed <unit>` — standard systemd health check |
| `psutil` | Watch by process name — not systemd-managed |
| `http` | Ping a local HTTP endpoint |
| `device` | Check presence of `/dev/serial/by-id/...` or similar path |

---

## Tier 1 — Offshore critical (must always be running)

Loss of any of these has immediate safety or navigational consequences.

| Service | systemd unit | Watch method | Notes |
|---|---|---|---|
| SignalK | `signalk.service` (socket-activated by `signalk.socket`) | `systemctl` + `http` | Data bus for everything. Watch service unit AND HTTP endpoint — socket active does not mean server healthy (see SignalK watch strategy below). |
| OpenCPN | OpenPlotter-managed, not a raw systemd unit | `psutil` — watch `opencpn` process | Halo Plus radar runs as plugin inside OpenCPN; no separate watch needed. |
| pypilot | `pypilot.service` | `systemctl` | Spawns ~9 worker processes; watch the parent unit, not individual PIDs. Communicates with motor controller via Arduino Nano on `/dev/ttyOP_pp` (stable OpenPlotter udev alias for the underlying `/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0` USB device). |
| pypilot web | `pypilot_web.service` | `systemctl` | Web UI on port 8000. Health proxy for overall pypilot reachability. |
| SSH | `ssh.service` | `systemctl` | Recovery path if display stack fails offshore. |
| NetworkManager | `NetworkManager.service` | `systemctl` | Hotspot / wifi / phone tether. |
| VNC server | `vncserver-x11-serviced.service` | `systemctl` | RealVNC commercial daemon. Spawns `vncserver-x11-core`, `vncagent`, `vncserverui`. Watch the parent service unit. |

**Time synchronisation note:** chrony is not installed. SignalK disciplines the system clock by calling `sudo date -s` from its GPS time plugin (observed in journal: `signalk-server` → `sudo date -u -s '...'`). There is no NTP fallback. See time-sync watch strategy below.

---

## Tier 2 — Data pipeline (should always be running)

Loss degrades data logging and telemetry but does not immediately endanger the vessel.

| Service | systemd unit | Watch method | Notes |
|---|---|---|---|
| InfluxDB | `influxdb.service` | `systemctl` | Time-series store; mcd trend queries and logbook min/max depend on this. |
| BLE scanner (Victron) | `ble-scanner.service` | `systemctl` + data freshness | Runs `/home/pi/ble_scanner.py`. Unit healthy ≠ data flowing — see BLE watch strategy below. |
| signalk-to-influxdb | Plugin inside SignalK | `http` (SignalK plugin status) | No separate unit. Healthy if SignalK and InfluxDB are both healthy. |
| Grafana | `grafana-server.service` | `systemctl` | Dashboard layer over InfluxDB. Not safety-critical but part of normal monitoring. |
| lightdm / X11 | `lightdm.service` | `systemctl` | Desktop session; VNC and touchscreen both depend on it. |

---

## Tier 3 — Useful but recoverable

Can be restarted manually without passage risk.

| Service | systemd unit | Watch method | Notes |
|---|---|---|---|
| GQRX / AIS decoder | manual / as-needed | `psutil` if running | DSC/AIS from IC-7000 via Signalink. Not always active — do not alert if absent. |

---

## Hardware presence checks

`/dev` node checks rather than systemd watches. Included in mcd Phase 1.

| Device | Path | Why |
|---|---|---|
| Arduino Nano (pypilot motor controller) | `/dev/ttyOP_pp` (stable OpenPlotter udev alias; underlying USB identifier is `/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0`) | CH340 USB-serial adapter. If this disappears, pypilot loses its motor controller — service may still show active while unable to steer. |
| GPS source | *to confirm — see outstanding* | Silent dropout loses position fix and time discipline (no chrony fallback). |
| AIS source | *to confirm — see outstanding* | Silent dropout loses collision-avoidance data. |

**Note on pypilot + Arduino:** pypilot's systemd unit may remain `active` even if the Arduino drops off USB, since pypilot handles reconnection internally. The device node check is the reliable signal for hardware presence. Cross-correlate: if `/dev/ttyOP_pp` disappears but `pypilot.service` is still active, that is an alert condition.

---

## Outstanding confirmations

- [x] SignalK unit name: `signalk.service` / `signalk.socket` ✓
- [x] VNC unit name: `vncserver-x11-serviced.service` ✓
- [x] chrony: not installed; SignalK is sole time source ✓
- [x] USB serial `/dev/ttyOP_pp` (alias for `usb-1a86_USB2.0-Serial-if00-port0`): Arduino Nano, pypilot motor controller ✓
- [ ] GPS source: how does GPS reach SignalK? (Bluetooth, internal UART, USB not yet plugged in?)
- [ ] AIS source: same question
- [ ] Signalink/IC-7000: connected to Pi at all, or standalone?
- [ ] Any other services visible in `sudo systemctl status` not listed above?

Suggested Pi commands to resolve:
```bash
curl -s http://localhost:3000/signalk/v1/api/vessels/self/navigation/position | python3 -m json.tool | grep -i source
cat ~/.signalk/settings.json | python3 -m json.tool | grep -E "type|device|host|port" | head -40
```

---

## Watch strategies

### SignalK

Two-layer check:

1. `systemctl is-failed signalk.service` — catches crashes and failed restarts
2. `GET http://localhost:3000/signalk/v1/api/` — catches degraded-but-running states

The socket (`signalk.socket`) being active only means port 3000 is listening. It does not confirm the Node server is healthy. Observed example (2026-06-18): process running, `findPluginsAndWebapps failed: fetch failed` in journal — systemd would report healthy, HTTP check would reveal the issue.

### Time synchronisation

No chrony. SignalK calls `sudo date -s` to set the system clock from GPS. mcd Phase 1 check:

```python
import datetime
from shared.signalk import get_sk_value

def system_time_sane() -> bool:
    """Returns False if system clock differs from GPS time (via SignalK) by more than 60s."""
    sk_time = get_sk_value("environment/time/value")  # confirm SK path
    if sk_time is None:
        return False
    gps_dt = datetime.datetime.fromisoformat(sk_time.replace("Z", "+00:00"))
    system_dt = datetime.datetime.now(datetime.timezone.utc)
    return abs((gps_dt - system_dt).total_seconds()) < 60
```

If SignalK is down, time discipline is lost entirely — no fallback. Worth alerting on.

### OpenCPN (psutil)

Not systemd-managed; launched by OpenPlotter at desktop startup.

```python
import psutil

def opencpn_running() -> bool:
    return any(p.name() == "opencpn" for p in psutil.process_iter(["name"]))
```

Alert condition: not running AND boat is underway. If dockside, absence is expected.
Boat-state context (from `shared/boat_state.py`, Phase 3) will make this smarter.

### BLE scanner (Victron)

Two checks:

1. `systemctl is-failed ble-scanner.service` — catches crashes
2. Data freshness: query SignalK for a recent Victron battery voltage timestamp. A running scanner that has lost BLE contact still shows `active` in systemd but data goes stale.

**Implemented 2026-06-20** (`apps/checks/http.py: check_ble_data_freshness()`):
queries `electrical/batteries/house/voltage` and compares its `timestamp`
against `now − MCD_BLE_DATA_MAX_AGE_SECONDS` (300s default). This anticipated
failure mode was confirmed in practice the same day: an `hci1-up.service`
restart left `ble-scanner.service` `active` with zero data flowing until
manually restarted — exactly the "unit healthy ≠ data flowing" gap this
check exists to catch. mcd now also attempts automatic recovery
(`apps/mcd.py: check_ble_recovery()`): on a stale reading, it runs
`sudo systemctl restart ble-scanner.service`, subject to a 10-minute
cooldown (`MCD_BLE_RESTART_COOLDOWN_SECONDS`) so a problem a restart can't
actually fix (e.g. hci1 itself down) doesn't turn into a restart loop.
This requires a passwordless sudo rule for the `pi` user — see
docs/mission_control_design.md, Phase 2 — Alert Policy, for the required
`/etc/sudoers.d/` entry, which has not yet been confirmed/added on the Pi.

### pypilot

Watch `pypilot.service` unit. The ~9 worker processes are children of the unit; systemd tracks them all. Also watch the Arduino Nano device node — pypilot may remain `active` in systemd while the motor controller hardware is disconnected. Consider also pinging pypilot's network interface (default port 23322) as a functional health check.
