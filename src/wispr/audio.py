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

# int16 peak amplitude below which a recording is treated as silence rather
# than sent to a transcription engine. Room tone/mic noise from an idle
# input typically peaks well under this; real speech, even quiet, clears it
# easily. See the comment in Recorder.stop() for why this check exists.
SILENCE_PEAK_AMPLITUDE = 500


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

    @property
    def is_recording(self) -> bool:
        """True while an input stream is open (i.e. audio is being captured)."""
        return self._stream is not None

    def _close_stream(self) -> None:
        """Closes the current stream, if any. Safe to call when none is open."""
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception as exc:  # noqa: BLE001 - never block on teardown
            print(f"[wispr] error closing audio stream: {exc}")
        finally:
            self._stream = None

    def start(self) -> None:
        # Defensive: if a stream is somehow already open (e.g. the hotkey
        # listener was hot-swapped mid-recording in toggle mode, so its
        # "am I recording" state was reset), close it first. Without this
        # the old stream is silently orphaned but stays ACTIVE -- the mic
        # keeps capturing after the pill has already been hidden, which is
        # both a device-handle leak and a privacy problem.
        self._close_stream()

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
        never called, no audio frames were captured, or the recording was
        near-silent (see SILENCE_PEAK_AMPLITUDE).
        """
        if self._stream is None:
            return None, 0.0

        # Via _close_stream so a failure mid-teardown still clears
        # self._stream rather than leaving a half-closed stream behind.
        self._close_stream()
        duration = time.monotonic() - self._start_time

        with self._lock:
            frames, self._frames = self._frames, []

        if not frames:
            return None, duration

        audio = np.concatenate(frames, axis=0)

        if np.abs(audio).max() < SILENCE_PEAK_AMPLITUDE:
            # Whisper-family models (whisper.cpp and the Groq/OpenAI Whisper
            # APIs alike) have no "there's no speech here" output -- fed
            # near-silent audio, they hallucinate a phrase from their
            # training data instead, almost always "Thank you." (a lot of
            # that data is YouTube videos ending in "thanks for watching").
            # Dropping silent recordings here, before any engine ever sees
            # them, avoids that for all three engines at once.
            return None, duration

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()

        with wave.open(str(tmp_path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # int16
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio.tobytes())

        return tmp_path, duration
