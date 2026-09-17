# DroidForge Tutorial

How to use the engine end-to-end. Assumes Windows + Python 3.11 + Android SDK installed.

## 1. One-time setup

```bash
cd C:\Users\computer\Desktop\AI\DroidForge
uv pip install -r requirements.txt
python cli.py doctor
```

`doctor` prints what's installed and what's missing. Common gaps:

- **adb missing** → install Android Studio (it includes platform-tools)
- **emulator missing** → only needed for AVDs. Skip if you only test on physical devices. Otherwise: Android Studio → SDK Manager → SDK Tools → check "Android Emulator".
- **avdmanager missing** → SDK Manager → SDK Tools → "Android SDK Command-line Tools (latest)"

## 2. Connect a device

**Physical phone (recommended for real-world testing):**
1. On phone: Settings → About → tap "Build number" 7 times to enable Developer Options
2. Settings → Developer Options → toggle "USB Debugging"
3. Plug into PC via USB
4. First connection: phone shows "Allow USB debugging?" — tap Allow
5. `python cli.py devices` — should show your phone's serial

**Emulator (after installing the Emulator package):**
1. Open Android Studio → Device Manager → Create Device → pick a Pixel + system image
2. `python cli.py avds` — should list your new AVD
3. Launch it from Android Studio's Device Manager (DroidForge's launch flow is v0.2)

## 3. Run a session via GUI (typical workflow)

```bash
python cli.py gui
```

1. **Devices tab** — see connected devices. Click "Use this device" on the one you want.
2. **Test tab** —
   - Top-left says "Device: <serial>" so you know what's targeted
   - Click "Choose APK..." to pick a `.apk` file (or skip — engine will tail logs of whatever's already running)
   - Click "Start session"
   - Watch the live logcat panel fill with lines
   - Crashes appear in **red** (CRITICAL) or **orange** (HIGH); the badge in the top-left counts them
   - Click "Stop" when done
3. **Logs tab** — every session writes to `logs/session_<timestamp>_<serial>.log`. Click "Open" to view in your default text editor.

## 4. Run a session via CLI (for scripting / CI)

```bash
# Install an APK on the only connected device
python cli.py install path\to\app.apk

# Stream logcat with crash flagging — Ctrl-C to stop
python cli.py tail

# If you have multiple devices, target a specific one
python cli.py tail -s emulator-5554
```

## 5. Tune the crash detection rule

The engine flags crashes by feeding each logcat line through `classify()` in `droidforge/logcat.py`. Default rule:

```python
def classify(line):
    if line.tag == "AndroidRuntime" and "FATAL EXCEPTION" in line.message:
        return Severity.CRITICAL
    if line.tag == "ActivityManager" and line.message.startswith("ANR in"):
        return Severity.HIGH
    if line.tag in ("libc", "DEBUG") and "Fatal signal" in line.message:
        return Severity.CRITICAL
    if line.level == "F":
        return Severity.HIGH
    return None
```

Edit it. Examples of useful tweaks:

- **Filter by your package** — wrap the rule with `if "com.yourapp" not in line.message: return None`
- **Add StrictMode to catch dev-build issues** — `if line.tag == "StrictMode" and line.level == "E": return Severity.WARN`
- **Catch process death** — `if "Process " in line.message and "has died" in line.message: return Severity.HIGH`

## 6. Where the files live

```
DroidForge/
├── droidforge/      # engine
├── gui/             # CustomTkinter UI
├── logs/            # session logs + crash dumps (gitignored)
├── captured_apks/   # future: screenshot/screen recording captures
├── cli.py
├── README.md
├── BREAKDOWN.md
├── HANDOFF.md
└── TUTORIAL.md      # this file
```

## 7. Common issues

| Symptom | Fix |
|---|---|
| `python cli.py devices` lists 0 even with phone plugged in | Run `adb kill-server && adb start-server` once. Then re-plug phone, accept the RSA prompt. |
| GUI shows "adb unavailable" in status bar | `python cli.py doctor` to confirm — usually missing platform-tools. |
| Live log box stops scrolling | Click inside it once — may have lost focus. Lines still arrive. |
| `Install failed` with `INSTALL_FAILED_VERSION_DOWNGRADE` | Uninstall the old version on device first: `python cli.py install` → if blocked, run `adb uninstall <package>` manually. |
| Engine crashed (window closed unexpectedly) | Look in `logs/crash_*.log` — `crash_logger` dumped a full traceback there. |

## 8. Next milestones

- v0.2: AVD launch from GUI, multi-line native-crash detection, package-name filter on logcat
- v0.3: web dashboard (same engine, FastAPI bolt-on, browser-accessible from any LAN device)
- v0.4: AI-assisted crash triage (pipe `CrashEvent` to Claude/Ollama for root-cause hypothesis)
