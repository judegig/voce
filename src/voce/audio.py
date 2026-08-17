"""Microphone capture for the duration the hotkey is held."""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

# Speech detection thresholds. See _voiced_seconds() and the comment in
# Recorder.stop() for why a recording has to clear these before any
# transcription engine sees it.
#
# A *peak* amplitude test used to stand in for this and let the exact bug it
# existed to prevent through anyway: peak is decided by a single sample, so
# one transient in an otherwise silent recording clears it -- and every
# recording ends with a transient, because releasing the hotkey is itself a
# key click into the mic. Mouse clicks, desk bumps and breaths did it too.
# Speech is not a spike, it is sustained energy, so measure that instead.
_FRAME_SECONDS = 0.03
# int16 RMS a 30ms frame must reach to count as voiced. Idle room tone sits
# well under this (tens); even quiet speech runs several hundred.
SPEECH_RMS_THRESHOLD = 180
# Total voiced audio a recording needs before it's worth transcribing. Below
# this it's treated as silence and dropped.
MIN_SPEECH_SECONDS = 0.25
# Voiced audio below this is real but too sparse to trust on its own -- a
# transcript from it is checked against Whisper's known silence
# hallucinations. See transcribe.is_silence_hallucination().
#
# Deliberately just above MIN_SPEECH_SECONDS: the window is narrow enough to
# hold only a single short word, which is all a hallucination ever is. Wider
# and it starts eating real dictation -- a briskly spoken "Thank you." lands
# around 0.42s of voiced audio and has to survive.
MARGINAL_SPEECH_SECONDS = 0.4


def list_input_devices() -> list[dict]:
    """Returns available audio input devices as [{"index": int, "name": str}, ...].

    Intended to be called once (e.g. at app startup) and cached by the
    caller -- re-querying on every recording or every tray-menu render is
    unnecessary and this function is not called from any hot path.

    On Windows, PortAudio surfaces every input device once per host API
    (MME, DirectSound, WASAPI, WDM-KS) -- the same physical mic shows up
    3-4 times under near-identical names (confirmed: an Intel Smart Sound
    array and a WO Mic virtual device each appeared 3x). Filtering to
    WASAPI, the modern host API, gives one clean entry per real device.
    This is a Windows-specific quirk; other platforms don't multiplex
    devices across host APIs this way, so they get the unfiltered list.
    """
    wasapi_index = None
    if sys.platform == "win32":
        for i, api in enumerate(sd.query_hostapis()):
            if "WASAPI" in api["name"]:
                wasapi_index = i
                break

    devices = []
    for index, info in enumerate(sd.query_devices()):
        if info.get("max_input_channels", 0) <= 0:
            continue
        if wasapi_index is not None and info["hostapi"] != wasapi_index:
            continue
        devices.append({"index": index, "name": info["name"]})
    return devices


def _voiced_seconds(audio: np.ndarray, sample_rate: float) -> float:
    """Returns how much of `audio` carries speech-level energy, in seconds.

    Splits the recording into short frames and totals the ones whose RMS
    clears SPEECH_RMS_THRESHOLD. Unlike a peak test this ignores isolated
    transients -- a key click is one or two frames, whereas even a single
    spoken word is dozens -- so the two are told apart by how long the
    energy lasts rather than by how loud its loudest instant was.
    """
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    frame_len = max(1, int(sample_rate * _FRAME_SECONDS))
    usable = len(mono) - (len(mono) % frame_len)
    if usable < frame_len:
        return 0.0
    # float32 before squaring: int16 RMS arithmetic overflows silently, and
    # the wrapped values read as near-zero energy.
    frames = mono[:usable].astype(np.float32).reshape(-1, frame_len)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    return float(np.count_nonzero(rms >= SPEECH_RMS_THRESHOLD) * _FRAME_SECONDS)


