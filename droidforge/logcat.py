"""Logcat parsing + crash detection.

Stream lines from adb.LogcatTail through `CrashDetector.feed()`.
When `classify()` returns a Severity, detector fires the on_crash callback
(used by GUI to flash an alert, save a crash bundle, ping crash_logger).

The classify() rule is deliberately YOURS to define — this is the engine's
core opinion on what counts as a crash for your apps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable


class Severity(Enum):
    """How loud should the engine yell about this line?"""
    INFO = "info"        # noteworthy but not a crash
    WARN = "warn"        # something off, app may still be alive
    HIGH = "high"        # ANR, force-stop, recoverable error
    CRITICAL = "critical"  # process dead — Java fatal, native SIGSEGV, etc.


@dataclass(frozen=True)
class LogLine:
    """One parsed logcat line in `-v threadtime` format.

    Example raw line:
        04-28 14:23:01.234  1234  5678 E AndroidRuntime: FATAL EXCEPTION: main
    """
    timestamp: str   # "04-28 14:23:01.234"
    pid: int
    tid: int
    level: str       # V, D, I, W, E, F (verbose..fatal)
    tag: str         # "AndroidRuntime"
    message: str     # "FATAL EXCEPTION: main"
    raw: str


# Compiled once. threadtime format is space-separated, tag ends at colon.
_THREADTIME_RE = re.compile(
    r"^(?P<ts>\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+"
    r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+"
    r"(?P<level>[VDIWEF])\s+"
    r"(?P<tag>[^:]+):\s?(?P<msg>.*)$"
)


def parse_line(raw: str) -> LogLine | None:
    """Parse one threadtime line. Returns None for header/garbage lines."""
    m = _THREADTIME_RE.match(raw)
    if not m:
        return None
    return LogLine(
        timestamp=m["ts"],
        pid=int(m["pid"]),
        tid=int(m["tid"]),
        level=m["level"],
        tag=m["tag"].strip(),
        message=m["msg"],
        raw=raw,
    )


# ============================================================================
# CRASH DETECTION RULE — YOUR CONTRIBUTION GOES HERE
# ============================================================================
#
# This is the engine's most opinionated function. It decides what counts as
# a crash for *your* apps. The wider the net, the more false alarms. The
# tighter the net, the more crashes slip past you in noisy logs.
#
# Common signals (pick what matters to you):
#
#   1. JVM uncaught exceptions
#      tag == "AndroidRuntime" AND "FATAL EXCEPTION" in message
#      → Severity.CRITICAL (process dies)
#
#   2. App Not Responding (ANR — UI thread blocked >5s)
#      tag == "ActivityManager" AND message.startswith("ANR in")
#      → Severity.HIGH (recoverable, user sees "App isn't responding")
#
#   3. Native crashes (SIGSEGV, SIGABRT, stack smashing)
#      tag in ("libc", "DEBUG") AND ("Fatal signal" in message
#                                     or "*** ***" in message)
#      → Severity.CRITICAL
#
#   4. StrictMode violations (your own debug builds, optional)
#      tag == "StrictMode" AND level == "E"
#      → Severity.WARN (nice to know, not crashing)
#
#   5. Force-stop / process death
#      "Process ... has died" in message
#      → Severity.HIGH
#
# YOUR TASK:
#   Replace the body of `classify()` below with your detection logic.
#   Return Severity if line indicates a crash worth flagging, else None.
#   Aim for 5-10 lines. Use early returns for clarity.
# ============================================================================


def classify(line: LogLine) -> Severity | None:
    """Decide if this line is a crash. Return Severity or None.

    TODO(you): Implement your detection rule. See guidance comment above.
    Default below is a sensible starter — tighten or loosen as needed.
    """
    # --- Starter rule (delete or refine to taste) ---
    msg = line.message
    if line.tag == "AndroidRuntime" and "FATAL EXCEPTION" in msg:
        return Severity.CRITICAL
    if line.tag == "ActivityManager" and msg.startswith("ANR in"):
        return Severity.HIGH
    if line.tag in ("libc", "DEBUG") and "Fatal signal" in msg:
        return Severity.CRITICAL
    if line.level == "F":  # any other fatal level — broad fallback
        return Severity.HIGH
    return None


# ============================================================================
# Detector wrapper — owns the rule, fans out to caller via callback.
# ============================================================================


@dataclass
class CrashEvent:
    """One detected crash, packaged for the UI / crash_logger / disk."""
    line: LogLine
    severity: Severity
    detected_at: datetime


CrashCallback = Callable[[CrashEvent], None]


class CrashDetector:
    """Stateless rule applicator with a callback fanout.

    Plug into adb.LogcatTail:
        detector = CrashDetector(on_crash=lambda e: print("BOOM:", e))
        tail = LogcatTail(client, serial, on_line=detector.feed)
        tail.start()
    """

    def __init__(self, on_crash: CrashCallback) -> None:
        self._on_crash = on_crash

    def feed(self, raw_line: str) -> None:
        """Called for every logcat line. Parse, classify, fire callback."""
        parsed = parse_line(raw_line)
        if parsed is None:
            return
        severity = classify(parsed)
        if severity is None:
            return
        event = CrashEvent(
            line=parsed,
            severity=severity,
            detected_at=datetime.now(),
        )
        try:
            self._on_crash(event)
        except Exception:
            # Don't let callback bugs derail the detector.
            pass
