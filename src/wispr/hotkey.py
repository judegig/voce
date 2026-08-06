"""Global hold-to-talk hotkey listener.

Supports a single key (e.g. "ctrl_r", "f9") or a "+"-separated combo
(e.g. "ctrl+alt"). Recording starts once every key in the combo is held
down, and stops the moment any one of them is released.
"""
from __future__ import annotations

import threading
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


def capture_hotkey() -> str:
    """Blocks the calling thread until the user presses one or more keys and
    then releases one of them, and returns the combo as a settings.json
    -compatible string (e.g. "ctrl_r" or "ctrl+alt").

    Meant to be called from a background thread (not the Tk thread) while
    the app's normal HoldToTalkHotkey listener is stopped, so the two
    listeners never compete for the same key events. Returns "" if nothing
    usable was captured (e.g. the release raced the press with no keys held).
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
    done.wait()
    listener.stop()
    listener.join()

    tokens = [_key_to_token(key) for key in pressed]
    tokens = [t for t in tokens if t]
    return "+".join(tokens)


class HoldToTalkHotkey:
    def __init__(
        self,
        combo: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ):
        self._keys = {_parse_key(token) for token in combo.split("+")}
        self._on_start = on_start
        self._on_stop = on_stop
        self._pressed: set = set()
        self._active = False
        self._lock = threading.Lock()
        self._listener: Optional[keyboard.Listener] = None

    def _on_press(self, key) -> None:  # noqa: ANN001
        if key is None:
            return
        with self._lock:
            self._pressed.add(key)
            if not self._active and self._keys.issubset(self._pressed):
                self._active = True
                should_fire = True
            else:
                should_fire = False
        if should_fire:
            self._on_start()

    def _on_release(self, key) -> None:  # noqa: ANN001
        if key is None:
            return
        with self._lock:
            self._pressed.discard(key)
            if self._active and not self._keys.issubset(self._pressed):
                self._active = False
                should_fire = True
            else:
                should_fire = False
        if should_fire:
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
