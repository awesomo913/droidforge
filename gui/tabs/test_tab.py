"""Test tab — the workhorse.

Pick device → optionally install APK → start session → live logcat panel
shows lines as they stream in. Crash badge pulses red when CrashDetector
fires. Stop button cleanly closes the session.

Also hosts the engine's three big actions:
    - Launch emulator (pick AVD, boot, auto-select)
    - Mirror screen (scrcpy in floating window)
    - Triage last crash (Claude API hypothesis + fix steps)
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from droidforge.emulator import EmulatorError
from droidforge.logcat import CrashEvent, Severity
from droidforge.screen import ScrcpyError
from droidforge.session import SessionConfig, TestSession

from gui.triage_dialog import TriageDialog

if TYPE_CHECKING:
    from gui.app import DroidForgeApp

# Cap how many lines stay in the live view to avoid 100MB textboxes.
_MAX_LIVE_LINES = 5000
# Drain the queue every N ms — balances UI smoothness vs CPU.
_DRAIN_INTERVAL_MS = 100
# How many recent log lines to ship to triage as context.
_TRIAGE_CONTEXT_LINES = 200


class TestTab(ctk.CTkFrame):
    def __init__(self, parent, app: "DroidForgeApp") -> None:
        super().__init__(parent)
        self.app = app
        self.session: TestSession | None = None
        self.serial: str | None = None
        self.apk_path: Path | None = None
        # Thread-safe pipe from logcat thread → tk thread.
        self._line_queue: queue.Queue[tuple[str, Severity | None]] = queue.Queue()
        self._line_count = 0
        self._crash_count = 0
        # Rolling buffer of recent raw lines (for triage context).
        self._recent_lines: deque[str] = deque(maxlen=_TRIAGE_CONTEXT_LINES)
        # Most recent CrashEvent — what the Triage button operates on.
        self._last_crash: CrashEvent | None = None
        self._build()
        self._schedule_drain()

    # ---------- layout ----------

    def _build(self) -> None:
        # --- Tools row: emulator launch, screen mirror, AI triage ---
        tools = ctk.CTkFrame(self)
        tools.pack(fill="x", padx=8, pady=(8, 4))

        ctk.CTkLabel(tools, text="AVD:", text_color=("gray60", "gray60")).pack(
            side="left", padx=(8, 4),
        )
        self.avd_combo = ctk.CTkComboBox(tools, values=["(none)"], width=200)
        self.avd_combo.pack(side="left", padx=4)
        ctk.CTkButton(
            tools, text="Refresh AVDs", command=self._refresh_avds, width=110,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            tools, text="Launch", command=self._launch_emulator, width=80,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            tools, text="Mirror screen", command=self._toggle_mirror, width=130,
        ).pack(side="left", padx=(16, 4))
        self.triage_btn = ctk.CTkButton(
            tools, text="Triage last crash",
            command=self._triage_last_crash, width=150, state="disabled",
        )
        self.triage_btn.pack(side="left", padx=4)

        self._refresh_avds()

        # --- Session control row ---
        top = ctk.CTkFrame(self)
        top.pack(fill="x", padx=8, pady=4)

        self.device_label = ctk.CTkLabel(top, text="No device selected", anchor="w")
        self.device_label.pack(side="left", padx=8)

        self.apk_btn = ctk.CTkButton(top, text="Choose APK...", command=self._choose_apk)
        self.apk_btn.pack(side="left", padx=8)
        self.apk_label = ctk.CTkLabel(top, text="(no APK — tail only)", text_color=("gray60", "gray60"))
        self.apk_label.pack(side="left", padx=4)

        self.start_btn = ctk.CTkButton(top, text="Start session", command=self._start, width=140)
        self.start_btn.pack(side="right", padx=4)
        self.stop_btn = ctk.CTkButton(
            top, text="Stop", command=self._stop, width=80, state="disabled",
        )
        self.stop_btn.pack(side="right", padx=4)

        # Crash badge
        badge_row = ctk.CTkFrame(self)
        badge_row.pack(fill="x", padx=8)
        self.crash_badge = ctk.CTkLabel(
            badge_row,
            text="0 crashes",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=("#2ecc71", "#27ae60"),
            corner_radius=6,
            padx=12, pady=4,
        )
        self.crash_badge.pack(side="left", padx=4, pady=4)
        self.lines_label = ctk.CTkLabel(badge_row, text="0 lines", text_color=("gray60", "gray60"))
        self.lines_label.pack(side="left", padx=12)

        # Live logcat textbox (read-only, monospace)
        self.log_box = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Consolas", size=11), wrap="none",
        )
        self.log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log_box.configure(state="disabled")
        # Color tags for severity
        self.log_box.tag_config("crit", foreground="#ff5555")
        self.log_box.tag_config("high", foreground="#ffaa55")

    # ---------- public hooks ----------

    def on_device_selected(self, serial: str) -> None:
        self.serial = serial
        self.device_label.configure(text=f"Device: {serial}")

    # ---------- handlers ----------

    def _choose_apk(self) -> None:
        path = filedialog.askopenfilename(
            title="Select APK",
            filetypes=[("Android APK", "*.apk"), ("All files", "*.*")],
        )
        if not path:
            return
        self.apk_path = Path(path)
        self.apk_label.configure(text=self.apk_path.name)

    def _start(self) -> None:
        if not self.serial:
            self.app.log("pick a device first (Devices tab)")
            return
        if self.session is not None:
            self.app.log("session already running — stop it first")
            return
        if not self.app.adb_client:
            self.app.log("adb unavailable")
            return

        # Reset live view
        self._line_count = 0
        self._crash_count = 0
        self._update_badge()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        cfg = SessionConfig(
            device_serial=self.serial,
            apk_path=self.apk_path,
            label="gui",
            on_log_line=self._enqueue_line,
            on_crash=self._enqueue_crash,
        )
        self.session = TestSession(self.app.adb_client, cfg)

        # Install (if any) is sync-ish on a thread so UI doesn't freeze.
        def worker():
            result = self.session.start()
            if result is not None and not result.ok:
                # Install failed — bail out, surface error.
                self.after(0, lambda: self._install_failed(result.stderr or result.stdout))
                return
            self.after(0, lambda: self.app.log(f"session started on {self.serial}"))

        threading.Thread(target=worker, daemon=True).start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

    def _install_failed(self, stderr: str) -> None:
        self.app.log(f"install failed: {stderr.strip()[:80]}")
        if self.session:
            self.session.stop()
            self.session = None
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def _stop(self) -> None:
        if self.session:
            self.session.stop()
            log_path = self.session.log_path
            self.session = None
            self.app.log(f"session stopped. log: {log_path}")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    # ---------- queue plumbing ----------

    def _enqueue_line(self, line: str) -> None:
        # Called from logcat thread. Don't touch tk widgets here.
        self._recent_lines.append(line)
        self._line_queue.put((line, None))

    def _enqueue_crash(self, event: CrashEvent) -> None:
        self._last_crash = event
        # Enable triage button on tk thread (deque/dataclass writes above
        # are atomic enough that we don't need locks for read-only use).
        self.after(0, lambda: self.triage_btn.configure(state="normal"))
        self._line_queue.put((
            f">>> CRASH {event.severity.value.upper()}: "
            f"{event.line.tag}: {event.line.message}",
            event.severity,
        ))

    def _schedule_drain(self) -> None:
        self.after(_DRAIN_INTERVAL_MS, self._drain)

    def _drain(self) -> None:
        """Pull queued lines onto the textbox in batches. Tk-thread only."""
        if self._line_queue.empty():
            self._schedule_drain()
            return
        self.log_box.configure(state="normal")
        drained = 0
        while drained < 200:  # cap per tick — keep UI responsive
            try:
                line, severity = self._line_queue.get_nowait()
            except queue.Empty:
                break
            self._line_count += 1
            tag = ()
            if severity == Severity.CRITICAL:
                tag = ("crit",)
                self._crash_count += 1
            elif severity == Severity.HIGH:
                tag = ("high",)
                self._crash_count += 1
            self.log_box.insert("end", line + "\n", tag)
            drained += 1
        # Trim if we exceed the cap.
        all_text = self.log_box.get("1.0", "end-1c")
        line_count = all_text.count("\n")
        if line_count > _MAX_LIVE_LINES:
            excess = line_count - _MAX_LIVE_LINES
            self.log_box.delete("1.0", f"{excess + 1}.0")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")
        self._update_badge()
        self._schedule_drain()

    # ---------- emulator / mirror / triage handlers ----------

    def _refresh_avds(self) -> None:
        avds = [a.name for a in self.app.emu_client.list_avds()]
        if not avds:
            self.avd_combo.configure(values=["(none)"])
            self.avd_combo.set("(none)")
            return
        self.avd_combo.configure(values=avds)
        self.avd_combo.set(avds[0])

    def _launch_emulator(self) -> None:
        avd = self.avd_combo.get()
        if avd == "(none)" or not avd:
            self.app.log("no AVD selected — refresh or create one in Android Studio")
            return
        if not self.app.adb_client:
            self.app.log("adb not available")
            return
        self.app.log(f"launching {avd}...")

        def worker() -> None:
            try:
                existing = {d.serial for d in self.app.adb_client.list_devices()}
                proc = self.app.emu_client.launch(avd)
            except EmulatorError as e:
                self.after(0, lambda: self.app.log(f"launch failed: {e}"))
                return
            new_serial = self.app.emu_client.wait_for_boot(
                self.app.adb_client, existing_serials=existing,
            )
            if new_serial is None:
                self.after(0, lambda: self.app.log("emulator boot timed out"))
                return
            self.app.emu_client.track_serial(new_serial, proc)
            self.after(0, lambda: self._on_boot_done(new_serial))

        threading.Thread(target=worker, daemon=True).start()

    def _on_boot_done(self, serial: str) -> None:
        self.serial = serial
        self.device_label.configure(text=f"Device: {serial}")
        self.app.selected_serial = serial
        self.app.log(f"emulator ready: {serial}")
        # Refresh Devices tab so the row appears there too.
        self.app.devices_tab.refresh()

    def _toggle_mirror(self) -> None:
        if not self.serial:
            self.app.log("pick a device first")
            return
        if not self.app.screen_mirror.available():
            self.app.log("scrcpy not bundled — see vendor/scrcpy/")
            return
        try:
            self.app.screen_mirror.start(self.serial)
            self.app.log(f"mirroring {self.serial} (close the scrcpy window to stop)")
        except ScrcpyError as e:
            self.app.log(str(e))

    def _triage_last_crash(self) -> None:
        if self._last_crash is None:
            self.app.log("no crash to triage yet")
            return
        # Snapshot the recent buffer at click time — list is owned by tk thread
        # while in this method, so plain copy is safe.
        context = list(self._recent_lines)
        TriageDialog(self.app, self._last_crash, context)

    def _update_badge(self) -> None:
        self.lines_label.configure(text=f"{self._line_count} lines")
        if self._crash_count == 0:
            self.crash_badge.configure(
                text="0 crashes",
                fg_color=("#2ecc71", "#27ae60"),
            )
        else:
            self.crash_badge.configure(
                text=f"{self._crash_count} crash(es)",
                fg_color=("#e74c3c", "#c0392b"),
            )
