"""Global hotkey listener, in two modes:

- "hold" (default): recording starts once every key in the combo is held
  down, and stops the moment any one of them is released.
- "toggle": recording starts the first time the full combo is pressed, and
  stops the *next* time the full combo is pressed again -- releasing the
  keys does nothing in this mode, so you can tap and let go.

Supports a single key (e.g. "ctrl_r", "f9") or a "+"-separated combo
(e.g. "ctrl+alt") in either mode.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Optional

from pynput import keyboard


def _parse_key(token: str):  # noqa: ANN201
    token = token.strip().lower()
    special = getattr(keyboard.Key, token, None)
    if special is not None:
        return special
    if len(token) == 1:
        return keyboard.KeyCode.from_char(token)
    raise ValueError(
        f"Unrecognized hotkey token: {token!r}. Use a pynput Key name "
        f"(e.g. 'ctrl_r', 'alt_r', 'f9') or a single character."
    )


def _key_to_token(key) -> Optional[str]:  # noqa: ANN001
    """Inverse of _parse_key: converts a pynput key object back into the
    settings.json token format ('ctrl_r', 'f9', 'a', ...)."""
    if isinstance(key, keyboard.Key):
        return key.name
    if isinstance(key, keyboard.KeyCode) and key.char:
        return key.char.lower()
    return None


CAPTURE_TIMEOUT_SECONDS = 15.0


def capture_hotkey(timeout: float = CAPTURE_TIMEOUT_SECONDS) -> str:
    """Blocks the calling thread until the user presses one or more keys and
    then releases one of them, and returns the combo as a settings.json
    -compatible string (e.g. "ctrl_r" or "ctrl+alt").

    Meant to be called from a background thread (not the Tk thread) while
    the app's normal HoldToTalkHotkey listener is stopped, so the two
    listeners never compete for the same key events.

    Returns "" if nothing usable was captured -- either the release raced
    the press with no keys held, or `timeout` seconds elapsed with no key
    pressed at all. The timeout matters: the caller stops the real hotkey
    listener before calling this, so blocking forever here would leave the
    app with no working hotkey and no way back short of restarting it.
    """
    pressed: list = []
    seen: set = set()
    done = threading.Event()

    def on_press(key) -> None:  # noqa: ANN001
        if key is not None and key not in seen:
            seen.add(key)
            pressed.append(key)

    def on_release(key) -> bool:  # noqa: ANN001
        done.set()
        return False  # stop the listener

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    captured = done.wait(timeout=timeout)
    listener.stop()
    listener.join()

    if not captured:
        return ""

    tokens = [_key_to_token(key) for key in pressed]
    tokens = [t for t in tokens if t]
    return "+".join(tokens)


MODES = ("hold", "toggle")


class HoldToTalkHotkey:
    def __init__(
        self,
        combo: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        mode: str = "hold",
    ):
        if mode not in MODES:
            raise ValueError(f"Unknown hotkey mode {mode!r}; expected one of {MODES}.")
        self._keys = {_parse_key(token) for token in combo.split("+")}
        self._on_start = on_start
        self._on_stop = on_stop
        self._mode = mode
        self._pressed: set = set()
        # Whether every key in the combo is currently physically held down --
        # tracked in both modes, to debounce repeat key-repeat events while
        # the combo stays held (matters most in "toggle" mode, where holding
        # a key that auto-repeats must not fire multiple toggles).
        self._active = False
        # "toggle" mode only: whether a recording is logically in progress.
        self._recording = False
        # See suppressed(): set while the app is sending its own keystrokes.
        self._suppressed = False
        self._lock = threading.Lock()
        self._listener: Optional[keyboard.Listener] = None

    @contextmanager
    def suppressed(self):  # noqa: ANN201
        """Ignores key events for the duration of the block.

        Wrapped around the synthetic Ctrl+V that paste.py sends. A global
        listener cannot tell an app-generated keystroke from a real one, so
        without this the paste's own Ctrl press reads as a hotkey press: in
        "toggle" mode that silently starts a fresh recording the instant the
        previous transcript is pasted, which then inverts every subsequent
        tap (the next one "stops" a recording the user never started).
        """
        with self._lock:
            self._suppressed = True
        try:
            yield
        finally:
            with self._lock:
                self._suppressed = False
                # Key events were dropped rather than tracked while
                # suppressed, so whatever the synthetic keystrokes left
                # behind -- or a real key genuinely released during the
                # block -- would otherwise linger as a phantom held key.
                self._pressed.clear()
                self._active = False

    def _on_press(self, key) -> None:  # noqa: ANN001
        if key is None:
            return
        fire = None
        with self._lock:
            if self._suppressed:
                return
            self._pressed.add(key)
            # `key in self._keys` keeps an unrelated keystroke from
            # re-triggering the combo if a combo key is somehow still
            # recorded as held -- only a combo key can complete the combo.
            if (
                key in self._keys
                and not self._active
                and self._keys.issubset(self._pressed)
            ):
                self._active = True
                if self._mode == "hold":
                    fire = "start"
                else:
                    self._recording = not self._recording
                    fire = "start" if self._recording else "stop"
        if fire == "start":
            self._on_start()
        elif fire == "stop":
            self._on_stop()

    def _on_release(self, key) -> None:  # noqa: ANN001
        if key is None:
            return
        fire = False
        with self._lock:
            if self._suppressed:
                return
            self._pressed.discard(key)
            if self._active and not self._keys.issubset(self._pressed):
                self._active = False
                if self._mode == "hold":
                    fire = True
        if fire:
            self._on_stop()

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
