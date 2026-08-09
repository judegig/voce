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
# How long to keep capturing after the hotkey is released. See Recorder.stop:
# releasing on the final syllable rather than after it costs Whisper the last
# word, and this covers the overlap.
CAPTURE_TAIL_SECONDS = 0.35
ENTRY_POINT = Path(__file__).resolve().parent.parent.parent / "run.py"


class VoceApp:
    def __init__(self) -> None:
        self.settings: Settings = load_settings()
        self._enabled = True
        # Only ever read/written from Tk-thread-dispatched callbacks below
        # (_show_pill/_hide_pill/_maybe_flash_language), so no lock is
        # needed -- the Tk mainloop is single-threaded, which is what makes
        # this safe to use as a "is a newer recording active" guard against
        # a stale background transcription result. See _maybe_flash_language.
        self._recording = False
        # Non-blocking guard so two rapid "Change Hotkey..." clicks can't
        # each spawn a capture thread. See _on_change_hotkey.
        self._capture_lock = threading.Lock()
        self._recorder = Recorder(
            sample_rate=self.settings.sample_rate,
            device=self.settings.input_device,
            preroll_seconds=self.settings.preroll_seconds,
        )
        # Just the initial seed for the tray's device submenu -- TrayApp
        # polls list_input_devices() itself afterward to pick up mics
        # plugged in or unplugged after startup. Recorder.device (set via
        # the tray callback) is what's actually used for capture; this list
        # is display-only.
        self._devices = list_input_devices()

        self._root = tk.Tk()
        self._root.withdraw()  # no main window — just drives the Tk event loop

        self._pill = RecordingPill(self._root)
        self._hotkey = self._make_hotkey_or_default()
        self._tray = TrayApp(
            on_toggle_enabled=self._on_toggle_enabled,
            on_toggle_login=self._on_toggle_login,
            on_select_device=self._on_select_device,
            on_select_language=self._on_select_language,
            on_toggle_auto_detect=self._on_toggle_auto_detect,
            on_change_hotkey=self._on_change_hotkey,
            on_toggle_tap_mode=self._on_toggle_tap_mode,
            on_quit=self._on_quit,
            enabled=True,
            launch_at_login=self.settings.launch_at_login,
            devices=self._devices,
            current_device=self.settings.input_device,
            languages=LANGUAGES,
            current_language=self.settings.transcription.language,
            auto_detect_language=self.settings.transcription.auto_detect_language,
            tap_to_toggle=self.settings.hotkey_mode == "toggle",
        )

    def _make_hotkey(self, combo: Optional[str] = None) -> HoldToTalkHotkey:
        return HoldToTalkHotkey(
            combo if combo is not None else self.settings.hotkey,
            on_start=self._on_hotkey_down,
            on_stop=self._on_hotkey_up,
            mode=self.settings.hotkey_mode,
        )

    def _make_hotkey_or_default(self) -> HoldToTalkHotkey:
        """Builds the configured hotkey, falling back to the built-in default
        if settings.json holds an unparseable combo. Used at startup, where
        raising would mean the app never launches at all -- and the README
        tells users they may hand-edit that file."""
        try:
            return self._make_hotkey()
        except ValueError as exc:
            print(
                f"[voce] {exc} Falling back to default hotkey "
                f"{Settings.hotkey!r}."
            )
            self.settings.hotkey = Settings.hotkey
            return self._make_hotkey()

    def _swap_hotkey(self, new_hotkey: HoldToTalkHotkey) -> None:
        """Replaces the active listener. Any recording still in progress is
        stopped and discarded first: the new listener starts with its own
        fresh "am I recording" state, so without this the old recording is
        orphaned -- in toggle mode the mic would keep capturing with the
        pill already hidden, and there'd be no tap that stops it."""
        self._hotkey.stop()
        if self._recorder.is_recording:
            audio_path, _ = self._recorder.stop()
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)
            self._root.after(0, self._hide_pill)
        self._hotkey = new_hotkey
        self._hotkey.start()

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
        # Recorder.stop() sleeps for the capture tail, so it can't run here --
        # this is the pynput listener thread, and blocking it stalls every
        # key event that follows, including the next hotkey press.
        threading.Thread(target=self._finish_recording, daemon=True).start()

    # -- capture teardown, on a background thread (see _on_hotkey_up) --

    def _finish_recording(self) -> None:
        audio_path, duration = self._recorder.stop(
            tail_seconds=CAPTURE_TAIL_SECONDS
        )
        if audio_path is None:
            return
        if duration < MIN_RECORDING_SECONDS:
            audio_path.unlink(missing_ok=True)
            return
        self._process(audio_path)

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
            print(f"[voce] transcription failed: {exc}")
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
            print(f"[voce] detected language: {result.language}")
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
        # The guard stops a second click from starting a rival capture
        # thread, which would leave two listeners fighting over the swap.
        if not self._capture_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._capture_hotkey_flow, daemon=True).start()

    def _capture_hotkey_flow(self) -> None:
        try:
            # Stop the normal listener first so it and the capture listener
            # below aren't both reacting to the same key events.
            self._hotkey.stop()
            self._root.after(0, lambda: self._pill.show_message("Press new hotkey..."))

            combo = capture_hotkey()

            self._root.after(0, self._pill.hide)

            if not combo or combo == "esc":
                # Empty combo also covers the capture timing out with no key
                # pressed -- either way, restore the previous listener.
                self._root.after(0, lambda: self._pill.flash_message("Cancelled"))
                self._hotkey.start()
                return

            try:
                new_hotkey = self._make_hotkey(combo)
            except ValueError as exc:
                print(f"[voce] failed to set hotkey: {exc}")
                self._root.after(0, lambda: self._pill.flash_message("Invalid hotkey"))
                self._hotkey.start()
                return

            self._swap_hotkey(new_hotkey)
            self.settings.hotkey = combo
            save_settings(self.settings)
            self._root.after(0, lambda: self._pill.flash_message(f"Hotkey: {combo}"))
        finally:
            self._capture_lock.release()

    def _on_toggle_tap_mode(self, enabled: bool) -> None:
        self.settings.hotkey_mode = "toggle" if enabled else "hold"
        save_settings(self.settings)
        self._swap_hotkey(self._make_hotkey())

    def _on_quit(self) -> None:
        self._hotkey.stop()
        # The recorder holds the mic open between recordings for pre-roll;
        # release it explicitly so the OS stops showing the mic as in use.
        self._recorder.close()
        self._root.after(0, self._root.quit)

    def run(self) -> None:
        # Start the mic before the first keypress so the pre-roll buffer is
        # already full when it arrives, and so a bad device selection is
        # reported at startup rather than silently on the first recording.
        self._recorder.arm()
        self._hotkey.start()
        self._tray.run_in_background()
        self._root.mainloop()


def main() -> None:
    VoceApp().run()
