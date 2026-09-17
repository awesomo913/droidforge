# DroidForge — Breakdown

## What & why

A custom Android testing engine for one developer's workflow. Built because Android Studio's built-in tooling is fine for full IDE work but heavy for "just run my APK and watch logcat" — and because this developer wants their own engine that can be extended (web layer, multi-device matrix, AI triage) without negotiating Google's UX.

Scope locked at v0.1: local-only, CLI + CustomTkinter GUI, single-device manual exploratory testing.

## Architecture

Layered, no circular deps:

```
                  cli.py            gui/app.py
                    \                   /
                     v                 v
                    droidforge/session.py
                          |
              +-----------+-----------+
              |                       |
              v                       v
      droidforge/adb.py      droidforge/logcat.py
              |                       (classify rule)
              v
      droidforge/sdk_paths.py
```

- **sdk_paths**: pure detection. No subprocess. No state.
- **adb**: subprocess wrapper. AdbClient holds path. LogcatTail spawns a thread.
- **emulator**: AVD lifecycle. Tracks DroidForge-launched emulators in a dict.
- **logcat**: parses threadtime format. `classify()` is the engine's opinion on crashes.
- **session**: glue. Install + tail + log file + crash forwarding.
- **crash_logger**: hooks `sys.excepthook` and `threading.excepthook`. For ENGINE crashes, not app crashes.
- **cli.py**: argparse subcommands. Hands work to session.
- **gui/**: CustomTkinter. Three tabs. Threading isolates adb calls from tk.

## Key design decisions

| Decision | Why |
|---|---|
| Subprocess wrappers (not pyadb library) | Zero deps, full control, version-resilient |
| Threadtime logcat format | Has PID+TID, lets you filter per-process later |
| `classify()` as a single function in logcat.py | One place to edit crash rules — engine's most opinionated piece |
| CustomTkinter not Qt | Faster startup, simpler theming, fewer install errors |
| Logs to disk per session | Replay + share without re-running. Filename includes serial + timestamp |
| `crash_logger` is engine-self only | Distinct from logcat crash detection, which catches APP crashes on the device |
| Graceful "emulator not installed" | Most users have adb but not the emulator package — engine handles physical-only setups |

## Out of scope for v0.1

- **Web dashboard** — same engine, FastAPI bolt-on. Deferred.
- **Multi-device parallel runs** — TestSession is single-device. Spinning up N is an orchestrator above this layer.
- **Espresso/UIAutomator orchestration** — engine triggers `adb shell am instrument`. v0.2 candidate.
- **AI-assisted crash triage** — pipe the crash event to Claude/Ollama. Easy add — `CrashDetector.on_crash` callback already exists.
- **AVD creation** — depends on `avdmanager` interactive prompts. Better to defer to Android Studio's Device Manager for now.
- **APK package-name extraction** — needs `aapt2` or APK zip parsing. Currently returns None.

## Risks / Known gaps

- **Windows-only paths**: `os.startfile`, `creationflags=0x08000000`, `.exe`/`.bat` suffixes. Cross-platform requires extracting these into a small platform module.
- **Logcat parsing is regex-based**: Android multiline crash dumps (`*** *** ***` headers) span multiple log lines. `classify()` only sees one line at a time. A multi-line crash detector would be a nice v0.2.
- **No retry on transient adb errors**: USB unplug mid-session = silent stop. Worth adding reconnect logic.
- **No process-name filtering on logcat tail**: floods you with system noise. v0.2: filter by package name.

## Test plan (manual, since this is the testing tool)

1. `python cli.py doctor` — exits 0 when SDK is fully installed, 1 with clear list otherwise.
2. `python cli.py devices` with no devices — shows hint, exits 0.
3. Plug in physical phone, repeat — shows the device.
4. `python cli.py gui` — window opens, no crashes, status bar shows SDK issues if any.
5. GUI Devices tab → Refresh — populates after physical phone plugged in.
6. Test tab → start without picking device — logs "pick a device first".
7. Choose APK → Start — install runs, logcat fills the panel, log file appears under `logs/`.
8. Force a crash on the target app → CRITICAL line appears in red, badge turns red and counts up.
9. Stop → log file finalized, badge persists, can switch to Logs tab and open the file.
