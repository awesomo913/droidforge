"""Locate Android SDK binaries.

Resolution order:
    1. Env vars: ANDROID_HOME, ANDROID_SDK_ROOT
    2. Known Windows install paths
    3. PATH lookup via shutil.which

Returns dataclass with optional Paths so GUI can show a clear
"install this package" message instead of crashing on missing tools.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

# Known SDK roots on Windows. Keep ordered by user-likelihood.
_KNOWN_ROOTS: tuple[str, ...] = (
    r"C:\Android\Sdk",
    str(Path.home() / "AppData" / "Local" / "Android" / "Sdk"),
    r"C:\Program Files\Android\Sdk",
    r"C:\Program Files (x86)\Android\Sdk",
)

# Sub-paths inside the SDK root (Windows binary names).
_ADB_SUBPATH = Path("platform-tools") / "adb.exe"
_EMULATOR_SUBPATH = Path("emulator") / "emulator.exe"
# avdmanager lives in cmdline-tools/<version>/bin or legacy tools/bin
_AVDMANAGER_LEAF = "avdmanager.bat"


@dataclass(frozen=True)
class SdkPaths:
    """Located SDK binaries. Any field may be None if not installed."""
    sdk_root: Path | None
    adb: Path | None
    emulator: Path | None
    avdmanager: Path | None

    @property
    def adb_ready(self) -> bool:
        return self.adb is not None and self.adb.exists()

    @property
    def emulator_ready(self) -> bool:
        return self.emulator is not None and self.emulator.exists()


def _resolve_root() -> Path | None:
    """Find the SDK root via env vars, then known paths."""
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.environ.get(env)
        if val and Path(val).is_dir():
            return Path(val)
    for known in _KNOWN_ROOTS:
        p = Path(known)
        if p.is_dir():
            return p
    return None


def _find_avdmanager(root: Path) -> Path | None:
    """avdmanager has moved across SDK versions — check both locations."""
    # Modern: cmdline-tools/<ver>/bin/avdmanager.bat
    cmdline = root / "cmdline-tools"
    if cmdline.is_dir():
        for ver_dir in cmdline.iterdir():
            candidate = ver_dir / "bin" / _AVDMANAGER_LEAF
            if candidate.exists():
                return candidate
    # Legacy: tools/bin/avdmanager.bat
    legacy = root / "tools" / "bin" / _AVDMANAGER_LEAF
    if legacy.exists():
        return legacy
    return None


def _path_lookup(name: str) -> Path | None:
    """Last-resort PATH lookup."""
    found = shutil.which(name)
    return Path(found) if found else None


def locate() -> SdkPaths:
    """Run full SDK detection. Cheap — call once at startup."""
    root = _resolve_root()
    if root is None:
        # PATH-only fallback. adb may still work even without an SDK root.
        return SdkPaths(
            sdk_root=None,
            adb=_path_lookup("adb"),
            emulator=_path_lookup("emulator"),
            avdmanager=_path_lookup("avdmanager"),
        )

    adb = root / _ADB_SUBPATH
    emulator = root / _EMULATOR_SUBPATH
    return SdkPaths(
        sdk_root=root,
        adb=adb if adb.exists() else _path_lookup("adb"),
        emulator=emulator if emulator.exists() else _path_lookup("emulator"),
        avdmanager=_find_avdmanager(root),
    )


def diagnose(paths: SdkPaths) -> list[str]:
    """Human-readable list of missing pieces. Empty list = fully ready."""
    issues: list[str] = []
    if paths.sdk_root is None:
        issues.append(
            "Android SDK root not found. Set ANDROID_HOME env var, or install "
            "Android Studio (it bundles the SDK)."
        )
    if not paths.adb_ready:
        issues.append(
            "adb.exe missing. Install via Android Studio: SDK Manager -> "
            "SDK Tools -> Android SDK Platform-Tools."
        )
    if not paths.emulator_ready:
        issues.append(
            "emulator.exe missing. Physical devices still work via USB. "
            "To add: SDK Manager -> SDK Tools -> Android Emulator."
        )
    if paths.avdmanager is None:
        issues.append(
            "avdmanager missing. Required to create new emulator AVDs. "
            "Install via SDK Manager -> SDK Tools -> Android SDK Command-line Tools."
        )
    return issues
