"""Wires the hotkey, recorder, transcription, cleanup, paste, overlay, and
tray together into the running application.
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

from . import autostart
from .audio import Recorder, list_input_devices
from .cleanup import clean_transcript
from .config import Settings, load_settings, save_settings
from .hotkey import HoldToTalkHotkey, capture_hotkey
from .languages import LANGUAGES
from .overlay import RecordingPill
from .paste import paste_text
from .transcribe import TranscriptionError, transcribe
from .tray import TrayApp

MIN_RECORDING_SECONDS = 0.3
ENTRY_POINT = Path(__file__).resolve().parent.parent.parent / "run.py"


class WisprApp:
    def __init__(self) -> None:
        self.settings: Settings = load_settings()
        self._enabled = True
        # Only ever read/written from Tk-thread-dispatched callbacks below
        # (_show_pill/_hide_pill/_maybe_flash_language), so no lock is
        # needed -- the Tk mainloop is single-threaded, which is what makes
        # this safe to use as a "is a newer recording active" guard against
        # a stale background transcription result. See _maybe_flash_language.
        self._recording = False
        self._recorder = Recorder(
            sample_rate=self.settings.sample_rate,
            device=self.settings.input_device,
        )
        # Enumerated once at startup. Devices don't need to be re-queried
        # on every recording, and the tray submenu is built once from this
        # cached list rather than calling sounddevice on every render.
        self._devices = list_input_devices()

        self._root = tk.Tk()
        self._root.withdraw()  # no main window — just drives the Tk event loop

        self._pill = RecordingPill(self._root)
        self._hotkey = HoldToTalkHotkey(
            self.settings.hotkey,
            on_start=self._on_hotkey_down,
            on_stop=self._on_hotkey_up,
        )
        self._tray = TrayApp(
            on_toggle_enabled=self._on_toggle_enabled,
            on_toggle_login=self._on_toggle_login,
            on_select_device=self._on_select_device,
            on_select_language=self._on_select_language,
            on_toggle_auto_detect=self._on_toggle_auto_detect,
            on_change_hotkey=self._on_change_hotkey,
            on_quit=self._on_quit,
            enabled=True,
            launch_at_login=self.settings.launch_at_login,
            devices=self._devices,
            current_device=self.settings.input_device,
            languages=LANGUAGES,
            current_language=self.settings.transcription.language,
            auto_detect_language=self.settings.transcription.auto_detect_language,
        )

    # -- hotkey callbacks (run on the pynput listener thread) --

    def _on_hotkey_down(self) -> None:
        if not self._enabled:
            return
        self._recorder.start()
        self._root.after(0, self._show_pill)

    def _on_hotkey_up(self) -> None:
        if not self._enabled:
            return
        self._root.after(0, self._hide_pill)
        audio_path, duration = self._recorder.stop()
        if audio_path is None:
            return
        if duration < MIN_RECORDING_SECONDS:
            audio_path.unlink(missing_ok=True)
            return
        threading.Thread(target=self._process, args=(audio_path,), daemon=True).start()

    # -- pill state, always run on the Tk thread via root.after(0, ...) --

    def _show_pill(self) -> None:
        self._recording = True
        self._pill.show()

    def _hide_pill(self) -> None:
        self._recording = False
        self._pill.hide()

    def _maybe_flash_language(self, language: str) -> None:
        # A slow background transcription (e.g. a Groq round trip) can
        # still be in flight when the user starts and finishes a *new*
        # recording. If that happens, this flash is stale -- showing it now
        # would hijack (and, after its timer, hide) the indicator for the
        # recording that's actually active. The transcript itself is still
        # pasted regardless; only the language display is skipped.
        if self._recording:
            return
        self._pill.flash_message(language)

    # -- background worker: transcribe -> clean -> paste --

    def _process(self, audio_path: Path) -> None:
        try:
            result = transcribe(audio_path, self.settings)
        except TranscriptionError as exc:
            print(f"[wispr] transcription failed: {exc}")
            return
        finally:
            audio_path.unlink(missing_ok=True)

        if not result.text.strip():
            return

        # Only surface the detected language when auto-detect is actually
        # on -- in fixed-language mode, result.language just echoes back
        # what was already forced, which isn't news to the user and isn't
        # what requirement 4 (auto-detect) asked to surface.
        if self.settings.transcription.auto_detect_language and result.language:
            print(f"[wispr] detected language: {result.language}")
            language = result.language
            self._root.after(0, lambda: self._maybe_flash_language(language))

        cleaned = clean_transcript(result.text, self.settings)
        paste_text(cleaned)

    # -- tray callbacks (run on the pystray/GUI thread) --

    def _on_toggle_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def _on_toggle_login(self, enabled: bool) -> None:
        self.settings.launch_at_login = enabled
        autostart.set_enabled(enabled, ENTRY_POINT)
        save_settings(self.settings)

    def _on_select_device(self, index: Optional[int]) -> None:
        self.settings.input_device = index
        self._recorder.device = index
        save_settings(self.settings)

    def _on_select_language(self, code: str) -> None:
        self.settings.transcription.language = code
        self.settings.transcription.auto_detect_language = False
        save_settings(self.settings)

    def _on_toggle_auto_detect(self, enabled: bool) -> None:
        self.settings.transcription.auto_detect_language = enabled
        save_settings(self.settings)

    def _on_change_hotkey(self) -> None:
        # capture_hotkey() blocks on its own pynput listener until a key is
        # released, so it must not run on the tray/Tk thread -- do it in the
        # background and marshal only the UI updates back via root.after.
        threading.Thread(target=self._capture_hotkey_flow, daemon=True).start()

    def _capture_hotkey_flow(self) -> None:
        # Stop the normal hold-to-talk listener first so it and the capture
        # listener below aren't both reacting to the same key events.
        self._hotkey.stop()
        self._root.after(0, lambda: self._pill.show_message("Press new hotkey..."))

        combo = capture_hotkey()

        self._root.after(0, self._pill.hide)

        if not combo or combo == "esc":
            self._root.after(0, lambda: self._pill.flash_message("Cancelled"))
            self._hotkey.start()
            return

        try:
            new_hotkey = HoldToTalkHotkey(
                combo, on_start=self._on_hotkey_down, on_stop=self._on_hotkey_up
            )
        except ValueError as exc:
            print(f"[wispr] failed to set hotkey: {exc}")
            self._root.after(0, lambda: self._pill.flash_message("Invalid hotkey"))
            self._hotkey.start()
            return

        self._hotkey = new_hotkey
        self._hotkey.start()
        self.settings.hotkey = combo
        save_settings(self.settings)
        self._root.after(0, lambda: self._pill.flash_message(f"Hotkey: {combo}"))

    def _on_quit(self) -> None:
        self._hotkey.stop()
        self._root.after(0, self._root.quit)

    def run(self) -> None:
        self._hotkey.start()
        self._tray.run_in_background()
        self._root.mainloop()


def main() -> None:
    WisprApp().run()
