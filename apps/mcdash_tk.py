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
from shared.config import MCD_STATUS_JSON_PATH
from shared.logger import get_logger
from shared.vnc_window import VNCToolWindow

logger = get_logger("mcdash_tk")

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
        top = tk.Frame(self.content_frame, bg=self.COLOR_BG)
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
            self.content_frame,
            textvariable=self.updated_var,
            font=self.font_small,
            bg=self.COLOR_BG,
            fg="#a8d8ff",
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        # --- Middle: master list ---
        tree_frame = tk.Frame(self.content_frame, bg=self.COLOR_BG)
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
        detail_frame = tk.Frame(self.content_frame, bg=self.COLOR_BG, bd=1, relief=tk.RIDGE)
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


if __name__ == "__main__":
    app = MissionControlDashboard()
    app.mainloop()
