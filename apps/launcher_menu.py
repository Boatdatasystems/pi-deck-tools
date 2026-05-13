#!/usr/bin/env python3
"""
Launcher Menu for pi-deck-tools.

Single OpenCPN entrypoint that discovers app scripts in apps/ and launches them.
Supports optional display overrides from data/launcher_manifest.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.vnc_window import VNCToolWindow


@dataclass
class AppEntry:
    script_name: str
    display_name: str
    order: int = 1000
    hidden: bool = False
    description: str = ""


class LauncherMenu(VNCToolWindow):
    def __init__(self) -> None:
        super().__init__(title="pi-deck-tools Launcher", width=900, height=620)
        self.apps_dir = Path(__file__).resolve().parent
        self.repo_root = self.apps_dir.parent
        self.manifest_path = self.repo_root / "data" / "launcher_manifest.json"

        self.status_var = tk.StringVar(value="Ready")
        self._buttons_frame: tk.Frame | None = None

        self._build_ui()
        self.reload_apps()

    def _build_ui(self) -> None:
        top = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        top.pack(fill=tk.X, pady=(0, 8))

        tk.Label(
            top,
            text="App Dashboard",
            font=self.font_large,
            bg=self.COLOR_BG,
            fg=self.COLOR_FG,
        ).pack(side=tk.LEFT)

        tk.Button(
            top,
            text="Reload",
            command=self.reload_apps,
            bg="#34495e",
            fg="white",
            padx=12,
            pady=6,
        ).pack(side=tk.RIGHT)

        tk.Label(
            self.content_frame,
            text="Auto-discovers scripts in apps/. Optional overrides: data/launcher_manifest.json",
            font=self.font_small,
            bg=self.COLOR_BG,
            fg="#a8d8ff",
            anchor="w",
        ).pack(fill=tk.X, pady=(0, 8))

        container = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, bg=self.COLOR_BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._buttons_frame = tk.Frame(canvas, bg=self.COLOR_BG)
        window_id = canvas.create_window((0, 0), window=self._buttons_frame, anchor="nw")

        self._buttons_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(window_id, width=e.width),
        )

        tk.Label(
            self.content_frame,
            textvariable=self.status_var,
            font=self.font_small,
            bg=self.COLOR_BG,
            fg="#a8d8ff",
            anchor="w",
        ).pack(fill=tk.X, pady=(8, 0))

    def _load_manifest_overrides(self) -> tuple[dict[str, dict], set[str]]:
        if not self.manifest_path.exists():
            return {}, set()

        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            self.status_var.set(f"Manifest ignored: {exc}")
            return {}, set()

        app_rows = data.get("apps", []) if isinstance(data, dict) else []
        excludes = data.get("exclude", []) if isinstance(data, dict) else []

        overrides: dict[str, dict] = {}
        for row in app_rows:
            if not isinstance(row, dict):
                continue
            script = str(row.get("script", "")).strip()
            if script:
                overrides[script] = row

        exclude_set = {str(item).strip() for item in excludes if str(item).strip()}
        return overrides, exclude_set

    def _has_entrypoint(self, file_path: Path) -> bool:
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        return "if __name__ == \"__main__\"" in text

    def _discover_apps(self) -> list[AppEntry]:
        overrides, manifest_excludes = self._load_manifest_overrides()

        entries: list[AppEntry] = []
        for script_path in sorted(self.apps_dir.glob("*.py")):
            name = script_path.name

            if name == Path(__file__).name:
                continue
            if name.startswith("_"):
                continue
            if name in manifest_excludes:
                continue
            if not self._has_entrypoint(script_path):
                continue

            default_display = script_path.stem.replace("_", " ").title()
            row = overrides.get(name, {})

            entry = AppEntry(
                script_name=name,
                display_name=str(row.get("name", default_display)),
                order=int(row.get("order", 1000)),
                hidden=bool(row.get("hidden", False)),
                description=str(row.get("description", "")).strip(),
            )
            if not entry.hidden:
                entries.append(entry)

        entries.sort(key=lambda x: (x.order, x.display_name.lower()))
        return entries

    def _clear_buttons(self) -> None:
        if not self._buttons_frame:
            return
        for child in self._buttons_frame.winfo_children():
            child.destroy()

    def _launch_app(self, script_name: str) -> None:
        script_path = self.apps_dir / script_name
        if not script_path.exists():
            self.status_var.set(f"Missing script: {script_name}")
            return

        try:
            subprocess.Popen([sys.executable, str(script_path)], cwd=str(self.apps_dir))
            self.status_var.set(f"Launched: {script_name}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Launch Error", f"Could not launch {script_name}\n\n{exc}")
            self.status_var.set(f"Launch failed: {script_name}")

    def _render_buttons(self, entries: list[AppEntry]) -> None:
        self._clear_buttons()
        if not self._buttons_frame:
            return

        if not entries:
            tk.Label(
                self._buttons_frame,
                text="No runnable apps discovered in apps/",
                font=self.font_normal,
                bg=self.COLOR_BG,
                fg="#f4d03f",
                anchor="w",
            ).grid(row=0, column=0, padx=8, pady=8, sticky="w")
            return

        columns = 3
        for col in range(columns):
            self._buttons_frame.grid_columnconfigure(col, weight=1, uniform="apps")

        for idx, entry in enumerate(entries):
            row = idx // columns
            col = idx % columns

            card = tk.Frame(self._buttons_frame, bg="#34495e", bd=1, relief=tk.RIDGE)
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")

            tk.Label(
                card,
                text=entry.display_name,
                font=self.font_large,
                bg="#34495e",
                fg="white",
                wraplength=220,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=10, pady=(10, 2))

            description = entry.description or entry.script_name
            tk.Label(
                card,
                text=description,
                font=self.font_small,
                bg="#34495e",
                fg="#d5e7f7",
                wraplength=220,
                justify=tk.LEFT,
                anchor="w",
            ).pack(fill=tk.X, padx=10, pady=(0, 8))

            tk.Button(
                card,
                text="Launch",
                command=lambda s=entry.script_name: self._launch_app(s),
                bg="#27ae60",
                fg="white",
                padx=10,
                pady=8,
            ).pack(fill=tk.X, padx=10, pady=(0, 10))

    def reload_apps(self) -> None:
        entries = self._discover_apps()
        self._render_buttons(entries)
        self.status_var.set(f"Loaded {len(entries)} app(s)")


if __name__ == "__main__":
    app = LauncherMenu()
    app.mainloop()
