"""Launch-at-login registration, per platform.

Windows writes a HKCU Run key (primary, tested path). macOS/Linux
implementations are included for completeness but untested on real
hardware — see README.md for manual alternatives on those platforms.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "WisprDictation"


def set_enabled(enabled: bool, entry_point: Path) -> None:
    if sys.platform == "win32":
        _set_windows(enabled, entry_point)
    elif sys.platform == "darwin":
        _set_macos(enabled, entry_point)
    elif sys.platform.startswith("linux"):
        _set_linux(enabled, entry_point)
    else:
        print(f"[wispr] launch-at-login is not implemented for platform {sys.platform!r}")


def _set_windows(enabled: bool, entry_point: Path) -> None:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            interpreter = str(pythonw) if pythonw.exists() else sys.executable
            command = f'"{interpreter}" "{entry_point}"'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"com.wispr.{APP_NAME.lower()}.plist"


def _set_macos(enabled: bool, entry_point: Path) -> None:
    import subprocess

    plist_path = _macos_plist_path()
    if enabled:
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wispr.{APP_NAME.lower()}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{entry_point}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
        plist_path.write_text(plist, encoding="utf-8")
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
    else:
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        if plist_path.exists():
            plist_path.unlink()


def _linux_desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / f"{APP_NAME.lower()}.desktop"


def _set_linux(enabled: bool, entry_point: Path) -> None:
    desktop_path = _linux_desktop_path()
    if enabled:
        desktop_path.parent.mkdir(parents=True, exist_ok=True)
        contents = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec={sys.executable} {entry_point}
X-GNOME-Autostart-enabled=true
"""
        desktop_path.write_text(contents, encoding="utf-8")
    else:
        if desktop_path.exists():
            desktop_path.unlink()
