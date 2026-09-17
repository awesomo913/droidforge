# DroidForge — Handoff

## Goals

Built **DroidForge v0.1**: a local Android testing engine for solo dev use. Wraps `adb` and `emulator` into a single workflow with a CLI and a CustomTkinter GUI. Devs pick a device, optionally install an APK, watch logcat stream live, get flagged when crashes happen.

The owner wanted their own engine — extensible without Google or Android Studio in the loop — for both local and (eventually) online testing of apps they're building.

## History (chronological)

1. **Scope lock** via `AskUserQuestion`:
   - Local CLI + desktop GUI (not web — that's a future bolt-on)
   - APK install + manual test only (no Espresso orchestration yet)
   - New project at `C:\Users\computer\Desktop\AI\DroidForge`
2. **Detection layer** (`droidforge/sdk_paths.py`): finds `adb.exe`, `emulator.exe`, `avdmanager` via env vars → known paths → PATH. Returns dataclass with `None` for missing pieces. `diagnose()` produces human-readable issue list.
3. **adb wrapper** (`droidforge/adb.py`): `AdbClient` for sync calls (`list_devices`, `install`, `uninstall`), `LogcatTail` for threaded streaming with stop hook. Hides `creationflags=0x08000000` so no console flicker on Windows.
4. **emulator wrapper** (`droidforge/emulator.py`): `EmulatorClient.list_avds()` returns `[]` cleanly when emulator package isn't installed (this dev's current state). `launch()` raises `EmulatorError` with install instructions instead of crashing.
5. **logcat module** (`droidforge/logcat.py`): regex parses threadtime format. `classify()` is the engine's opinion on what counts as a crash. Default catches Java FATAL, ANR, native SIGSEGV. **This function is documented as the user's contribution surface** — they can rewrite it for their apps' specific crash patterns.
6. **session orchestrator** (`droidforge/session.py`): `TestSession` glues install + tail + log file + crash forwarding. One session = one device = one log file.
7. **CLI** (`cli.py`): argparse subcommands `doctor`, `devices`, `avds`, `install`, `tail`, `gui`. Imports `crash_logger.install()` first thing.
8. **GUI** (`gui/app.py` + `gui/tabs/`): CustomTkinter, three tabs. Devices (refresh + pick), Test (APK + live logcat with red-tagged crashes + crash count badge), Logs (browse session logs). Threading isolates adb calls from tk.
9. **Process crash logger** (`droidforge/crash_logger.py`): hooks `sys.excepthook` + `threading.excepthook`, dumps to `logs/crash_<ts>.log`.

## Verified working on this machine

- `python cli.py doctor` → SDK detected at `C:\Android\Sdk`, adb + avdmanager found, emulator package correctly flagged missing.
- `python cli.py devices` → "No devices connected" with helpful next steps (zero false errors).
- `python cli.py avds` → graceful "emulator not installed" message.
- `from gui.app import DroidForgeApp` imports clean.
- Logcat parser tested on 4 sample lines — Java FATAL → CRITICAL, ANR → HIGH, native SIGSEGV → CRITICAL, info line → None.

## Owner contribution

`droidforge/logcat.py::classify()` is left with a sensible default and a **TODO marker for the owner**. The function is the engine's most opinionated piece — what counts as a crash worth flagging — and the owner is best positioned to tune it for their apps. ~5-10 lines.

## Credit & Authorship

- **Owner**: awesomo913 — set scope, owns the `classify()` rule, will install Android Emulator package when needed.
- **Implementation**: Claude (this conversation), structured per workspace rules (small files, early returns, named constants, immutable dataclasses, crash_logger at entry points, BREAKDOWN/HANDOFF/TUTORIAL docs).

## Known gaps / next steps

- Install Android Emulator package via SDK Manager (currently flagged by `doctor`)
- Web/remote bolt-on: FastAPI server reusing the same `droidforge/` package, screens streamed via WebRTC
- Multi-device matrix: orchestrator above `TestSession` to fan out to N devices
- AI-assisted crash triage: `CrashDetector.on_crash` already passes a `CrashEvent` — pipe it to a Claude API call or local Ollama
- Cross-platform: extract Windows-isms (`os.startfile`, `.exe`, `creationflags`) into a small platform shim
- Multi-line crash detection: native crash blocks span multiple logcat lines; current `classify()` sees one at a time
