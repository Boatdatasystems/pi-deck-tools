#!/usr/bin/env python3
"""Mission Control Dashboard — mcdash_tk.py

Tkinter viewer for mcd's status. Reads the JSON snapshot mcd writes to
MCD_STATUS_JSON_PATH (see apps/mcd.py: write_status_json()) and displays
it as a master/detail view. Manual refresh only — no auto-polling, by
design: open the app, see current state, click Refresh for an update.

Launched on demand from apps/launcher_menu.py, same as any other tool.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).parent.parent))
from apps.alert_overrides import load_overrides, save_overrides
from apps.alerts.audio import list_available_sounds, play_critical_alert
from shared.config import MCD_ALERT_INTERVAL_SECONDS, MCD_STATUS_JSON_PATH
from shared.logger import get_logger
from shared.vnc_window import VNCToolWindow

logger = get_logger("mcdash_tk")

DEFAULT_SOUND_LABEL = "(default)"

COLOR_OK = "#2ecc71"
COLOR_CRITICAL = "#e74c3c"
COLOR_WARN = "#f1c40f"


class MissionControlDashboard(VNCToolWindow):
    def __init__(self) -> None:
        super().__init__(title="Mission Control — Conachair", width=900, height=620)
        self.status_path = Path(MCD_STATUS_JSON_PATH)
        self._checks_by_iid: dict[str, dict] = {}

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.content_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        overview_frame = tk.Frame(notebook, bg=self.COLOR_BG)
        settings_frame = tk.Frame(notebook, bg=self.COLOR_BG)
        notebook.add(overview_frame, text="Overview")
        notebook.add(settings_frame, text="Settings")

        self._build_overview_tab(overview_frame)
        self._build_settings_tab(settings_frame)

    def _build_overview_tab(self, parent: tk.Frame) -> None:
        top = tk.Frame(parent, bg=self.COLOR_BG)
        top.pack(fill=tk.X, pady=(0, 4))

        self.summary_var = tk.StringVar(value="Loading...")
        self.summary_label = tk.Label(
            top,
            textvariable=self.summary_var,
            font=self.font_large,
            bg=self.COLOR_BG,
            fg=self.COLOR_FG,
            anchor="w",
        )
        self.summary_label.pack(side=tk.LEFT)

        tk.Button(
            top,
            text="Refresh",
            command=self.refresh,
            bg="#34495e",
            fg="white",
            padx=12,
            pady=6,
        ).pack(side=tk.RIGHT)

        self.updated_var = tk.StringVar(value="")
        tk.Label(
            parent,
            textvariable=self.updated_var,
            font=self.font_small,
            bg=self.COLOR_BG,
            fg="#a8d8ff",
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        # --- Middle: master list ---
        tree_frame = tk.Frame(parent, bg=self.COLOR_BG)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("status", "detail", "severity")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings")
        self.tree.heading("#0", text="Check")
        self.tree.heading("status", text="Status")
        self.tree.heading("detail", text="Detail")
        self.tree.heading("severity", text="Severity")
        self.tree.column("#0", width=220, anchor="w")
        self.tree.column("status", width=70, anchor="center")
        self.tree.column("detail", width=420, anchor="w")
        self.tree.column("severity", width=100, anchor="center")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.tag_configure("ok", foreground=COLOR_OK)
        self.tree.tag_configure("critical_fail", foreground=COLOR_CRITICAL)
        self.tree.tag_configure("noncritical_fail", foreground=COLOR_WARN)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # --- Bottom: detail panel ---
        detail_frame = tk.Frame(parent, bg=self.COLOR_BG, bd=1, relief=tk.RIDGE)
        detail_frame.pack(fill=tk.X, pady=(8, 0))

        self.detail_text = tk.Text(
            detail_frame,
            height=6,
            bg="#1c2833",
            fg=self.COLOR_FG,
            font=self.font_small,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        check = self._checks_by_iid.get(selection[0])
        if check is not None:
            self._show_detail(check)

    def _show_detail(self, check: dict) -> None:
        value = check.get("value")
        if isinstance(value, dict):
            value_str = json.dumps(value, indent=2)
        else:
            value_str = str(value)

        lines = [
            f"Name:     {check.get('name')}",
            f"Severity: {check.get('severity')}",
            f"Detail:   {check.get('detail')}",
            f"Value:    {value_str}",
            f"Time:     {check.get('ts')}",
        ]

        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, "\n".join(lines))
        self.detail_text.configure(state=tk.DISABLED)

    def _clear(self) -> None:
        self._checks_by_iid.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.configure(state=tk.DISABLED)

    def refresh(self) -> None:
        """Re-read MCD_STATUS_JSON_PATH and rebuild the view. Manual only —
        not called on a timer."""
        self._clear()

        try:
            data = json.loads(self.status_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.summary_var.set("mcd status file not found — is mcd.service running?")
            self.summary_label.configure(fg=COLOR_WARN)
            self.updated_var.set("")
            return
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse status JSON at %s: %s", self.status_path, exc)
            self.summary_var.set("mcd status file is unreadable (invalid JSON)")
            self.summary_label.configure(fg=COLOR_CRITICAL)
            self.updated_var.set("")
            return

        summary = data.get("summary", {})
        critical_fail_count = summary.get("critical_fail_count", 0)
        if critical_fail_count:
            self.summary_var.set(f"{critical_fail_count} critical failure(s)")
            self.summary_label.configure(fg=COLOR_CRITICAL)
        else:
            self.summary_var.set("All systems nominal")
            self.summary_label.configure(fg=COLOR_OK)

        updated_at = data.get("updated_at", "")
        self.updated_var.set(f"Last updated: {updated_at}" if updated_at else "")

        checks = data.get("checks", [])
        critical_checks = [c for c in checks if c.get("severity") == "critical"]
        noncritical_checks = [c for c in checks if c.get("severity") != "critical"]

        self._populate_group("Critical", critical_checks)
        self._populate_group("Non-critical", noncritical_checks)

        self._populate_settings(checks)

    def _populate_group(self, label: str, checks: list[dict]) -> None:
        group_id = self.tree.insert("", tk.END, text=f"{label} ({len(checks)})", open=True)
        for check in checks:
            ok = check.get("ok")
            severity = check.get("severity", "non-critical")
            if ok:
                tag = "ok"
            elif severity == "critical":
                tag = "critical_fail"
            else:
                tag = "noncritical_fail"

            iid = self.tree.insert(
                group_id,
                tk.END,
                text=check.get("name", ""),
                values=("●", check.get("detail", ""), severity),
                tags=(tag,),
            )
            self._checks_by_iid[iid] = check

    # ------------------------------------------------------------------
    # Settings tab — per-check alert overrides
    # ------------------------------------------------------------------

    def _build_settings_tab(self, parent: tk.Frame) -> None:
        tk.Label(
            parent,
            text="Per-check alert overrides",
            font=self.font_large,
            bg=self.COLOR_BG,
            fg=self.COLOR_FG,
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        scroll_container = tk.Frame(parent, bg=self.COLOR_BG)
        scroll_container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(scroll_container, bg=self.COLOR_BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(scroll_container, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._settings_rows_frame = tk.Frame(canvas, bg=self.COLOR_BG)
        window_id = canvas.create_window((0, 0), window=self._settings_rows_frame, anchor="nw")
        self._settings_rows_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(window_id, width=e.width),
        )

        bottom = tk.Frame(parent, bg=self.COLOR_BG)
        bottom.pack(fill=tk.X, pady=(8, 0))

        self.settings_status_var = tk.StringVar(value="")
        tk.Label(
            bottom,
            textvariable=self.settings_status_var,
            font=self.font_small,
            bg=self.COLOR_BG,
            fg="#a8d8ff",
        ).pack(side=tk.LEFT)

        tk.Button(
            bottom,
            text="Save",
            command=self._save_overrides,
            bg="#34495e",
            fg="white",
            padx=12,
            pady=6,
        ).pack(side=tk.RIGHT)

        self._setting_widgets: dict[str, dict] = {}

    def _populate_settings(self, checks: list[dict]) -> None:
        for child in self._settings_rows_frame.winfo_children():
            child.destroy()
        self._setting_widgets.clear()

        overrides = load_overrides()
        sound_options = [DEFAULT_SOUND_LABEL] + list_available_sounds()

        critical_checks = [c for c in checks if c.get("severity") == "critical"]
        noncritical_checks = [c for c in checks if c.get("severity") != "critical"]

        row = 0
        for label, group in (("Critical", critical_checks), ("Non-critical", noncritical_checks)):
            tk.Label(
                self._settings_rows_frame,
                text=f"{label} ({len(group)})",
                font=self.font_normal,
                bg=self.COLOR_BG,
                fg=self.COLOR_FG,
                anchor="w",
            ).grid(row=row, column=0, columnspan=6, sticky="w", padx=4, pady=(10, 2))
            row += 1

            for check in group:
                row = self._add_setting_row(row, check, overrides.get(check.get("name", ""), {}), sound_options)

    def _add_setting_row(self, row: int, check: dict, override: dict, sound_options: list[str]) -> int:
        name = check.get("name", "")
        default_severity = check.get("severity", "non-critical")

        tk.Label(
            self._settings_rows_frame,
            text=name,
            font=self.font_small,
            bg=self.COLOR_BG,
            fg=self.COLOR_FG,
            anchor="w",
            width=18,
        ).grid(row=row, column=0, sticky="w", padx=4, pady=2)

        enabled_var = tk.BooleanVar(value=bool(override.get("enabled", True)))
        tk.Checkbutton(
            self._settings_rows_frame,
            variable=enabled_var,
            bg=self.COLOR_BG,
            activebackground=self.COLOR_BG,
            selectcolor="#1c2833",
        ).grid(row=row, column=1, padx=4)

        severity_var = tk.StringVar(value=override.get("severity", default_severity))
        ttk.Combobox(
            self._settings_rows_frame,
            textvariable=severity_var,
            values=["critical", "non-critical"],
            width=12,
            state="readonly",
        ).grid(row=row, column=2, padx=4)

        interval_override = override.get("alert_interval_seconds")
        interval_var = tk.StringVar(value=str(interval_override) if interval_override is not None else "")
        tk.Entry(
            self._settings_rows_frame,
            textvariable=interval_var,
            width=6,
            bg="#1c2833",
            fg=self.COLOR_FG,
            insertbackground=self.COLOR_FG,
        ).grid(row=row, column=3, padx=(4, 2))
        tk.Label(
            self._settings_rows_frame,
            text=f"(default {MCD_ALERT_INTERVAL_SECONDS}s)",
            font=self.font_small,
            bg=self.COLOR_BG,
            fg="#7f8c8d",
            anchor="w",
        ).grid(row=row, column=4, sticky="w", padx=(0, 4))

        sound_var = tk.StringVar(value=override.get("sound_file", DEFAULT_SOUND_LABEL))
        ttk.Combobox(
            self._settings_rows_frame,
            textvariable=sound_var,
            values=sound_options,
            width=22,
            state="readonly",
        ).grid(row=row, column=5, padx=4)

        tk.Button(
            self._settings_rows_frame,
            text="▶ Play",
            command=lambda n=name, sv=sound_var: self._preview_sound(n, sv),
            bg="#34495e",
            fg="white",
            padx=6,
            pady=2,
        ).grid(row=row, column=6, padx=4)

        self._setting_widgets[name] = {
            "default_severity": default_severity,
            "enabled_var": enabled_var,
            "severity_var": severity_var,
            "interval_var": interval_var,
            "sound_var": sound_var,
        }
        return row + 1

    def _preview_sound(self, check_name: str, sound_var: tk.StringVar) -> None:
        sound = sound_var.get()
        sound_file = None if sound in ("", DEFAULT_SOUND_LABEL) else sound
        play_critical_alert(check_name, sound_file)

    def _save_overrides(self) -> None:
        overrides: dict[str, dict] = {}

        for name, widgets in self._setting_widgets.items():
            entry: dict = {}

            if not widgets["enabled_var"].get():
                entry["enabled"] = False

            severity = widgets["severity_var"].get()
            if severity != widgets["default_severity"]:
                entry["severity"] = severity

            interval_text = widgets["interval_var"].get().strip()
            if interval_text:
                try:
                    entry["alert_interval_seconds"] = int(interval_text)
                except ValueError:
                    logger.warning("Ignoring non-numeric alert interval '%s' for check '%s'", interval_text, name)

            sound = widgets["sound_var"].get()
            if sound and sound != DEFAULT_SOUND_LABEL:
                entry["sound_file"] = sound

            if entry:
                overrides[name] = entry

        try:
            save_overrides(overrides)
            self.settings_status_var.set("Saved")
        except OSError as exc:
            logger.error("Failed to save alert overrides: %s", exc, exc_info=True)
            self.settings_status_var.set(f"Save failed: {exc}")

        self.after(2000, lambda: self.settings_status_var.set(""))


if __name__ == "__main__":
    app = MissionControlDashboard()
    app.mainloop()
