# DroidForge

> A lighter Android testing engine: install an APK, watch live logs, get crashes flagged automatically.

DroidForge is a local Android testing tool built as a leaner alternative to Android Studio's built-in tooling for the common "install my APK and watch logcat" workflow. It wraps `adb` and `scrcpy` behind both a CLI and a CustomTkinter desktop GUI, with logcat parsing that flags crashes by severity as they happen.

## Features
- **Device detection** — lists connected adb devices and installed AVDs.
- **APK install** from the CLI or GUI, targeting a chosen device.
- **Live logcat streaming** with automatic crash/warning severity classification.
- **AI-assisted crash triage** (`droidforge/triage.py`) via the Claude API.
- **Screen mirroring** through a bundled scrcpy binary.
- **`doctor` command** that locates the Android SDK and reports what's missing.
- **Session logging** — each test run is written to a session log file for later review.

## Stack
Python 3.11, CustomTkinter (GUI), Pillow, `adb`/`scrcpy` wrappers around the Android SDK command-line tools.

## Getting started
**Requirements**
- Python 3.11+
- Android SDK with `adb` on the machine (Android Studio's platform-tools is the easiest source); `emulator`/`avdmanager` only needed for AVDs

**Run**
```bash
uv pip install -r requirements.txt
python cli.py doctor      # verify SDK setup
python cli.py devices     # list connected devices
python cli.py gui         # launch the desktop app
# or, CLI-only:
python cli.py install <apk> [-s SERIAL]
python cli.py tail [-s SERIAL]
```

## Status
**Unmaintained / archived.** Personal project, published as-is — fork it, adapt it, take it over. No support or guarantees.

## License
[MIT](LICENSE) — free to use, fork, and build on.
