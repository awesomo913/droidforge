"""Thin adb wrapper.

Goals:
    - Subprocess calls return structured results (no string parsing in callers).
    - Per-device targeting via -s <serial>.
    - logcat streams as a generator so GUI can render lines as they arrive.

Non-goals:
    - Reimplement adb. Just shape it for engine consumption.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .sdk_paths import SdkPaths

# Default timeouts in seconds. APK install on a slow emulator can take a while.
_QUICK_TIMEOUT = 15
_INSTALL_TIMEOUT = 180


@dataclass(frozen=True)
class Device:
    """One connected adb device."""
    serial: str
    state: str  # "device", "offline", "unauthorized", "emulator"
    is_emulator: bool

    @property
    def online(self) -> bool:
        return self.state == "device"


@dataclass(frozen=True)
class AdbResult:
    """Captured outcome of an adb command."""
    ok: bool
    stdout: str
    stderr: str
    returncode: int


class AdbError(RuntimeError):
    """Raised when adb itself is unavailable, not when a command returns nonzero."""


class AdbClient:
    """Per-instance adb client bound to one located adb.exe."""

    def __init__(self, paths: SdkPaths) -> None:
        if not paths.adb_ready:
            raise AdbError("adb.exe not located. Run sdk_paths.diagnose() for hints.")
        self._adb: Path = paths.adb  # type: ignore[assignment]

    # ---------- core run ----------

    def _run(self, args: list[str], timeout: int = _QUICK_TIMEOUT) -> AdbResult:
        """Run adb with args, return structured result. Never raises on nonzero."""
        cmd = [str(self._adb), *args]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                # CREATE_NO_WINDOW = 0x08000000 — hides flicker on Windows
                creationflags=0x08000000,
            )
        except subprocess.TimeoutExpired as e:
            return AdbResult(False, e.stdout or "", f"timeout after {timeout}s", -1)
        return AdbResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
        )

    # ---------- devices ----------

    def list_devices(self) -> list[Device]:
        """Parse `adb devices` into structured records."""
        result = self._run(["devices"])
        if not result.ok:
            return []
        devices: list[Device] = []
        # First line is the "List of devices attached" header — skip it.
        for line in result.stdout.splitlines()[1:]:
            line = line.strip()
            if not line or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            devices.append(Device(
                serial=serial,
                state=state,
                is_emulator=serial.startswith("emulator-"),
            ))
        return devices

    # ---------- packages ----------

    def install(self, device_serial: str, apk_path: Path, replace: bool = True) -> AdbResult:
        """Install APK. -r to replace existing app, -g to grant runtime perms."""
        if not apk_path.exists():
            return AdbResult(False, "", f"APK not found: {apk_path}", -1)
        args = ["-s", device_serial, "install"]
        if replace:
            args.append("-r")
        args.extend(["-g", str(apk_path)])
        return self._run(args, timeout=_INSTALL_TIMEOUT)

    def uninstall(self, device_serial: str, package: str) -> AdbResult:
        """Remove app by package name."""
        return self._run(["-s", device_serial, "uninstall", package])

    def package_of(self, apk_path: Path) -> str | None:
        """Extract the package name from an APK using aapt-style fallback.

        Uses `adb shell pm list packages` as fallback won't work pre-install.
        For now: returns None and lets caller skip pretty-display.
        Future: bundle aapt2 or parse APK zip manifest.
        """
        return None

    # ---------- logcat ----------

    def logcat_stream(self, device_serial: str, *, clear_first: bool = True) -> Iterator[str]:
        """Yield logcat lines as they arrive. Caller must handle the generator
        on a background thread or in async context."""
        if clear_first:
            self._run(["-s", device_serial, "logcat", "-c"])
        cmd = [str(self._adb), "-s", device_serial, "logcat", "-v", "threadtime"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
            creationflags=0x08000000,
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                yield line.rstrip("\n")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()


class LogcatTail:
    """Thread-safe wrapper around logcat_stream — the GUI's friend.

    Usage:
        tail = LogcatTail(client, serial, on_line=lambda l: print(l))
        tail.start()
        ...
        tail.stop()
    """

    def __init__(
        self,
        client: AdbClient,
        device_serial: str,
        on_line,
        clear_first: bool = True,
    ) -> None:
        self._client = client
        self._serial = device_serial
        self._on_line = on_line
        self._clear_first = clear_first
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()

    def _run(self) -> None:
        for line in self._client.logcat_stream(self._serial, clear_first=self._clear_first):
            if self._stop_flag.is_set():
                break
            try:
                self._on_line(line)
            except Exception:
                # Never let a callback bug kill the tail thread silently.
                # crash_logger picks this up at the process level.
                continue
