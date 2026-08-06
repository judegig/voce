"""Microphone capture for the duration the hotkey is held."""
from __future__ import annotations

import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd


def list_input_devices() -> list[dict]:
    """Returns available audio input devices as [{"index": int, "name": str}, ...].

    Intended to be called once (e.g. at app startup) and cached by the
    caller -- re-querying on every recording or every tray-menu render is
    unnecessary and this function is not called from any hot path.
    """
    devices = []
    for index, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) > 0:
            devices.append({"index": index, "name": info["name"]})
    return devices


class Recorder:
    """Captures microphone audio while active; writes a 16-bit PCM WAV on stop."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        device: Optional[int] = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device  # None = system default input device; read
        # fresh on every start() call, so changing it takes effect on the
        # next recording with no restart needed.
        self._frames: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self._start_time: float = 0.0

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            self._frames.append(indata.copy())

    def start(self) -> None:
        with self._lock:
            self._frames = []
        self._start_time = time.monotonic()
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                device=self.device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            if self.device is None:
                raise
            # A previously-selected device (e.g. a USB mic) can disappear
            # between runs. Fall back to the system default rather than
            # leaving the hotkey listener dead until the app is restarted.
            print(
                f"[wispr] failed to open input device {self.device!r} ({exc}); "
                f"falling back to system default"
            )
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                device=None,
                callback=self._callback,
            )
            self._stream.start()

    def stop(self) -> tuple[Optional[Path], float]:
        """Stops recording and writes a temp WAV file.

        Returns (path_or_none, duration_seconds). path is None if start() was
        never called or no audio frames were captured.
        """
        if self._stream is None:
            return None, 0.0

        self._stream.stop()
        self._stream.close()
        self._stream = None
        duration = time.monotonic() - self._start_time

        with self._lock:
            frames, self._frames = self._frames, []

        if not frames:
            return None, duration

        audio = np.concatenate(frames, axis=0)

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()

        with wave.open(str(tmp_path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # int16
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio.tobytes())

        return tmp_path, duration
