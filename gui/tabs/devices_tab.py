"""Devices tab — lists adb-connected devices, refresh button.

Selecting a row sets `app.selected_serial` so the Test tab knows which
device to target.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import customtkinter as ctk

from droidforge.adb import Device

if TYPE_CHECKING:
    from gui.app import DroidForgeApp


class DevicesTab(ctk.CTkFrame):
    def __init__(self, parent, app: "DroidForgeApp") -> None:
        super().__init__(parent)
        self.app = app
        self._rows: list[ctk.CTkFrame] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        # Top bar: refresh + count
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=8, pady=8)
        ctk.CTkButton(top, text="Refresh", command=self.refresh, width=100).pack(side="left")
        self.count_label = ctk.CTkLabel(top, text="", anchor="w")
        self.count_label.pack(side="left", padx=12)

        # Scrollable device list
        self.list_frame = ctk.CTkScrollableFrame(self, label_text="Connected devices")
        self.list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Hint when empty
        self.hint_label = ctk.CTkLabel(
            self.list_frame,
            text=(
                "No devices.\n\n"
                "Plug in a phone with USB debugging enabled, OR launch an emulator.\n"
                "Then click Refresh."
            ),
            justify="left",
            text_color=("gray50", "gray50"),
        )

    def refresh(self) -> None:
        """Off-thread adb call → on-thread UI update."""
        if not self.app.adb_client:
            self._render([])
            self.app.log("adb not available — see doctor output")
            return
        self.app.log("refreshing devices...")

        def worker():
            devices = self.app.adb_client.list_devices()
            self.after(0, lambda: self._render(devices))

        threading.Thread(target=worker, daemon=True).start()

    def _render(self, devices: list[Device]) -> None:
        # Clear previous rows
        for r in self._rows:
            r.destroy()
        self._rows.clear()
        self.hint_label.pack_forget()

        self.count_label.configure(text=f"{len(devices)} device(s)")

        if not devices:
            self.hint_label.pack(pady=24)
            self.app.log("0 devices")
            return

        for d in devices:
            row = self._make_row(d)
            row.pack(fill="x", padx=4, pady=4)
            self._rows.append(row)
        self.app.log(f"found {len(devices)} device(s)")

    def _make_row(self, device: Device) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self.list_frame)
        kind = "emulator" if device.is_emulator else "physical"
        status_color = ("#2ecc71", "#27ae60") if device.online else ("#e67e22", "#d35400")

        dot = ctk.CTkLabel(row, text="●", text_color=status_color, width=20)
        dot.pack(side="left", padx=(8, 4))
        ctk.CTkLabel(
            row, text=device.serial, font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left", padx=4)
        ctk.CTkLabel(row, text=f"({kind})", text_color=("gray60", "gray60")).pack(side="left", padx=4)
        ctk.CTkLabel(row, text=device.state, text_color=("gray60", "gray60")).pack(side="left", padx=4)

        def select():
            self.app.selected_serial = device.serial
            self.app.log(f"selected {device.serial}")
            self.app.tabs.set("Test")
            # Refresh test tab so it picks up the selection.
            self.app.test_tab.on_device_selected(device.serial)

        ctk.CTkButton(row, text="Use this device", command=select, width=140).pack(
            side="right", padx=8, pady=6,
        )
        return row
