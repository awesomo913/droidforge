"""Logs tab — browse session log files saved under logs/.

Click a file → opens with the OS default text editor. Refresh button
re-scans the log dir (sorted newest first).
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

if TYPE_CHECKING:
    from gui.app import DroidForgeApp

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


class LogsTab(ctk.CTkFrame):
    def __init__(self, parent, app: "DroidForgeApp") -> None:
        super().__init__(parent)
        self.app = app
        self._rows: list[ctk.CTkFrame] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=8, pady=8)
        ctk.CTkButton(top, text="Refresh", command=self.refresh, width=100).pack(side="left")
        ctk.CTkButton(
            top, text="Open log folder", command=self._open_folder, width=140,
        ).pack(side="left", padx=8)
        self.count_label = ctk.CTkLabel(top, text="", anchor="w")
        self.count_label.pack(side="left", padx=12)

        self.list_frame = ctk.CTkScrollableFrame(self, label_text="Past sessions")
        self.list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def refresh(self) -> None:
        for r in self._rows:
            r.destroy()
        self._rows.clear()

        if not _LOG_DIR.exists():
            ctk.CTkLabel(
                self.list_frame, text="No logs yet.", text_color=("gray60", "gray60"),
            ).pack(pady=24)
            self.count_label.configure(text="0 logs")
            return

        files = sorted(
            (f for f in _LOG_DIR.iterdir() if f.is_file() and f.suffix == ".log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        self.count_label.configure(text=f"{len(files)} log(s)")
        if not files:
            ctk.CTkLabel(
                self.list_frame, text="No session logs yet.", text_color=("gray60", "gray60"),
            ).pack(pady=24)
            return
        for f in files:
            row = self._make_row(f)
            row.pack(fill="x", padx=4, pady=2)
            self._rows.append(row)

    def _make_row(self, path: Path) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self.list_frame)
        ts = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = path.stat().st_size / 1024
        ctk.CTkLabel(
            row, text=path.name, font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=8)
        ctk.CTkLabel(row, text=ts, text_color=("gray60", "gray60")).pack(side="left", padx=4)
        ctk.CTkLabel(row, text=f"{size_kb:.1f} KB", text_color=("gray60", "gray60")).pack(
            side="left", padx=4,
        )
        ctk.CTkButton(
            row, text="Open", command=lambda p=path: self._open_file(p), width=80,
        ).pack(side="right", padx=8, pady=4)
        return row

    def _open_file(self, path: Path) -> None:
        try:
            os.startfile(str(path))  # Windows-only — fine for this engine
        except (AttributeError, OSError):
            # Cross-platform fallback for future portability.
            try:
                subprocess.Popen(["xdg-open", str(path)])
            except FileNotFoundError:
                subprocess.Popen(["open", str(path)])
        self.app.log(f"opened {path.name}")

    def _open_folder(self) -> None:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(_LOG_DIR))
        except (AttributeError, OSError):
            subprocess.Popen(["xdg-open", str(_LOG_DIR)])
        self.app.log(f"opened {_LOG_DIR}")
