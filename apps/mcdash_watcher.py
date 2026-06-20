#!/usr/bin/env python3
"""Mission Control Alert Watcher — mcdash_watcher.py

Small, always-running background app. Polls mcd's status JSON
(MCD_STATUS_JSON_PATH) for new critical failures and pops up an
always-on-top alert window when one occurs. Runs inside the Pi's X
session (it needs a display for popups) — launched via XDG autostart,
not as a headless systemd service like mcd. See deploy/mcdash-watcher.desktop
and docs/mission_control_design.md for the autostart convention.

Polling only, no GUI to interact with otherwise — there's no main
window, just background polling and occasional popups.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.config import MCD_STATUS_JSON_PATH, MCDASH_WATCHER_POLL_SECONDS
from shared.logger import get_logger

logger = get_logger("mcdash_watcher")

COLOR_BG = "#3a1414"
COLOR_FG = "#ecf0f1"
COLOR_ACCENT = "#e74c3c"

STATUS_PATH = Path(MCD_STATUS_JSON_PATH)
POLL_MS = MCDASH_WATCHER_POLL_SECONDS * 1000

# Set of check names currently shown in the last-displayed popup (or empty
# if no failure is currently being displayed). Used to decide whether a
# new poll result represents a genuinely new incident worth re-popping,
# rather than the same ongoing failure(s) the user already dismissed.
_last_shown_names: frozenset[str] = frozenset()

# Reference to the currently open popup, if any, so a newer/different
# failure set can replace it instead of stacking duplicate windows.
_popup: tk.Toplevel | None = None


def _read_status() -> dict | None:
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("mcd status file not found at %s; skipping poll", STATUS_PATH)
        return None
    except json.JSONDecodeError as exc:
        logger.warning("mcd status file at %s is invalid JSON: %s; skipping poll", STATUS_PATH, exc)
        return None


def _show_popup(root: tk.Tk, failing_checks: list[dict]) -> None:
    global _popup

    if _popup is not None and _popup.winfo_exists():
        _popup.destroy()

    popup = tk.Toplevel(root)
    _popup = popup
    popup.title("Mission Control — Critical Alert")
    popup.configure(bg=COLOR_BG)
    popup.resizable(False, False)
    popup.attributes("-topmost", True)

    width = 380
    tk.Label(
        popup,
        text=f"⚠ {len(failing_checks)} critical failure(s)",
        font=("Arial", 14, "bold"),
        bg=COLOR_BG,
        fg=COLOR_FG,
        anchor="w",
        wraplength=width - 20,
        justify=tk.LEFT,
    ).pack(fill=tk.X, padx=10, pady=(10, 4))

    for check in failing_checks:
        tk.Label(
            popup,
            text=f"{check.get('name', '?')}: {check.get('detail', '')}",
            font=("Arial", 11),
            bg=COLOR_BG,
            fg=COLOR_FG,
            anchor="w",
            wraplength=width - 20,
            justify=tk.LEFT,
        ).pack(fill=tk.X, padx=10, pady=2)

    tk.Button(
        popup,
        text="Dismiss",
        command=popup.destroy,
        bg=COLOR_ACCENT,
        fg="white",
        font=("Arial", 11, "bold"),
        padx=12,
        pady=4,
    ).pack(pady=(8, 10))

    # Size to content, then position in the top-right corner so it
    # doesn't block whatever else is on screen.
    popup.update_idletasks()
    height = popup.winfo_reqheight()
    screen_w = popup.winfo_screenwidth()
    x = screen_w - width - 20
    y = 20
    popup.geometry(f"{width}x{height}+{x}+{y}")


def check_for_alerts(root: tk.Tk) -> None:
    global _last_shown_names

    data = _read_status()
    if data is not None:
        summary = data.get("summary", {})
        critical_fail_count = summary.get("critical_fail_count", 0)
        checks = data.get("checks", [])
        failing_checks = [c for c in checks if c.get("severity") == "critical" and not c.get("ok")]
        current_names = frozenset(c.get("name", "") for c in failing_checks)

        if critical_fail_count and current_names:
            if current_names != _last_shown_names:
                _show_popup(root, failing_checks)
                _last_shown_names = current_names
            # else: same ongoing incident already shown/dismissed — don't re-pop.
        else:
            # No critical failures right now — reset so the next failure
            # (even of a previously-seen check) is treated as a new incident.
            _last_shown_names = frozenset()

    root.after(POLL_MS, check_for_alerts, root)


def main() -> None:
    root = tk.Tk()
    root.withdraw()  # no main window — background polling + occasional popups only
    root.after(POLL_MS, check_for_alerts, root)
    root.mainloop()


if __name__ == "__main__":
    main()
