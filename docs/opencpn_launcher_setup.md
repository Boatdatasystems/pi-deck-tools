# OpenCPN Launcher Plugin Setup

## Overview

The [OpenCPN Launcher Plugin](https://opencpn-manuals.github.io/main/opencpn-plugins/launcher/docs/) lets you add custom buttons to OpenCPN's toolbar that run shell commands. We use it to launch Python/tkinter tools inside the VNC session.

## Prerequisites

- OpenCPN installed with the Launcher Plugin enabled
- Python 3 with `python3-tk` installed (`sudo apt install python3-tk`)
- VNC server running (tools open windows in the VNC display)

## Adding a Tool

1. In OpenCPN, go to **Options → Plugins → Launcher → Preferences**
2. Add a new entry:
   - **Label:** Short name shown on the toolbar button (e.g. `Grid Sq`)
   - **Command:** The shell command to run (see below)
   - **Icon:** Optional — point at a 32×32 PNG

### Command Template

```bash
/home/pi/pi-deck-tools/launch_pi_app.sh maidenhead
```

> Do not force `DISPLAY` unless needed. On some setups, OpenCPN already provides the correct display context and forcing `:0` breaks launch behavior.

## Tool Commands

| Tool | Command |
|---|---|
| Maidenhead Grid | `/home/pi/pi-deck-tools/launch_pi_app.sh maidenhead` |
| HiFiBerry Volume | `/home/pi/pi-deck-tools/launch_pi_app.sh hifiberry_volume` |
| Sun/Moon | `/home/pi/pi-deck-tools/launch_pi_app.sh sun_moon` |
| Passage Planning | `/home/pi/pi-deck-tools/launch_pi_app.sh passage_planning` |

If a specific display must be forced on your Pi, use:

```bash
PI_DECK_DISPLAY=:0 /home/pi/pi-deck-tools/launch_pi_app.sh maidenhead
```

## Notes

- Tools exit cleanly when their window is closed — they do not run in the background
- If a tool fails silently, run the command manually in a VNC terminal to see error output
- The Launcher Plugin supports an optional working directory setting — leave blank; tools resolve paths relative to their own location using `__file__`