class Recorder:
    """Captures microphone audio while active; writes a 16-bit PCM WAV on stop.

    Holds the input stream open continuously and keeps the most recent
    `preroll_seconds` of audio in a ring buffer, which is prepended to each
    recording. People start speaking as they press the hotkey rather than
    after it, and losing even the first fraction of a second wrecks the
    transcript: measured against a real recording, cutting 150ms off the
    front turned "What are you saying" into "body shape", and 300ms into
    "How do you say it?". Opening the stream on keypress cannot fix this --
    no amount of speed beats a user who has already started talking -- so
    the audio has to already exist when the key goes down.

    The tradeoff: the mic stream stays open for the app's lifetime, so the
    OS shows the mic as in use. Nothing is written to disk or sent anywhere
    outside an active recording -- idle audio lives only in the ring buffer,
    a few hundred milliseconds of memory that is continuously overwritten.
    Set preroll_seconds=0 to keep the stream closed between recordings and
    accept the clipping.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        device: Optional[int] = None,
        preroll_seconds: float = 0.3,
    ):
        self.sample_rate = sample_rate  # preferred rate; see _resolve_sample_rate
        self._active_rate = float(sample_rate)  # what the open stream actually uses
        self.channels = channels
        self._device = device  # see the `device` property below
        self.preroll_seconds = preroll_seconds
        self._frames: list[np.ndarray] = []
        self._preroll: deque[np.ndarray] = deque()
        self._preroll_len = 0  # samples currently held in _preroll
        self._capturing = False
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self._start_time: float = 0.0

    @property
    def device(self) -> Optional[int]:
        return self._device

    @device.setter
    def device(self, value: Optional[int]) -> None:
        """Switching devices needs the persistent stream reopened against the
        new one -- unlike the old open-per-recording design, nothing else
        would ever pick the change up."""
        if value == self._device:
            return
        self._device = value
        self._close_stream()
        with self._lock:
            self._preroll.clear()
            self._preroll_len = 0
        if self.preroll_seconds > 0:
            self._ensure_stream()

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        with self._lock:
            if self._capturing:
                self._frames.append(indata.copy())
                return
            # Idle: keep only the tail end of the audio, discarding the rest.
            self._preroll.append(indata.copy())
            self._preroll_len += len(indata)
            while self._preroll and self._preroll_len > self._preroll_samples:
                self._preroll_len -= len(self._preroll.popleft())

    @property
    def _preroll_samples(self) -> int:
        """Sized against the rate the stream is actually running at, which is
        not always the configured one -- see _resolve_sample_rate."""
        return int(self._active_rate * self.preroll_seconds)

    @property
    def is_recording(self) -> bool:
        """True while audio is being captured for a recording. The stream may
        be open without this being True -- that is the idle pre-roll state."""
        return self._capturing

    def _close_stream(self) -> None:
        """Closes the current stream, if any. Safe to call when none is open."""
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception as exc:  # noqa: BLE001 - never block on teardown
            print(f"[voce] error closing audio stream: {exc}")
        finally:
            self._stream = None

    def _resolve_sample_rate(self, device: Optional[int]) -> float:
        """Finds a rate `device` will actually accept, preferring the
        configured one.

        Under WASAPI's shared mode a device only accepts its own native
        format, so a hardcoded rate silently locks out anything that doesn't
        happen to match: a phone-as-mic device here is 48kHz-only and
        rejected 16kHz outright, which used to send the recorder down its
        fall-back-to-default path and quietly record from the built-in mic
        instead of the one that was selected. The cloud engines resample
        server-side, so handing them 48kHz costs nothing (verified: 16kHz
        and 44.1kHz of the same phrase transcribed identically).
        """
        candidates = [float(self.sample_rate)]
        try:
            native = float(sd.query_devices(device)["default_samplerate"])
            if native not in candidates:
                candidates.append(native)
        except Exception:  # noqa: BLE001 - probing only; fall through to the list
            pass
        candidates.extend(r for r in (48000.0, 44100.0) if r not in candidates)

        for rate in candidates:
            try:
                sd.check_input_settings(
                    device=device, samplerate=rate,
                    channels=self.channels, dtype="int16",
                )
                return rate
            except Exception:  # noqa: BLE001 - unsupported rate, try the next
                continue
        # Nothing probed clean; let the configured rate raise a real error.
        return float(self.sample_rate)

    def _open_stream(self, device: Optional[int]) -> sd.InputStream:
        rate = self._resolve_sample_rate(device)
        stream = sd.InputStream(
            samplerate=rate,
            channels=self.channels,
            dtype="int16",
            device=device,
            callback=self._callback,
        )
        stream.start()
        self._active_rate = rate
        if rate != self.sample_rate:
            name = "system default"
            try:
                name = sd.query_devices(device)["name"]
            except Exception:  # noqa: BLE001 - naming is cosmetic
                pass
            print(
                f"[voce] {name!r} does not support {self.sample_rate}Hz; "
                f"recording at {rate:.0f}Hz instead"
            )
        return stream

    def _ensure_stream(self) -> None:
        """Opens the input stream if it isn't already running."""
        if self._stream is not None:
            return
        try:
            self._stream = self._open_stream(self._device)
        except Exception as exc:
            if self._device is None:
                raise
            # A previously-selected device (e.g. a USB mic) can disappear
            # between runs. Fall back to the system default rather than
            # leaving the hotkey listener dead until the app is restarted.
            #
            # Deliberately loud, and _device is left pointing at the chosen
            # device: recording from a mic the user didn't pick is worse than
            # not recording, and silently rewriting the selection to None hid
            # it -- the tray menu kept showing their choice while the audio
            # came from somewhere else entirely.
            print(
                f"[voce] WARNING: could not open input device {self._device!r} "
                f"({exc}). Recording from the SYSTEM DEFAULT mic instead -- "
                f"the device selected in the tray menu is NOT being used."
            )
            self._stream = self._open_stream(None)

    def arm(self) -> None:
        """Opens the stream so the pre-roll buffer starts filling immediately.

        Without this the stream would first open on the initial keypress,
        leaving exactly the first recording of each run with no pre-roll --
        the one case the buffer exists to cover. No-op when pre-roll is off.
        """
        if self.preroll_seconds > 0:
            self._ensure_stream()

    def close(self) -> None:
        """Releases the mic. Call on quit so the OS stops showing it in use."""
        self._close_stream()
        with self._lock:
            self._capturing = False
            self._preroll.clear()
            self._preroll_len = 0

    def start(self) -> None:
        self._ensure_stream()
        with self._lock:
            # Seed the recording with the buffered audio from just before the
            # keypress, which is where the first syllable actually lives.
            self._frames = list(self._preroll)
            self._preroll.clear()
            self._preroll_len = 0
            self._capturing = True
        self._start_time = time.monotonic()

    def stop(
        self, tail_seconds: float = 0.0
    ) -> tuple[Optional[Path], float, float]:
        """Stops recording and writes a temp WAV file.

        Keeps capturing for `tail_seconds` before closing the stream. People
        release the hotkey as they finish the last syllable rather than after
        it, and Whisper drops a word it only half hears: measured against a
        real recording, chopping 300ms off the end turned "What are you
        saying" into "What are you?", while 150ms still transcribed intact.
        The tail buys back that overlap. Callers must not run this on the
        hotkey listener thread -- it sleeps.

        Returns (path_or_none, duration_seconds, voiced_seconds), where
        duration is how long the hotkey was held and voiced is how much of
        that carried speech-level energy. path is None if start() was never
        called, no audio frames were captured, or the recording held less
        than MIN_SPEECH_SECONDS of speech.
        """
        if not self._capturing:
            return None, 0.0, 0.0

        # Measured before the tail sleep so it reflects how long the hotkey
        # was actually held. Counting the tail would push every accidental
        # tap past the caller's minimum-duration guard.
        duration = time.monotonic() - self._start_time

        if tail_seconds > 0:
            time.sleep(tail_seconds)

        with self._lock:
            self._capturing = False
            frames, self._frames = self._frames, []
            # The idle ring buffer restarts empty rather than carrying over
            # audio from the recording that just ended -- otherwise the tail
            # of one dictation would be prepended to the start of the next.
            self._preroll.clear()
            self._preroll_len = 0

        if self.preroll_seconds <= 0:
            # Pre-roll disabled: nothing needs the stream between recordings,
            # so release the mic instead of holding it open.
            self._close_stream()

        if not frames:
            return None, duration, 0.0

        audio = np.concatenate(frames, axis=0)
        voiced = _voiced_seconds(audio, self._active_rate)

        if voiced < MIN_SPEECH_SECONDS:
            # Whisper-family models (whisper.cpp and the Groq/OpenAI Whisper
            # APIs alike) have no "there's no speech here" output -- fed
            # near-silent audio, they hallucinate a phrase from their
            # training data instead, almost always "Thank you." (a lot of
            # that data is YouTube videos ending in "thanks for watching").
            # Dropping silent recordings here, before any engine ever sees
            # them, avoids that for all three engines at once.
            return None, duration, voiced

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()

        with wave.open(str(tmp_path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # int16
            # The rate the stream actually ran at, not the configured one --
            # tagging 48kHz audio as 16kHz would play (and transcribe) as
            # slow, deep gibberish.
            wf.setframerate(int(self._active_rate))
            wf.writeframes(audio.tobytes())

        return tmp_path, duration, voiced
