"""Process-wide crash logger.

Hooks `sys.excepthook` and `threading.excepthook` so any uncaught
exception in DroidForge itself (engine, GUI, threads) is dumped to
`logs/crash_<timestamp>.log` with full traceback + context. Re-raises
so normal Python crash behavior still applies (don't swallow).

Call `install()` once, before anything risky runs. cli.py and gui/app.py
both call it at top of their entry points.
"""

from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Type

_CRASH_DIR = Path(__file__).parent.parent / "logs"
_INSTALLED = False


def _write_crash(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    tb: TracebackType | None,
    *,
    thread_name: str = "MainThread",
) -> Path:
    """Dump traceback to a timestamped file. Returns path."""
    _CRASH_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _CRASH_DIR / f"crash_{ts}.log"
    with path.open("w", encoding="utf-8") as f:
        f.write(f"DroidForge crash dump\n")
        f.write(f"Time:        {datetime.now().isoformat()}\n")
        f.write(f"Thread:      {thread_name}\n")
        f.write(f"Python:      {sys.version}\n")
        f.write(f"Platform:    {sys.platform}\n")
        f.write(f"Exception:   {exc_type.__name__}: {exc_value}\n")
        f.write("\n--- Traceback ---\n")
        traceback.print_exception(exc_type, exc_value, tb, file=f)
    return path


def _excepthook(exc_type, exc_value, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        # Don't dump crash for Ctrl-C — that's normal exit.
        sys.__excepthook__(exc_type, exc_value, tb)
        return
    path = _write_crash(exc_type, exc_value, tb)
    sys.stderr.write(f"\nCRASH: {exc_type.__name__}: {exc_value}\n")
    sys.stderr.write(f"Dump:  {path}\n")
    sys.__excepthook__(exc_type, exc_value, tb)


def _thread_excepthook(args: threading.ExceptHookArgs) -> None:
    if issubclass(args.exc_type, SystemExit):
        return
    path = _write_crash(
        args.exc_type, args.exc_value, args.exc_traceback,
        thread_name=args.thread.name if args.thread else "<unknown>",
    )
    sys.stderr.write(f"\nTHREAD CRASH: {args.exc_type.__name__}: {args.exc_value}\n")
    sys.stderr.write(f"Dump:         {path}\n")


def install() -> None:
    """Idempotent — safe to call from multiple entry points."""
    global _INSTALLED
    if _INSTALLED:
        return
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    _INSTALLED = True
