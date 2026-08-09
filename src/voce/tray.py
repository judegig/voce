"""System tray / menu-bar icon: on-off toggle, launch-at-login toggle,
input device picker, language picker, auto-detect toggle, quit.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

from .audio import list_input_devices

# How often to check for input devices being plugged in or unplugged while
# the tray menu isn't open. pystray's Windows backend builds a native HMENU
# once and never re-walks it on right-click, so a newly connected mic would
# otherwise stay invisible until the app restarts -- this poll plus
# icon.update_menu() is what picks it up.
DEVICE_POLL_INTERVAL_SECONDS = 2.0


def _make_icon_image(color: str) -> Image.Image:
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, size - 8, size - 8), fill=color)
    return image


class TrayApp:
    def __init__(
        self,
        on_toggle_enabled: Callable[[bool], None],
        on_toggle_login: Callable[[bool], None],
        on_select_device: Callable[[Optional[int]], None],
        on_select_language: Callable[[str], None],
        on_toggle_auto_detect: Callable[[bool], None],
        on_change_hotkey: Callable[[], None],
        on_toggle_tap_mode: Callable[[bool], None],
        on_quit: Callable[[], None],
        enabled: bool = True,
        launch_at_login: bool = False,
        devices: Optional[list[dict]] = None,
        current_device: Optional[int] = None,
        languages: Optional[dict[str, str]] = None,
        current_language: str = "en",
        auto_detect_language: bool = False,
        tap_to_toggle: bool = False,
    ):
        self._on_toggle_enabled = on_toggle_enabled
        self._on_toggle_login = on_toggle_login
        self._on_select_device = on_select_device
        self._on_select_language = on_select_language
        self._on_toggle_auto_detect = on_toggle_auto_detect
        self._on_change_hotkey = on_change_hotkey
        self._on_toggle_tap_mode = on_toggle_tap_mode
        self._on_quit = on_quit

        self._enabled = enabled
        self._launch_at_login = launch_at_login
        # Seeded from the startup enumeration (see app.py) but kept fresh
        # after that by _poll_devices, not a one-time snapshot.
        self._devices = devices or []
        self._current_device = current_device
        self._languages = languages or {}
        self._current_language = current_language
        self._auto_detect_language = auto_detect_language
        self._tap_to_toggle = tap_to_toggle

        self._icon: Optional[pystray.Icon] = None
        self._stop_polling = threading.Event()

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "Enabled",
                self._handle_toggle_enabled,
                checked=lambda item: self._enabled,
            ),
            pystray.MenuItem("Input Device", self._build_device_submenu()),
            pystray.MenuItem("Language", self._build_language_submenu()),
            pystray.MenuItem(
                "Auto-detect Language",
                self._handle_toggle_auto_detect,
                checked=lambda item: self._auto_detect_language,
            ),
            pystray.MenuItem(
                "Launch at Login",
                self._handle_toggle_login,
                checked=lambda item: self._launch_at_login,
            ),
            pystray.MenuItem("Change Hotkey...", self._handle_change_hotkey),
            pystray.MenuItem(
                "Tap to Start/Stop (instead of Hold)",
                self._handle_toggle_tap_mode,
                checked=lambda item: self._tap_to_toggle,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Voce", self._handle_quit),
        )

    def _make_device_action(self, index: Optional[int]) -> Callable:
        # pystray's action validator inspects __code__.co_argcount and
        # rejects anything but exactly 0/1/2 declared params -- it does
        # NOT know some have defaults, so a 3-param default-capture lambda
        # (icon, item, idx=idx) is rejected outright. A plain closure over
        # this method's own `index` parameter has a clean 2-arg signature
        # and still captures a distinct value per call.
        def action(icon, item) -> None:  # noqa: ANN001
            self._handle_select_device(index)

        return action

    def _device_submenu_items(self):
        # A generator handed to pystray.Menu rather than a pre-built item
        # list: pystray re-invokes this every time the menu is rebuilt (see
        # icon.update_menu() in _poll_devices), so it must read self._devices
        # fresh each call rather than closing over a snapshot from whenever
        # the submenu was first constructed.
        yield pystray.MenuItem(
            "System Default",
            self._make_device_action(None),
            checked=lambda item: self._current_device is None,
        )
        for device in self._devices:
            idx = device["index"]
            yield pystray.MenuItem(
                device["name"],
                self._make_device_action(idx),
                checked=lambda item, idx=idx: self._current_device == idx,
            )

    def _build_device_submenu(self) -> pystray.Menu:
        return pystray.Menu(self._device_submenu_items)

    def _make_language_action(self, code: str) -> Callable:
        def action(icon, item) -> None:  # noqa: ANN001
            self._handle_select_language(code)

        return action

    def _build_language_submenu(self) -> pystray.Menu:
        items = []
        for code, name in self._languages.items():
            items.append(
                pystray.MenuItem(
                    name,
                    self._make_language_action(code),
                    checked=lambda item, code=code: (
                        not self._auto_detect_language and self._current_language == code
                    ),
                )
            )
        return pystray.Menu(*items)

    def _handle_toggle_enabled(self, icon, item) -> None:  # noqa: ANN001
        self._enabled = not self._enabled
        self._on_toggle_enabled(self._enabled)
        self._refresh_icon()

    def _handle_toggle_login(self, icon, item) -> None:  # noqa: ANN001
        self._launch_at_login = not self._launch_at_login
        self._on_toggle_login(self._launch_at_login)

    def _handle_select_device(self, index: Optional[int]) -> None:
        self._current_device = index
        self._on_select_device(index)

    def _handle_select_language(self, code: str) -> None:
        self._current_language = code
        self._auto_detect_language = False
        self._on_select_language(code)

    def _handle_toggle_auto_detect(self, icon, item) -> None:  # noqa: ANN001
        self._auto_detect_language = not self._auto_detect_language
        self._on_toggle_auto_detect(self._auto_detect_language)

    def _handle_change_hotkey(self, icon, item) -> None:  # noqa: ANN001
        self._on_change_hotkey()

    def _handle_toggle_tap_mode(self, icon, item) -> None:  # noqa: ANN001
        self._tap_to_toggle = not self._tap_to_toggle
        self._on_toggle_tap_mode(self._tap_to_toggle)

    def _handle_quit(self, icon, item) -> None:  # noqa: ANN001
        self._on_quit()
        icon.stop()

    def _refresh_icon(self) -> None:
        if self._icon is not None:
            self._icon.icon = _make_icon_image("#4ade80" if self._enabled else "#6b7280")

    def _poll_devices(self) -> None:
        """Background loop: re-enumerates input devices periodically and
        rebuilds the native menu when the list changes, so a mic plugged in
        (or unplugged) after startup shows up without an app restart.

        Only calls update_menu() on an actual change, not every tick --
        pystray's Windows backend destroys and recreates the native HMENU
        on each call, and doing that while the menu happens to be open
        could pull it out from under an in-progress click.
        """
        while not self._stop_polling.wait(DEVICE_POLL_INTERVAL_SECONDS):
            try:
                devices = list_input_devices()
            except Exception as exc:  # noqa: BLE001 - polling only, never fatal
                print(f"[voce] error polling input devices: {exc}")
                continue
            if devices != self._devices:
                self._devices = devices
                if self._icon is not None:
                    self._icon.update_menu()

    def run_in_background(self) -> None:
        image = _make_icon_image("#4ade80" if self._enabled else "#6b7280")
        self._icon = pystray.Icon("voce", image, "Voce Dictation", self._build_menu())
        threading.Thread(target=self._icon.run, daemon=True).start()
        threading.Thread(target=self._poll_devices, daemon=True).start()

    def stop(self) -> None:
        self._stop_polling.set()
        if self._icon is not None:
            self._icon.stop()
