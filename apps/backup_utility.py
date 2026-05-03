#!/usr/bin/env python3
"""Backup Utility for pi-deck-tools.

Two-pane backup manager:
- Left pane: source files/folders to protect (path + notes)
- Right pane: backup outputs from previous runs (path + notes)

Features in v1:
- Add/remove sources and destinations with notes
- Manual run to copy sources into timestamped destination folders
- Optional interval auto-run scheduler
- JSON config persistence
"""

from __future__ import annotations

import json
import shutil
import sys
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.vnc_window import VNCToolWindow


class BackupUtility(VNCToolWindow):
    def __init__(self) -> None:
        super().__init__(title="Backup Utility", width=1280, height=760)

        self.config_path = Path(__file__).resolve().parent.parent / "data" / "backup_utility_jobs.json"
        self.sources: list[dict[str, str]] = []
        self.destinations: list[dict[str, str]] = []
        self.backup_records: list[dict[str, str]] = []

        self._auto_job_id: str | None = None
        self._next_run_dt: datetime | None = None

        self.auto_enabled_var = tk.BooleanVar(value=False)
        self.interval_min_var = tk.StringVar(value="60")
        self.status_var = tk.StringVar(value="Add sources and destinations, then run backup.")
        self.next_run_var = tk.StringVar(value="Auto: off")

        self._build_ui()
        self._load_config()
        self._refresh_sources_tree()
        self._refresh_destinations_tree()
        self._refresh_records_tree()

    def _build_ui(self) -> None:
        top = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        top.pack(fill=tk.X, pady=(0, 8))

        tk.Button(top, text="Run Backup Now", command=self.run_backup_now, bg="#1f618d", fg="white", padx=12).pack(side=tk.LEFT)
        tk.Checkbutton(
            top,
            text="Auto",
            variable=self.auto_enabled_var,
            command=self._toggle_auto,
            bg=self.COLOR_BG,
            fg=self.COLOR_FG,
            selectcolor=self.COLOR_BG,
            activebackground=self.COLOR_BG,
            activeforeground=self.COLOR_FG,
            font=self.font_normal,
        ).pack(side=tk.LEFT, padx=(14, 6))
        tk.Label(top, text="Every (min)", bg=self.COLOR_BG, fg=self.COLOR_FG, font=self.font_small).pack(side=tk.LEFT)
        tk.Entry(top, textvariable=self.interval_min_var, width=6, font=self.font_small).pack(side=tk.LEFT, padx=(6, 10))
        tk.Button(top, text="Save Config", command=self._save_config, bg="#34495e", fg="white", padx=10).pack(side=tk.LEFT)

        tk.Label(top, textvariable=self.next_run_var, bg=self.COLOR_BG, fg="#a8d8ff", font=self.font_small).pack(side=tk.RIGHT)

        body = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        body.pack(fill=tk.BOTH, expand=True)

        left = tk.LabelFrame(body, text="Sources (What To Backup)", bg=self.COLOR_BG, fg=self.COLOR_FG, font=self.font_normal)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        right = tk.LabelFrame(body, text="Backup Outputs (What Was Backed Up)", bg=self.COLOR_BG, fg=self.COLOR_FG, font=self.font_normal)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        self.sources_tree = ttk.Treeview(left, columns=("path", "note"), show="headings", height=16)
        self.sources_tree.heading("path", text="Source Path")
        self.sources_tree.heading("note", text="Note")
        self.sources_tree.column("path", width=420, anchor="w")
        self.sources_tree.column("note", width=220, anchor="w")
        self.sources_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        src_controls = tk.Frame(left, bg=self.COLOR_BG)
        src_controls.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Button(src_controls, text="Add File", command=self.add_source_file, bg="#2c7a7b", fg="white").pack(side=tk.LEFT)
        tk.Button(src_controls, text="Add Folder", command=self.add_source_folder, bg="#2c7a7b", fg="white").pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(src_controls, text="Edit Note", command=self.edit_source_note, bg="#7f8c8d", fg="white").pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(src_controls, text="Remove", command=self.remove_source, bg="#a93226", fg="white").pack(side=tk.LEFT, padx=(6, 0))

        dest_frame = tk.LabelFrame(left, text="Destinations", bg=self.COLOR_BG, fg=self.COLOR_FG, font=self.font_small)
        dest_frame.pack(fill=tk.BOTH, expand=False, padx=8, pady=(4, 8))

        self.dest_tree = ttk.Treeview(dest_frame, columns=("path", "note"), show="headings", height=6)
        self.dest_tree.heading("path", text="Destination Root")
        self.dest_tree.heading("note", text="Note")
        self.dest_tree.column("path", width=420, anchor="w")
        self.dest_tree.column("note", width=220, anchor="w")
        self.dest_tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        dst_controls = tk.Frame(dest_frame, bg=self.COLOR_BG)
        dst_controls.pack(fill=tk.X, padx=6, pady=(0, 6))
        tk.Button(dst_controls, text="Add Destination", command=self.add_destination, bg="#2d6a4f", fg="white").pack(side=tk.LEFT)
        tk.Button(dst_controls, text="Edit Note", command=self.edit_destination_note, bg="#7f8c8d", fg="white").pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(dst_controls, text="Remove", command=self.remove_destination, bg="#a93226", fg="white").pack(side=tk.LEFT, padx=(6, 0))

        self.records_tree = ttk.Treeview(
            right,
            columns=("time", "backup_path", "source_path", "note"),
            show="headings",
            height=24,
        )
        self.records_tree.heading("time", text="Time")
        self.records_tree.heading("backup_path", text="Backup Path")
        self.records_tree.heading("source_path", text="Source")
        self.records_tree.heading("note", text="Note")
        self.records_tree.column("time", width=140, anchor="w")
        self.records_tree.column("backup_path", width=360, anchor="w")
        self.records_tree.column("source_path", width=260, anchor="w")
        self.records_tree.column("note", width=180, anchor="w")
        self.records_tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        rec_controls = tk.Frame(right, bg=self.COLOR_BG)
        rec_controls.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Button(rec_controls, text="Open Backup Folder", command=self.open_selected_backup_folder, bg="#34495e", fg="white").pack(side=tk.LEFT)
        tk.Button(rec_controls, text="Clear Records", command=self.clear_records, bg="#a93226", fg="white").pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(
            self.content_frame,
            textvariable=self.status_var,
            bg=self.COLOR_BG,
            fg="#a8d8ff",
            font=self.font_small,
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(4, 0))

    def _load_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.status_var.set(f"Could not read config: {exc}")
            return

        self.sources = [
            {"path": str(i.get("path", "")).strip(), "note": str(i.get("note", "")).strip()}
            for i in payload.get("sources", [])
            if str(i.get("path", "")).strip()
        ]
        self.destinations = [
            {"path": str(i.get("path", "")).strip(), "note": str(i.get("note", "")).strip()}
            for i in payload.get("destinations", [])
            if str(i.get("path", "")).strip()
        ]
        self.backup_records = [
            {
                "time": str(i.get("time", "")),
                "backup_path": str(i.get("backup_path", "")),
                "source_path": str(i.get("source_path", "")),
                "note": str(i.get("note", "")),
            }
            for i in payload.get("backup_records", [])
            if str(i.get("backup_path", "")).strip()
        ]

        interval = payload.get("auto_interval_min", 60)
        self.interval_min_var.set(str(interval))
        auto_enabled = bool(payload.get("auto_enabled", False))
        self.auto_enabled_var.set(auto_enabled)
        if auto_enabled:
            self._start_auto_schedule()

    def _save_config(self) -> None:
        payload = {
            "sources": self.sources,
            "destinations": self.destinations,
            "backup_records": self.backup_records[-200:],
            "auto_enabled": bool(self.auto_enabled_var.get()),
            "auto_interval_min": self._interval_minutes(),
        }
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            self.show_error("Save Error", f"Could not save config:\n{exc}")
            return
        self.status_var.set(f"Saved config: {self.config_path}")

    def _interval_minutes(self) -> int:
        try:
            value = int(self.interval_min_var.get().strip())
            return max(1, value)
        except (ValueError, AttributeError):
            return 60

    def _toggle_auto(self) -> None:
        if self.auto_enabled_var.get():
            self._start_auto_schedule()
        else:
            self._stop_auto_schedule()
        self._save_config()

    def _start_auto_schedule(self) -> None:
        self._stop_auto_schedule()
        interval = self._interval_minutes()
        self._next_run_dt = datetime.now() + timedelta(minutes=interval)
        self.next_run_var.set(f"Auto: every {interval} min, next {self._next_run_dt.strftime('%Y-%m-%d %H:%M')}")
        self._auto_job_id = self.after(interval * 60 * 1000, self._auto_tick)

    def _stop_auto_schedule(self) -> None:
        if self._auto_job_id:
            self.after_cancel(self._auto_job_id)
            self._auto_job_id = None
        self._next_run_dt = None
        self.next_run_var.set("Auto: off")

    def _auto_tick(self) -> None:
        self._auto_job_id = None
        self.run_backup_now(is_auto=True)
        if self.auto_enabled_var.get():
            self._start_auto_schedule()

    def _ask_note(self, title: str, initial: str = "") -> str | None:
        win = tk.Toplevel(self)
        win.title(title)
        win.configure(bg=self.COLOR_BG)
        win.resizable(False, False)
        win.grab_set()

        tk.Label(win, text="Note", bg=self.COLOR_BG, fg=self.COLOR_FG, font=self.font_normal).pack(anchor="w", padx=12, pady=(10, 4))
        note_var = tk.StringVar(value=initial)
        tk.Entry(win, textvariable=note_var, width=56, font=self.font_small).pack(fill=tk.X, padx=12)

        result = {"value": None}

        def _ok() -> None:
            result["value"] = note_var.get().strip()
            win.destroy()

        def _cancel() -> None:
            win.destroy()

        btns = tk.Frame(win, bg=self.COLOR_BG)
        btns.pack(fill=tk.X, padx=12, pady=10)
        tk.Button(btns, text="OK", command=_ok, bg="#27ae60", fg="white", width=10).pack(side=tk.RIGHT)
        tk.Button(btns, text="Cancel", command=_cancel, bg="#7f8c8d", fg="white", width=10).pack(side=tk.RIGHT, padx=(0, 6))

        self.wait_window(win)
        return result["value"]

    def add_source_file(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Choose file to back up")
        if not path:
            return
        note = self._ask_note("Source File Note")
        if note is None:
            return
        self.sources.append({"path": path, "note": note})
        self._refresh_sources_tree()
        self._save_config()

    def add_source_folder(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Choose folder to back up")
        if not path:
            return
        note = self._ask_note("Source Folder Note")
        if note is None:
            return
        self.sources.append({"path": path, "note": note})
        self._refresh_sources_tree()
        self._save_config()

    def edit_source_note(self) -> None:
        selected = self.sources_tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        current = self.sources[idx]
        new_note = self._ask_note("Edit Source Note", current.get("note", ""))
        if new_note is None:
            return
        current["note"] = new_note
        self._refresh_sources_tree()
        self._save_config()

    def remove_source(self) -> None:
        selected = self.sources_tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        del self.sources[idx]
        self._refresh_sources_tree()
        self._save_config()

    def add_destination(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Choose destination root")
        if not path:
            return
        note = self._ask_note("Destination Note")
        if note is None:
            return
        self.destinations.append({"path": path, "note": note})
        self._refresh_destinations_tree()
        self._save_config()

    def edit_destination_note(self) -> None:
        selected = self.dest_tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        current = self.destinations[idx]
        new_note = self._ask_note("Edit Destination Note", current.get("note", ""))
        if new_note is None:
            return
        current["note"] = new_note
        self._refresh_destinations_tree()
        self._save_config()

    def remove_destination(self) -> None:
        selected = self.dest_tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        del self.destinations[idx]
        self._refresh_destinations_tree()
        self._save_config()

    def _refresh_sources_tree(self) -> None:
        self.sources_tree.delete(*self.sources_tree.get_children())
        for idx, item in enumerate(self.sources):
            self.sources_tree.insert("", tk.END, iid=str(idx), values=(item["path"], item.get("note", "")))

    def _refresh_destinations_tree(self) -> None:
        self.dest_tree.delete(*self.dest_tree.get_children())
        for idx, item in enumerate(self.destinations):
            self.dest_tree.insert("", tk.END, iid=str(idx), values=(item["path"], item.get("note", "")))

    def _refresh_records_tree(self) -> None:
        self.records_tree.delete(*self.records_tree.get_children())
        for idx, rec in enumerate(reversed(self.backup_records[-500:])):
            self.records_tree.insert(
                "",
                tk.END,
                iid=str(idx),
                values=(
                    rec.get("time", ""),
                    rec.get("backup_path", ""),
                    rec.get("source_path", ""),
                    rec.get("note", ""),
                ),
            )

    def _copy_source_to_snapshot(self, source: Path, snapshot_root: Path) -> Path:
        snapshot_root.mkdir(parents=True, exist_ok=True)
        target_name = source.name if source.name else source.anchor.replace(":", "")
        target = snapshot_root / target_name

        if source.is_file():
            shutil.copy2(source, target)
            return target

        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            return target

        raise FileNotFoundError(f"Source not found: {source}")

    def run_backup_now(self, is_auto: bool = False) -> None:
        if not self.sources:
            self.show_error("No Sources", "Add at least one source file/folder.")
            return
        if not self.destinations:
            self.show_error("No Destinations", "Add at least one destination folder.")
            return

        run_stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        created = 0
        errors: list[str] = []

        for dest in self.destinations:
            dest_path = Path(dest["path"]).expanduser()
            try:
                dest_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"Cannot create destination {dest_path}: {exc}")
                continue

            snapshot_root = dest_path / f"backup-{run_stamp}"

            for src in self.sources:
                source_path = Path(src["path"]).expanduser()
                try:
                    backup_path = self._copy_source_to_snapshot(source_path, snapshot_root)
                    self.backup_records.append(
                        {
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "backup_path": str(backup_path),
                            "source_path": str(source_path),
                            "note": src.get("note", "") or dest.get("note", ""),
                        }
                    )
                    created += 1
                except Exception as exc:
                    errors.append(f"{source_path} -> {snapshot_root}: {exc}")

        self.backup_records = self.backup_records[-1000:]
        self._refresh_records_tree()
        self._save_config()

        run_mode = "Auto" if is_auto else "Manual"
        if errors:
            first = errors[0]
            self.status_var.set(f"{run_mode} backup done with errors. Copied: {created}. First error: {first}")
            if not is_auto:
                messagebox.showwarning("Backup Completed With Errors", "\n".join(errors[:8]))
            return

        self.status_var.set(f"{run_mode} backup complete. Copied {created} item(s) into timestamped backup folders.")

    def clear_records(self) -> None:
        if not messagebox.askyesno("Clear Records", "Clear backup output history records?", parent=self):
            return
        self.backup_records.clear()
        self._refresh_records_tree()
        self._save_config()

    def open_selected_backup_folder(self) -> None:
        selected = self.records_tree.selection()
        if not selected:
            return

        values = self.records_tree.item(selected[0], "values")
        if not values:
            return
        backup_path = Path(str(values[1]))
        target = backup_path.parent if backup_path.exists() else backup_path

        self.show_info("Backup Path", str(target))


def main() -> None:
    app = BackupUtility()
    app.mainloop()


if __name__ == "__main__":
    main()
