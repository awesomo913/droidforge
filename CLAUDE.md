<!-- claude-backend:generated:start -->
# DroidForge

## Overview

- **Files**: 22 (.py (17), .md (5))
- **Entry points**: `cli.py`, `gui/app.py`
- **Dependencies**: customtkinter, Pillow
- **Key files**: `README.md`, `CLAUDE.md`, `requirements.txt`, `.gitignore`

## Structure

```
droidforge/  (9 files)
gui/  (7 files)
  tabs/  (4 files)
```

## Conventions

- Use `pathlib.Path` for all path operations
- Type hints are used extensively -- maintain them
- Prefer f-strings for string formatting
- Use specific exception types in except clauses
- Uses print() for output (consider migrating to logging)
- Absolute imports preferred

## Modules

- `cli.py` -- DroidForge CLI entry point [entry]
- `droidforge/adb.py` -- Thin adb wrapper
- `droidforge/crash_logger.py` -- Process-wide crash logger
- `droidforge/emulator.py` -- AVD lifecycle: list / launch / kill emulator instances
- `droidforge/logcat.py` -- Logcat parsing + crash detection
- `droidforge/screen.py` -- scrcpy launcher — mirror device screen in a separate window
- `droidforge/sdk_paths.py` -- Locate Android SDK binaries
- `droidforge/session.py` -- TestSession: stitch the pieces into one workflow
- `droidforge/triage.py` -- AI-assisted crash triage via Claude API
- `gui/app.py` -- Main DroidForge GUI window [entry]
- `gui/tabs/devices_tab.py` -- Devices tab — lists adb-connected devices, refresh button
- `gui/tabs/logs_tab.py` -- Logs tab — browse session log files saved under logs/
- `gui/tabs/test_tab.py` -- Test tab — the workhorse
- `gui/triage_dialog.py` -- Modal dialog showing AI triage stream for a CrashEvent

<!-- claude-backend:generated:end -->
