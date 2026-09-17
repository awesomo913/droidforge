"""DroidForge CLI entry point.

Usage:
    python cli.py doctor                     # check SDK setup
    python cli.py devices                    # list connected devices
    python cli.py avds                       # list installed AVDs
    python cli.py install <apk> [-s SERIAL]  # install APK on device
    python cli.py tail [-s SERIAL]           # stream logcat with crash flagging
    python cli.py gui                        # launch CustomTkinter GUI
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Install crash logger as early as possible.
from droidforge import crash_logger as _crash_logger
_crash_logger.install()

from droidforge.adb import AdbClient
from droidforge.emulator import EmulatorClient, EmulatorError
from droidforge.logcat import CrashDetector, Severity
from droidforge.screen import ScreenMirror, ScrcpyError
from droidforge.sdk_paths import diagnose, locate
from droidforge.session import SessionConfig, TestSession
from droidforge.triage import TriageError, is_configured, triage


_SEVERITY_PREFIX = {
    Severity.INFO: "[INFO]",
    Severity.WARN: "[WARN]",
    Severity.HIGH: "[HIGH] ",
    Severity.CRITICAL: "[CRITICAL]",
}


def cmd_doctor(_args) -> int:
    paths = locate()
    print(f"SDK root:    {paths.sdk_root or '<not found>'}")
    print(f"adb:         {paths.adb or '<missing>'}")
    print(f"emulator:    {paths.emulator or '<missing>'}")
    print(f"avdmanager:  {paths.avdmanager or '<missing>'}")
    issues = diagnose(paths)
    if not issues:
        print("\nAll good. Engine is ready.")
        return 0
    print("\nIssues to fix:")
    for i in issues:
        print(f"  - {i}")
    return 1


def cmd_devices(_args) -> int:
    client = AdbClient(locate())
    devices = client.list_devices()
    if not devices:
        print("No devices connected.")
        print("  - Plug in a phone with USB debugging on, OR")
        print("  - Launch an emulator (`python cli.py avds` to list them)")
        return 0
    print(f"{len(devices)} device(s):")
    for d in devices:
        kind = "emulator" if d.is_emulator else "physical"
        print(f"  {d.serial:20s}  {d.state:14s}  ({kind})")
    return 0


def cmd_avds(_args) -> int:
    emu = EmulatorClient(locate())
    if not emu.available():
        print("emulator.exe not installed. See `python cli.py doctor`.")
        return 1
    avds = emu.list_avds()
    if not avds:
        print("No AVDs created. Use Android Studio Device Manager to make one.")
        return 0
    print(f"{len(avds)} AVD(s):")
    for a in avds:
        print(f"  {a.name}")
    return 0


def cmd_install(args) -> int:
    client = AdbClient(locate())
    serial = _resolve_serial(client, args.serial)
    if serial is None:
        return 1
    apk = Path(args.apk).resolve()
    if not apk.exists():
        print(f"APK not found: {apk}")
        return 1
    print(f"Installing {apk.name} on {serial}...")
    result = client.install(serial, apk)
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return 0 if result.ok else 1


def cmd_tail(args) -> int:
    client = AdbClient(locate())
    serial = _resolve_serial(client, args.serial)
    if serial is None:
        return 1

    def on_crash(event):
        prefix = _SEVERITY_PREFIX.get(event.severity, "[?]")
        print(f"\n*** {prefix} CRASH DETECTED ***")
        print(f"    {event.line.tag}: {event.line.message}")
        print(f"    at {event.detected_at.strftime('%H:%M:%S')}\n")

    cfg = SessionConfig(
        device_serial=serial,
        on_crash=on_crash,
        on_log_line=lambda l: print(l),
        label="cli-tail",
    )
    session = TestSession(client, cfg)
    session.start()
    print(f"Tailing logcat on {serial}. Log file: {session.log_path}")
    print("Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        session.stop()
        print(f"{len(session.crashes)} crash event(s) captured.")
    return 0


def cmd_launch(args) -> int:
    """Boot an AVD, wait for it to come online."""
    paths = locate()
    emu = EmulatorClient(paths)
    if not emu.available():
        print("emulator.exe not installed. See `python cli.py doctor`.")
        return 1
    adb = AdbClient(paths)
    existing = {d.serial for d in adb.list_devices()}
    print(f"Launching {args.avd}...")
    try:
        proc = emu.launch(args.avd)
    except EmulatorError as e:
        print(str(e))
        return 1
    print("Waiting for boot (up to 3 min)...")
    serial = emu.wait_for_boot(adb, existing_serials=existing)
    if serial is None:
        print("Boot timed out. Is the AVD healthy?")
        return 1
    emu.track_serial(serial, proc)
    print(f"Booted: {serial}")
    return 0


def cmd_mirror(args) -> int:
    """Start scrcpy screen mirror for a device."""
    mirror = ScreenMirror()
    if not mirror.available():
        print("scrcpy not found under vendor/scrcpy/. Bundle it first.")
        return 1
    client = AdbClient(locate())
    serial = _resolve_serial(client, args.serial)
    if serial is None:
        return 1
    try:
        mirror.start(serial)
    except ScrcpyError as e:
        print(str(e))
        return 1
    print(f"Mirror running for {serial}. Close the scrcpy window to stop.")
    return 0


def cmd_triage(args) -> int:
    """Read crash + log context from stdin/files, ask Claude for a hypothesis."""
    if not is_configured():
        print("ANTHROPIC_API_KEY not set. Export it before running triage.")
        return 1
    log_path = Path(args.log)
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return 1
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    # Find the last crash-looking line as the trigger event.
    from droidforge.logcat import classify, parse_line
    event = None
    for raw in reversed(lines):
        parsed = parse_line(raw)
        if parsed is None:
            continue
        sev = classify(parsed)
        if sev is not None:
            from droidforge.logcat import CrashEvent
            from datetime import datetime
            event = CrashEvent(line=parsed, severity=sev, detected_at=datetime.now())
            break
    if event is None:
        print("No crash-looking line found in that log. Nothing to triage.")
        return 1
    print(f"Triaging {event.severity.value.upper()}: {event.line.tag} ...\n")
    try:
        result = triage(event, lines, on_token=lambda s: print(s, end="", flush=True))
    except TriageError as e:
        print(f"\n\n[ERROR] {e}")
        return 1
    print(
        f"\n\n--- tokens: in={result.input_tokens} out={result.output_tokens} "
        f"cache_read={result.cache_read_tokens} ---"
    )
    return 0


def cmd_gui(_args) -> int:
    # Imported lazily so the CLI doesn't pay the customtkinter import cost
    # on `cli.py devices` etc.
    from gui.app import launch
    launch()
    return 0


def _resolve_serial(client: AdbClient, requested: str | None) -> str | None:
    """Pick a device. If user passed -s, use it. Else: only-one or error."""
    devices = [d for d in client.list_devices() if d.online]
    if requested:
        if any(d.serial == requested for d in devices):
            return requested
        print(f"Device '{requested}' not connected or not online.")
        return None
    if not devices:
        print("No online devices. Run `python cli.py devices`.")
        return None
    if len(devices) > 1:
        print("Multiple devices connected. Pick one with -s:")
        for d in devices:
            print(f"  {d.serial}")
        return None
    return devices[0].serial


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="droidforge",
        description="Local Android testing engine.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="Check SDK setup")
    sub.add_parser("devices", help="List connected devices")
    sub.add_parser("avds", help="List installed AVDs")

    p_install = sub.add_parser("install", help="Install an APK")
    p_install.add_argument("apk", help="Path to .apk file")
    p_install.add_argument("-s", "--serial", help="Device serial (optional if only one connected)")

    p_tail = sub.add_parser("tail", help="Stream logcat with crash detection")
    p_tail.add_argument("-s", "--serial", help="Device serial (optional if only one connected)")

    p_launch = sub.add_parser("launch", help="Boot an AVD")
    p_launch.add_argument("avd", help="AVD name (use `avds` to list)")

    p_mirror = sub.add_parser("mirror", help="Start scrcpy screen mirror")
    p_mirror.add_argument("-s", "--serial", help="Device serial (optional if only one connected)")

    p_triage = sub.add_parser("triage", help="AI triage on a saved log file (needs ANTHROPIC_API_KEY)")
    p_triage.add_argument("log", help="Path to a session log (e.g. logs/session_*.log)")

    sub.add_parser("gui", help="Launch CustomTkinter GUI")

    args = parser.parse_args()
    handlers = {
        "doctor": cmd_doctor,
        "devices": cmd_devices,
        "avds": cmd_avds,
        "install": cmd_install,
        "tail": cmd_tail,
        "launch": cmd_launch,
        "mirror": cmd_mirror,
        "triage": cmd_triage,
        "gui": cmd_gui,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
