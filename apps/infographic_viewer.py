#!/usr/bin/env python3
"""
Infographic Viewer for pi-deck-tools

Displays all .png images in /data/infographics/ with a tree view of subdirectories.
Double-click a .png to view it in the right pane.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import os
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from shared.vnc_window import VNCToolWindow

ROOT_DIR = Path("/data/infographics/")

class InfographicViewer(VNCToolWindow):
    def __init__(self):
        super().__init__(title="Infographic Viewer", width=1100, height=700)
        self.selected_image = None
        self.image_label = None
        self.image_canvas = None
        self.tk_img = None
        self._build_ui()
        self._populate_tree()

    def _build_ui(self):
        main_frame = tk.Frame(self.content_frame, bg=self.COLOR_BG)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Treeview (left)
        tree_frame = tk.Frame(main_frame, bg=self.COLOR_BG)
        tree_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8), pady=4)
        self.tree = ttk.Treeview(tree_frame, show="tree")
        self.tree.pack(fill=tk.Y, expand=True)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # Image display (right)
        img_frame = tk.Frame(main_frame, bg=self.COLOR_BG)
        img_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.image_canvas = tk.Canvas(img_frame, bg="#222", highlightthickness=0)
        self.image_canvas.pack(fill=tk.BOTH, expand=True)

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._add_tree_nodes(ROOT_DIR, "")

    def _add_tree_nodes(self, path, parent):
        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception:
            return
        for entry in entries:
            if entry.is_dir():
                node = self.tree.insert(parent, "end", text=entry.name, open=False)
                self._add_tree_nodes(entry, node)
            elif entry.suffix.lower() == ".png":
                self.tree.insert(parent, "end", text=entry.name, values=[str(entry)], open=False)

    def _on_tree_double_click(self, event):
        item = self.tree.focus()
        if not item:
            return
        path_parts = []
        node = item
        while node:
            text = self.tree.item(node, "text")
            path_parts.insert(0, text)
            node = self.tree.parent(node)
        img_path = ROOT_DIR.joinpath(*path_parts)
        if img_path.is_file() and img_path.suffix.lower() == ".png":
            self._show_image(img_path)

    def _show_image(self, img_path):
        try:
            img = Image.open(img_path)
        except Exception as e:
            messagebox.showerror("Image Error", f"Could not open image:\n{img_path}\n\n{e}")
            return
        # Force update to get correct canvas size
        self.image_canvas.update_idletasks()
        canvas_w = self.image_canvas.winfo_width()
        canvas_h = self.image_canvas.winfo_height()
        if canvas_w < 10 or canvas_h < 10:
            self.after(100, lambda: self._show_image(img_path))
            return
        img.thumbnail((canvas_w, canvas_h), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(img)
        self.image_canvas.create_image(canvas_w//2, canvas_h//2, image=self.tk_img, anchor=tk.CENTER)
        self.image_canvas.config(scrollregion=self.image_canvas.bbox("all"))
        self.selected_image = img_path

if __name__ == "__main__":
    app = InfographicViewer()
    app.mainloop()
