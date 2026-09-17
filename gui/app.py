"""Main DroidForge GUI window.

Three tabs:
    Devices — see what's connected, refresh
    Test    — pick device, install APK, live logcat with crash flagging
    Logs    — open past session log files

Engine state is constructed once and passed to each tab so they share
the same AdbClient/EmulatorClient instances (and thus the same located
SDK binaries).
"""

from __future__ import annotations

import customtkinter as ctk

from droidforge import crash_logger
from droidforge.adb import AdbClient, AdbError
from droidforge.emulator import EmulatorClient
from droidforge.screen import ScreenMirror
from droidforge.sdk_paths import diagnose, locate

from .tabs.devices_tab import DevicesTab
from .tabs.logs_tab import LogsTab
from .tabs.test_tab import TestTab

_WINDOW_W = 1100
_WINDOW_H = 720


class DroidForgeApp(ctk.CTk):
    """Top-level window. Owns engine handles and tab container."""

    def __init__(self) -> None:
        super().__init__()
        self.title("DroidForge")
        self.geometry(f"{_WINDOW_W}x{_WINDOW_H}")
        self.minsize(800, 500)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # --- Engine handles ---
        self.paths = locate()
        try:
            self.adb_client = AdbClient(self.paths)
        except AdbError:
            self.adb_client = None
        self.emu_client = EmulatorClient(self.paths)
        self.screen_mirror = ScreenMirror()

        # --- Layout ---
        self._build_header()
        self._build_tabs()
        self._build_status_bar()

        # On first launch, surface SDK issues via status bar.
        for issue in diagnose(self.paths):
            self.log(f"[setup] {issue}")

    # ---------- layout ----------

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, height=48, corner_radius=0)
        bar.pack(side="top", fill="x")
        title = ctk.CTkLabel(
            bar,
            text="DroidForge",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        title.pack(side="left", padx=16, pady=8)
        sub = ctk.CTkLabel(
            bar,
            text="Local Android testing engine",
            text_color=("gray60", "gray60"),
        )
        sub.pack(side="left", padx=4, pady=8)

    def _build_tabs(self) -> None:
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(8, 4))
        self.tabs.add("Devices")
        self.tabs.add("Test")
        self.tabs.add("Logs")

        self.devices_tab = DevicesTab(self.tabs.tab("Devices"), app=self)
        self.devices_tab.pack(fill="both", expand=True)

        self.test_tab = TestTab(self.tabs.tab("Test"), app=self)
        self.test_tab.pack(fill="both", expand=True)

        self.logs_tab = LogsTab(self.tabs.tab("Logs"), app=self)
        self.logs_tab.pack(fill="both", expand=True)

        # Devices tab is the natural opener.
        self.tabs.set("Devices")

    def _build_status_bar(self) -> None:
        self.status_frame = ctk.CTkFrame(self, height=28, corner_radius=0)
        self.status_frame.pack(side="bottom", fill="x")
        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="ready",
            anchor="w",
            text_color=("gray60", "gray60"),
        )
        self.status_label.pack(side="left", padx=12, pady=4, fill="x", expand=True)

    # ---------- shared helpers ----------

    def log(self, message: str) -> None:
        """One-line app log → status bar. Tabs call this for global feedback."""
        self.status_label.configure(text=message)


def launch() -> None:
    """Public entry point used by cli.py gui."""
    crash_logger.install()
    app = DroidForgeApp()
    app.mainloop()


if __name__ == "__main__":
    launch()
