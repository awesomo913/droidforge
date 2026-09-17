"""TestSession: stitch the pieces into one workflow.

A session represents: pick a device, optionally install an APK, tail
logcat, save logs to disk, fire callbacks on crashes. One session = one
test run. Multiple sessions can run on different devices in parallel.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .adb import AdbClient, AdbResult, LogcatTail
from .logcat import CrashDetector, CrashEvent

# Default log dir under repo root. GUI can override.
_DEFAULT_LOG_DIR = Path(__file__).parent.parent / "logs"


@dataclass
class SessionConfig:
    """All knobs for one test session."""
    device_serial: str
    apk_path: Path | None = None        # None = use already-installed app
    log_dir: Path = field(default_factory=lambda: _DEFAULT_LOG_DIR)
    label: str = ""                      # human tag for the log filename
    on_crash: Callable[[CrashEvent], None] | None = None
    on_log_line: Callable[[str], None] | None = None  # GUI live-feed hook


class TestSession:
    """One test run on one device. Owns its tail + log file."""

    def __init__(self, client: AdbClient, config: SessionConfig) -> None:
        self._client = client
        self._cfg = config
        self._tail: LogcatTail | None = None
        self._log_file = None
        self._lock = threading.Lock()
        self._crashes: list[CrashEvent] = []
        self.log_path: Path | None = None

    # ---------- lifecycle ----------

    def start(self) -> AdbResult | None:
        """Install (if APK provided) and begin logcat capture.

        Returns AdbResult of install, or None if no APK was set.
        """
        install_result: AdbResult | None = None
        if self._cfg.apk_path is not None:
            install_result = self._client.install(
                self._cfg.device_serial, self._cfg.apk_path,
            )
            if not install_result.ok:
                return install_result

        self._open_log_file()
        detector = CrashDetector(on_crash=self._handle_crash)
        self._tail = LogcatTail(
            client=self._client,
            device_serial=self._cfg.device_serial,
            on_line=self._handle_line(detector),
        )
        self._tail.start()
        return install_result

    def stop(self) -> None:
        """Stop tail, close log file."""
        if self._tail:
            self._tail.stop()
            self._tail = None
        with self._lock:
            if self._log_file:
                self._log_file.close()
                self._log_file = None

    # ---------- accessors ----------

    @property
    def crashes(self) -> list[CrashEvent]:
        return list(self._crashes)

    # ---------- internals ----------

    def _open_log_file(self) -> None:
        self._cfg.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        label = self._cfg.label or self._cfg.device_serial
        # Sanitize: serials may contain colons (e.g., 192.168.1.10:5555)
        safe_label = label.replace(":", "_").replace("/", "_")
        self.log_path = self._cfg.log_dir / f"session_{ts}_{safe_label}.log"
        self._log_file = self.log_path.open("w", encoding="utf-8", buffering=1)

    def _handle_line(self, detector: CrashDetector) -> Callable[[str], None]:
        """Build the on_line callback bound to this session's state."""
        def _on_line(line: str) -> None:
            with self._lock:
                if self._log_file:
                    self._log_file.write(line + "\n")
            detector.feed(line)
            if self._cfg.on_log_line:
                self._cfg.on_log_line(line)
        return _on_line

    def _handle_crash(self, event: CrashEvent) -> None:
        self._crashes.append(event)
        if self._cfg.on_crash:
            self._cfg.on_crash(event)
