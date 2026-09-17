"""AVD lifecycle: list / launch / kill emulator instances.

Handles the case where emulator package isn't installed (graceful empty
list, clear status). Caller queries `available()` first.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .adb import AdbClient
from .sdk_paths import SdkPaths

_LOG = logging.getLogger(__name__)
_BOOT_POLL_INTERVAL = 2.0
_BOOT_TIMEOUT_DEFAULT = 180.0

_LAUNCH_FLAGS_DEFAULT = (
    "-no-snapshot-save",  # don't pollute snapshot on every test session
    "-no-boot-anim",       # faster cold boot
)
_LIST_TIMEOUT = 10


@dataclass(frozen=True)
class AvdInfo:
    """One installed AVD."""
    name: str


class EmulatorError(RuntimeError):
    """Emulator not installed or AVD lookup failed."""


class EmulatorClient:
    """Manages AVDs via emulator.exe + tracks running instances we launched."""

    def __init__(self, paths: SdkPaths) -> None:
        self._paths = paths
        # Map serial -> Popen for each emulator we launched. Lets us kill them.
        self._launched: dict[str, subprocess.Popen[bytes]] = {}

    def available(self) -> bool:
        """Is emulator.exe present?"""
        return self._paths.emulator_ready

    def list_avds(self) -> list[AvdInfo]:
        """List installed AVD names. Empty list if emulator not installed."""
        if not self.available():
            return []
        emu: Path = self._paths.emulator  # type: ignore[assignment]
        try:
            proc = subprocess.run(
                [str(emu), "-list-avds"],
                capture_output=True,
                text=True,
                timeout=_LIST_TIMEOUT,
                creationflags=0x08000000,
            )
        except subprocess.TimeoutExpired:
            return []
        return [
            AvdInfo(name=line.strip())
            for line in proc.stdout.splitlines()
            if line.strip() and not line.startswith("INFO")
        ]

    def launch(self, avd_name: str, *, extra_flags: tuple[str, ...] = ()) -> subprocess.Popen[bytes]:
        """Spawn emulator for given AVD. Returns Popen handle for later kill.

        Caller must poll `adb devices` to know when boot completes —
        emulator.exe doesn't block on boot.
        """
        if not self.available():
            raise EmulatorError(
                "emulator.exe not installed. Install via Android Studio "
                "SDK Manager -> SDK Tools -> Android Emulator."
            )
        if avd_name not in {a.name for a in self.list_avds()}:
            raise EmulatorError(f"AVD '{avd_name}' not found.")

        emu: Path = self._paths.emulator  # type: ignore[assignment]
        args = [str(emu), "-avd", avd_name, *_LAUNCH_FLAGS_DEFAULT, *extra_flags]
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        # Serial isn't known until adb sees it. Caller polls adb.list_devices()
        # and when it sees a new emulator-XXXX, links it via track_serial().
        return proc

    def track_serial(self, serial: str, proc: subprocess.Popen[bytes]) -> None:
        """Associate a running emulator's serial with the launch Popen."""
        self._launched[serial] = proc

    def wait_for_boot(
        self,
        adb_client: AdbClient,
        *,
        existing_serials: set[str],
        timeout: float = _BOOT_TIMEOUT_DEFAULT,
    ) -> str | None:
        """Poll adb until a NEW emulator serial appears in 'device' state.

        Caller passes the set of serials that existed BEFORE launch so we
        can ignore them and detect the freshly-booted one. Returns the new
        serial, or None on timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for d in adb_client.list_devices():
                if d.serial in existing_serials:
                    continue
                if d.is_emulator and d.online:
                    _LOG.info("emulator booted: %s", d.serial)
                    return d.serial
            time.sleep(_BOOT_POLL_INTERVAL)
        _LOG.warning("emulator boot timed out after %.0fs", timeout)
        return None

    def kill(self, serial: str) -> None:
        """Try graceful kill via Popen, fall back to no-op (user's external emu)."""
        proc = self._launched.pop(serial, None)
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def kill_all(self) -> None:
        """Stop every emulator DroidForge launched. Doesn't touch external ones."""
        for serial in list(self._launched):
            self.kill(serial)
