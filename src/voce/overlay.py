"""A tiny always-on-top, borderless pill shown while recording is active.

All methods must be called from the Tk main thread. Callers on other
threads should schedule show()/hide() via `root.after(0, ...)`.
"""
from __future__ import annotations

import math
import time
import tkinter as tk

# Breathing pulse color boundaries (dark red to bright red)
_PULSE_DIM_RGB = (90, 30, 27)
_PULSE_BRIGHT_RGB = (255, 69, 58)
_PULSE_PERIOD_SECONDS = 1.8
_PULSE_INTERVAL_MS = 33


class RecordingPill:
    def __init__(self, root: tk.Tk):
        self._root = root
        self._window = tk.Toplevel(root)
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        try:
            self._window.attributes("-alpha", 0.92)
        except tk.TclError:
            pass  # transparency isn't supported on every platform/WM

        width, height = 150, 42
        screen_w = self._window.winfo_screenwidth()
        x = (screen_w - width) // 2
        y = 40
        self._window.geometry(f"{width}x{height}+{x}+{y}")

        self._canvas = tk.Canvas(
            self._window, width=width, height=height, bg="#1e1e1e", highlightthickness=0
        )
        self._canvas.pack(fill="both", expand=True)
        self._dot = self._canvas.create_oval(16, 16, 28, 28, fill="#ff453a", outline="")
        self._label = self._canvas.create_text(
            85, 21, text="Listening...", fill="#f5f5f5", font=("Segoe UI", 11)
        )

        self._window.withdraw()
        self._pulse_job: str | None = None
        self._flash_job: str | None = None
        self._pulse_start_time: float = 0.0

    def show(self) -> None:
        # A flash_message() from a *previous* utterance may still have a
        # hide scheduled (its `duration_ms` timer). If a new recording
        # starts before that fires, cancel it -- otherwise it would
        # withdraw the pill out from under an in-progress recording.
        if self._flash_job is not None:
            self._window.after_cancel(self._flash_job)
            self._flash_job = None
        if self._pulse_job is not None:
            self._window.after_cancel(self._pulse_job)
            self._pulse_job = None

        self._canvas.itemconfig(self._label, text="Listening...")
        self._canvas.itemconfig(self._dot, fill="#ff453a")
        self._pulse_start_time = time.monotonic()

        self._window.deiconify()
        self._window.lift()
        self._pulse()

    def hide(self) -> None:
        if self._pulse_job is not None:
            self._window.after_cancel(self._pulse_job)
            self._pulse_job = None
        if self._flash_job is not None:
            self._window.after_cancel(self._flash_job)
            self._flash_job = None
        self._window.withdraw()

    def _pulse(self) -> None:
        elapsed = time.monotonic() - self._pulse_start_time
        phase = (elapsed * 2.0 * math.pi) / _PULSE_PERIOD_SECONDS
        # Cosine factor smoothly transitions 1.0 -> 0.0 -> 1.0 starting at full brightness
        factor = (math.cos(phase) + 1.0) / 2.0

        r = int(_PULSE_DIM_RGB[0] + (_PULSE_BRIGHT_RGB[0] - _PULSE_DIM_RGB[0]) * factor)
        g = int(_PULSE_DIM_RGB[1] + (_PULSE_BRIGHT_RGB[1] - _PULSE_DIM_RGB[1]) * factor)
        b = int(_PULSE_DIM_RGB[2] + (_PULSE_BRIGHT_RGB[2] - _PULSE_DIM_RGB[2]) * factor)
        self._canvas.itemconfig(self._dot, fill=f"#{r:02x}{g:02x}{b:02x}")
        self._pulse_job = self._window.after(_PULSE_INTERVAL_MS, self._pulse)

    def show_message(self, text: str) -> None:
        """Shows `text` persistently (no pulse, no auto-hide timer) until
        hide() is called. Used for the hotkey-capture prompt, where the
        duration isn't known up front."""
        if self._pulse_job is not None:
            self._window.after_cancel(self._pulse_job)
            self._pulse_job = None
        if self._flash_job is not None:
            self._window.after_cancel(self._flash_job)
            self._flash_job = None
        self._canvas.itemconfig(self._dot, fill="#3a86ff")
        self._canvas.itemconfig(self._label, text=text)
        self._window.deiconify()
        self._window.lift()

    def flash_message(self, text: str, duration_ms: int = 1500) -> None:
        """Briefly shows `text` (e.g. a detected language code) in place of
        the listening indicator, then hides the pill again."""
        if self._pulse_job is not None:
            self._window.after_cancel(self._pulse_job)
            self._pulse_job = None
        if self._flash_job is not None:
            self._window.after_cancel(self._flash_job)
            self._flash_job = None

        self._canvas.itemconfig(self._dot, fill="#3a86ff")
        self._canvas.itemconfig(self._label, text=text)
        self._window.deiconify()
        self._window.lift()
        self._flash_job = self._window.after(duration_ms, self._reset_and_hide)

    def _reset_and_hide(self) -> None:
        self._flash_job = None
        if self._pulse_job is not None:
            self._window.after_cancel(self._pulse_job)
            self._pulse_job = None
        self._canvas.itemconfig(self._label, text="Listening...")
        self._canvas.itemconfig(self._dot, fill="#ff453a")
        self._window.withdraw()
