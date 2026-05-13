#!/usr/bin/env python3
"""Backup Utility for pi-deck-tools.

Two-pane backup manager:
- Left pane: source files/folders to protect (path + notes)
- Right pane: backup outputs from previous runs (path + notes)

Features in v1:
- Add/remove sources and destinations with notes
- Manual run to copy sources into a rotating snapshot set (current + history)
- Optional interval auto-run scheduler
- JSON config persistence
"""

from __future__ import annotations

import json
from typing import Callable
import shutil
import stat
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.vnc_window import VNCToolWindow

APP_VERSION = "1.0.0"


class BackupUtility(VNCToolWindow):
    def __init__(self) -> None:
        super().__init__(title="Backup Utility", width=1280, height=760)
        self.resizable(True, True)
        self.minsize(980, 620)

        self.config_path = Path(__file__).resolve().parent.parent / "data" / "backup_utility_jobs.json"
        self.sources: list[dict[str, str]] = []
        self.destinations: list[dict[str, str]] = []
        self.backup_records: list[dict[str, str]] = []

        self._auto_job_id: str | None = None
        self._next_run_dt: datetime | None = None

        self.auto_enabled_var = tk.BooleanVar(value=False)
        self.interval_min_var = tk.StringVar(value="60")
        self.history_count_var = tk.StringVar(value="2")
        self.status_var = tk.StringVar(value="Add sources and destinations, then run backup.")
        self.next_run_var = tk.StringVar(value="Auto: off")
        self._progress_var = tk.IntVar(value=0)
        self._progress_label_var = tk.StringVar(value="")
        self._backup_running = False
        self._run_btn: tk.Button | None = None

        self._build_ui()
        self._load_config()
        self._refresh_sources_tree()
        self._refresh_destinations_tree()
        self._refresh_records_tree()

    def _build_ui(self) -> None:
        top = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        top.pack(fill=tk.X, pady=(0, 8))

        self._run_btn = tk.Button(top, text="Run Backup Now", command=self.run_backup_now, bg="#1f618d", fg="white", padx=12)
        self._run_btn.pack(side=tk.LEFT)
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
        tk.Label(top, text="History", bg=self.COLOR_BG, fg=self.COLOR_FG, font=self.font_small).pack(side=tk.LEFT)
        tk.Entry(top, textvariable=self.history_count_var, width=4, font=self.font_small).pack(side=tk.LEFT, padx=(6, 10))
        tk.Button(top, text="Save Config", command=self._save_config, bg="#34495e", fg="white", padx=10).pack(side=tk.LEFT)

        tk.Label(top, text=f"v{APP_VERSION}", bg=self.COLOR_BG, fg="#5d7d9a", font=self.font_small).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Label(top, textvariable=self.next_run_var, bg=self.COLOR_BG, fg="#a8d8ff", font=self.font_small).pack(side=tk.RIGHT)

        # Progress bar row — visible at top, always in view
        progress_frame = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        progress_frame.pack(fill=tk.X, pady=(0, 4))

        self._progress_bar = ttk.Progressbar(
            progress_frame, variable=self._progress_var, maximum=100, length=400
        )
        self._progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        tk.Label(
            progress_frame,
            textvariable=self._progress_label_var,
            bg=self.COLOR_BG,
            fg="#a8d8ff",
            font=self.font_small,
            anchor="w",
            width=22,
        ).pack(side=tk.LEFT)

        tk.Label(
            self.content_frame,
            textvariable=self.status_var,
            bg=self.COLOR_BG,
            fg="#a8d8ff",
            font=self.font_small,
            anchor="w",
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(0, 6))

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
        history_count = payload.get("history_count", 2)
        self.history_count_var.set(str(history_count))
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
            "history_count": self._history_count(),
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

    def _history_count(self) -> int:
        """How many previous snapshots to retain (not counting current)."""
        try:
            value = int(self.history_count_var.get().strip())
            return max(0, min(10, value))
        except (ValueError, AttributeError):
            return 2

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

    @staticmethod
    def _ignore_special_files(src: str, names: list[str]) -> list[str]:
        """Skip sockets, pipes, block/char devices — things like opencpn-ipc."""
        skipped = []
        for name in names:
            try:
                mode = Path(src, name).stat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
                    skipped.append(name)
            except OSError:
                skipped.append(name)
        return skipped

    @staticmethod
    def _count_copyable_files(source: Path) -> int:
        """Count regular files in source (skipping special files)."""
        if source.is_file():
            return 1
        total = 0
        for p in source.rglob("*"):
            try:
                mode = p.stat().st_mode
                if stat.S_ISREG(mode):
                    total += 1
            except OSError:
                pass
        return max(total, 1)

    def _copy_source_to_snapshot(
        self,
        source: Path,
        snapshot_root: Path,
        on_file_copied: "Callable[[], None] | None" = None,
    ) -> Path:
        snapshot_root.mkdir(parents=True, exist_ok=True)
        target_name = source.name if source.name else source.anchor.replace(":", "")
        target = snapshot_root / target_name

        def _copy_with_callback(src: str, dst: str) -> str:
            shutil.copy2(src, dst)
            if on_file_copied:
                on_file_copied()
            return dst

        if source.is_file():
            shutil.copy2(source, target)
            if on_file_copied:
                on_file_copied()
            return target

        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                source, target,
                ignore=self._ignore_special_files,
                copy_function=_copy_with_callback,
            )
            return target

        raise FileNotFoundError(f"Source not found: {source}")

    def _remove_path(self, path: Path) -> None:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    def _rotate_destination_snapshots(self, dest_path: Path, keep_previous: int) -> Path:
        """Rotate snapshots at destination and return writable 'current' snapshot path.

        Layout:
          current/         <- newest run
          previous-01/     <- prior run
          previous-02/ ... <- older runs up to configured history
        """
        current = dest_path / "current"

        if keep_previous <= 0:
            self._remove_path(current)
            current.mkdir(parents=True, exist_ok=True)
            return current

        oldest = dest_path / f"previous-{keep_previous:02d}"
        self._remove_path(oldest)

        for idx in range(keep_previous - 1, 0, -1):
            src = dest_path / f"previous-{idx:02d}"
            dst = dest_path / f"previous-{idx + 1:02d}"
            if src.exists():
                self._remove_path(dst)
                src.rename(dst)

        previous_01 = dest_path / "previous-01"
        if current.exists():
            self._remove_path(previous_01)
            current.rename(previous_01)

        current.mkdir(parents=True, exist_ok=True)
        return current

    def run_backup_now(self, is_auto: bool = False) -> None:
        if self._backup_running:
            return
        if not self.sources:
            self.show_error("No Sources", "Add at least one source file/folder.")
            return
        if not self.destinations:
            self.show_error("No Destinations", "Add at least one destination folder.")
            return

        # Count total files across all sources for progress tracking.
        total_files = sum(
            self._count_copyable_files(Path(src["path"]).expanduser())
            for src in self.sources
        ) * max(len(self.destinations), 1)
        total_files = max(total_files, 1)

        self._backup_running = True
        self._progress_var.set(0)
        self._progress_label_var.set("0 / 0 files")
        if self._run_btn:
            self._run_btn.config(state=tk.DISABLED)
        self.status_var.set("Backup running...")

        copied_count = [0]
        errors: list[str] = []
        new_records: list[dict] = []
        keep_previous = self._history_count()

        def _on_file_copied() -> None:
            copied_count[0] += 1
            pct = int(copied_count[0] * 100 / total_files)
            self.after(0, lambda p=pct, c=copied_count[0]: (
                self._progress_var.set(p),
                self._progress_label_var.set(f"{c} / {total_files} files"),
            ))

        def _worker() -> None:
            created = 0
            for dest in self.destinations:
                dest_path = Path(dest["path"]).expanduser()
                try:
                    dest_path.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    errors.append(f"Cannot create destination {dest_path}: {exc}")
                    continue

                try:
                    snapshot_root = self._rotate_destination_snapshots(dest_path, keep_previous)
                except Exception as exc:
                    errors.append(f"Cannot rotate snapshots at {dest_path}: {exc}")
                    continue

                for src in self.sources:
                    source_path = Path(src["path"]).expanduser()
                    try:
                        backup_path = self._copy_source_to_snapshot(
                            source_path, snapshot_root, on_file_copied=_on_file_copied
                        )
                        new_records.append(
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

            self.after(0, lambda: _finish(created))

        def _finish(created: int) -> None:
            self._backup_running = False
            if self._run_btn:
                self._run_btn.config(state=tk.NORMAL)
            self._progress_var.set(100)

            self.backup_records.extend(new_records)
            self.backup_records = self.backup_records[-1000:]
            self._refresh_records_tree()
            self._save_config()

            run_mode = "Auto" if is_auto else "Manual"
            if errors:
                first = errors[0]
                self._progress_label_var.set("Done (errors)")
                self.status_var.set(f"{run_mode} backup done with errors. Copied: {created}. First error: {first}")
                if not is_auto:
                    messagebox.showwarning("Backup Completed With Errors", "\n".join(errors[:8]))
                return

            self._progress_label_var.set(f"{copied_count[0]} files")
            self.status_var.set(
                f"{run_mode} backup complete. Copied {created} source(s) into 'current' snapshots "
                f"with {keep_previous} previous version(s) retained."
            )

        threading.Thread(target=_worker, daemon=True).start()

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
