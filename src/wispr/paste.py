"""Pastes text at the current cursor position via the clipboard, restoring
whatever was on the clipboard beforehand.

Note: this only preserves *text* clipboard contents across the paste (via
pyperclip). If the clipboard held an image or file selection, that is not
restored — a known limitation of the cross-platform clipboard API.
"""
from __future__ import annotations

import sys
import time

import pyperclip
from pynput.keyboard import Controller, Key

_controller = Controller()


def paste_text(text: str, settle_delay: float = 0.05) -> None:
    if not text:
        return

    try:
        previous = pyperclip.paste()
    except Exception:  # noqa: BLE001 - clipboard can hold non-text data
        previous = None

    pyperclip.copy(text)
    time.sleep(settle_delay)  # give the OS a moment to register the new clipboard

    modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
    with _controller.pressed(modifier):
        _controller.press("v")
        _controller.release("v")

    time.sleep(settle_delay)

    if previous is not None:
        try:
            pyperclip.copy(previous)
        except Exception:  # noqa: BLE001
            pass
