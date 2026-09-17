"""Modal dialog showing AI triage stream for a CrashEvent.

Opens when user clicks "Triage" on a crash. Spawns a worker thread that
calls droidforge.triage.triage(), streams tokens into the textbox via
queue + .after() draining (same pattern as the live log panel).
"""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING

import customtkinter as ctk

from droidforge.logcat import CrashEvent
from droidforge.triage import TriageError, is_configured, triage

if TYPE_CHECKING:
    from gui.app import DroidForgeApp

_DRAIN_INTERVAL_MS = 80


class TriageDialog(ctk.CTkToplevel):
    """One-shot modal: streams Claude's triage response and lets you copy it."""

    def __init__(
        self,
        app: "DroidForgeApp",
        event: CrashEvent,
        context_lines: list[str],
    ) -> None:
        super().__init__(app)
        self.app = app
        self.event = event
        self.context_lines = context_lines
        self.title(f"AI Triage: {event.line.tag}")
        self.geometry("780x560")
        self._queue: queue.Queue[str] = queue.Queue()
        self._done = False
        self._build()
        if not is_configured():
            self._render_missing_key()
            return
        self._start_worker()
        self.after(_DRAIN_INTERVAL_MS, self._drain)

    def _build(self) -> None:
        header = ctk.CTkFrame(self)
        header.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(
            header,
            text=f"{self.event.severity.value.upper()}: {self.event.line.tag}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text=self.event.line.message[:120],
            text_color=("gray60", "gray60"),
        ).pack(side="left", padx=12)

        self.body = ctk.CTkTextbox(
            self, font=ctk.CTkFont(family="Consolas", size=12), wrap="word",
        )
        self.body.pack(fill="both", expand=True, padx=12, pady=6)

        footer = ctk.CTkFrame(self)
        footer.pack(fill="x", padx=12, pady=(6, 12))
        ctk.CTkButton(footer, text="Copy", command=self._copy, width=100).pack(side="left")
        ctk.CTkButton(footer, text="Close", command=self.destroy, width=100).pack(side="right")
        self.status = ctk.CTkLabel(
            footer, text="thinking...", text_color=("gray60", "gray60"),
        )
        self.status.pack(side="left", padx=12)

    def _render_missing_key(self) -> None:
        self.body.insert(
            "end",
            "ANTHROPIC_API_KEY is not set in your environment.\n\n"
            "To enable AI triage:\n"
            "  1. Get a key at https://console.anthropic.com\n"
            "  2. Set it: setx ANTHROPIC_API_KEY \"your-key\" (Windows)\n"
            "  3. Restart DroidForge\n",
        )
        self.body.configure(state="disabled")
        self.status.configure(text="API key missing")

    def _start_worker(self) -> None:
        def worker() -> None:
            try:
                result = triage(
                    self.event,
                    self.context_lines,
                    on_token=lambda s: self._queue.put(s),
                )
                summary = (
                    f"\n\n--- tokens: in={result.input_tokens} "
                    f"out={result.output_tokens} "
                    f"cache_read={result.cache_read_tokens} "
                    f"({'HIT' if result.cache_hit else 'miss'}) ---"
                )
                self._queue.put(summary)
                self._queue.put("__DONE__")
            except TriageError as e:
                self._queue.put(f"\n\n[ERROR] {e}\n")
                self._queue.put("__DONE__")
            except Exception as e:  # noqa: BLE001 - surface to user, don't crash
                self._queue.put(f"\n\n[UNEXPECTED] {e!r}\n")
                self._queue.put("__DONE__")

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self) -> None:
        if self._done:
            return
        drained = 0
        while drained < 64:
            try:
                chunk = self._queue.get_nowait()
            except queue.Empty:
                break
            if chunk == "__DONE__":
                self._done = True
                self.status.configure(text="done")
                return
            self.body.insert("end", chunk)
            self.body.see("end")
            drained += 1
        self.after(_DRAIN_INTERVAL_MS, self._drain)

    def _copy(self) -> None:
        text = self.body.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text="copied to clipboard")
