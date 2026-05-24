# AGENTS.md

## Purpose
This file provides essential instructions and conventions for AI coding agents working in the pi-deck-tools repository. It summarizes project structure, build/test commands, and key development practices. For detailed documentation, see the linked files below.

---

## Project Overview
- **Type:** Python/tkinter utility tools for Raspberry Pi, launched via OpenCPN Launcher Plugin.
- **Main entry scripts:** All tools are in the `apps/` directory. Launch via `launch_pi_app.sh`.
- **Shared code:** Common modules are in `shared/`.
- **Data/config:** See `data/` for manifests and job configs.

## Key Conventions
- Always use the project Python virtual environment (`.venv`) when running or developing tools.
- All GUIs are tkinter-based and require an X display (typically via VNC).
- Do not force the `DISPLAY` variable unless necessary (see [quick_start_links.md](docs/quick_start_links.md)).
- Use `launch_pi_app.sh <toolname>` to run apps as the launcher does.
- All requirements are in [requirements.txt](requirements.txt). Use `pip install -r requirements.txt` inside the venv.
- Use [Black](https://black.readthedocs.io/) for code formatting. Run `black .` to auto-format all Python files.

## Build/Test/Run
- **Create venv:** `bash setup_pi_venv.sh` (on Pi)
- **Install deps:** `pip install -r requirements.txt`
- **Run tool:** `./launch_pi_app.sh <toolname>`
- **Test display:** `echo $DISPLAY`

## Documentation Links
- [README.md](README.md): Project summary, hardware/software stack, tool list
- [docs/quick_start_links.md](docs/quick_start_links.md): Quick start, venv, display tips
- [docs/opencpn_launcher_setup.md](docs/opencpn_launcher_setup.md): OpenCPN Launcher Plugin setup
- [docs/signalk_api_notes.md](docs/signalk_api_notes.md): Signal K API usage

## Agent Guidance
- Link to documentation rather than duplicating content.
- Follow the conventions above for launching, formatting, and environment setup.
- If unsure, ask the user for clarification on Pi-specific or OpenCPN-specific details.
