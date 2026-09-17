"""DroidForge — local Android testing engine.

Wraps adb + emulator into a single workflow:
    install APK → mirror screen → stream logcat → flag crashes.

Built for solo dev use, single machine, manual exploratory testing.
"""

__version__ = "0.1.0"
