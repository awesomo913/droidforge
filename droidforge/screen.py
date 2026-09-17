"""scrcpy launcher — mirror device screen in a separate window.

scrcpy is bundled under vendor/scrcpy/. On launch we spawn the binary
with the target device serial, hand back a Popen so the caller can stop
it later. We don't try to embed the window inside Tk (scrcpy uses SDL2;
embedding is hairy and brittle). A separate floating window is fine for
v0.2 — user docks it next to the DroidForge GUI.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)
# vendor/scrcpy/scrcpy-win64-vX.X/scrcpy.exe — version subdir varies.
_SCRCPY_PARENT = Path(__file__).resolve().parent.parent / "vendor" / "scrcpy"


@dataclass(frozen=True)
class MirrorHandle:
    """One running mirror session."""
    serial: str
    proc: subprocess.Popen[bytes]

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None


class ScrcpyError(RuntimeError):
    """scrcpy binary missing or refused to launch."""


def _locate_binary() -> Path | None:
    """Find scrcpy.exe inside vendor/scrcpy/scrcpy-win64-v*/."""
    if not _SCRCPY_PARENT.is_dir():
        return None
    for sub in _SCRCPY_PARENT.iterdir():
        if not sub.is_dir():
            continue
        candidate = sub / "scrcpy.exe"
        if candidate.exists():
            return candidate
    return None


class ScreenMirror:
    """Owns the bundled scrcpy binary and any running mirrors."""

    def __init__(self) -> None:
        self._binary = _locate_binary()
        self._mirrors: dict[str, MirrorHandle] = {}

    def available(self) -> bool:
        return self._binary is not None

    def binary_path(self) -> Path | None:
        return self._binary

    def start(
        self,
        serial: str,
        *,
        max_size: int = 1024,
        bit_rate: str = "4M",
    ) -> MirrorHandle:
        """Spawn a scrcpy window for the given device.

        max_size: longest-side resolution cap (px). Lower = lower latency.
        bit_rate: H.264 bitrate, e.g. "4M", "8M".
        """
        if self._binary is None:
            raise ScrcpyError(
                f"scrcpy.exe not found under {_SCRCPY_PARENT}. "
                "Re-run setup or place scrcpy-win64-vX manually."
            )
        if serial in self._mirrors and self._mirrors[serial].alive:
            _LOG.info("mirror already running for %s", serial)
            return self._mirrors[serial]

        args = [
            str(self._binary),
            "--serial", serial,
            "--max-size", str(max_size),
            "--video-bit-rate", bit_rate,
            "--window-title", f"DroidForge: {serial}",
        ]
        _LOG.info("launching scrcpy: %s", " ".join(args))
        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        handle = MirrorHandle(serial=serial, proc=proc)
        self._mirrors[serial] = handle
        return handle

    def stop(self, serial: str) -> None:
        """Close the mirror window for a given device, if running."""
        handle = self._mirrors.pop(serial, None)
        if handle is None or not handle.alive:
            return
        handle.proc.terminate()
        try:
            handle.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            handle.proc.kill()

    def stop_all(self) -> None:
        for serial in list(self._mirrors):
            self.stop(serial)
