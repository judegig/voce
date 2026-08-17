"""Speech-to-text: local whisper.cpp, or the Groq / OpenAI Whisper APIs."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from .config import Settings


class TranscriptionError(Exception):
    """Raised when the configured transcription engine fails to produce text."""


@dataclass
class TranscriptionResult:
    text: str
    # The language actually used: the forced code, the auto-detected code,
    # or None if the engine gave us no way to know either.
    language: Optional[str] = None


# Placeholders whisper.cpp and the APIs emit for audio they found no speech
# in. Never something a person dictated, so these are dropped on sight.
_NON_SPEECH_MARKERS = frozenset({
    "blank_audio", "silence", "music", "inaudible", "no audio", "sound",
    "applause", "background noise", "upbeat music",
})

# What Whisper hallucinates *as speech* when handed near-silence: stock
# phrases from the YouTube captions in its training data. Only rejected when
# the audio was already marginal (see is_silence_hallucination) -- "thank
# you" is a real thing to dictate, and a confidently-voiced one is kept.
_SILENCE_PHRASES = frozenset({
    "thank you", "thank you very much", "thank you so much",
    "thanks for watching", "thanks for watching the video",
    "thank you for watching", "thanks", "you", "bye", "bye bye", "okay",
    "please subscribe", "subscribe to my channel", "see you next time",
    "subtitles by the amara.org community",
})


def is_silence_hallucination(text: str, *, marginal_audio: bool) -> bool:
    """True if `text` is Whisper inventing speech out of near-silence.

    The energy gate in audio.py stops most of these by never sending silent
    audio at all, but it can only measure loudness -- a recording of a fan,
    typing, or a couple of stray syllables of room noise clears it and still
    gives Whisper nothing to work with. So the transcript gets checked too.

    Matches the *whole* transcript only. "Thank you." alone off marginal
    audio is the hallucination; "thank you" inside a real sentence is the
    user talking, and a longer transcript containing one of these phrases is
    never touched.
    """
    normalized = re.sub(r"\s+", " ", text).strip().strip("[]()*").lower()
    normalized = normalized.strip(" .!?,-–—…").strip()
    if not normalized:
        return True
    if normalized in _NON_SPEECH_MARKERS:
        return True
    return marginal_audio and normalized in _SILENCE_PHRASES


def transcribe(audio_path: Path, settings: Settings) -> TranscriptionResult:
    engine = settings.transcription.engine
    if engine == "local":
        return _transcribe_local(audio_path, settings)
    if engine == "groq":
        return _transcribe_groq(audio_path, settings)
    if engine == "openai":
        return _transcribe_openai(audio_path, settings)
    raise TranscriptionError(
        f"Unknown transcription engine {engine!r} in settings.json "
        f"(expected 'local', 'groq', or 'openai')."
    )


def _transcribe_local(audio_path: Path, settings: Settings) -> TranscriptionResult:
    cfg = settings.transcription.local
    binary = Path(cfg.binary_path)
    model = Path(cfg.model_path)

    if not binary.exists():
        raise TranscriptionError(
            f"whisper.cpp binary not found at '{binary}'. See README.md for build "
            f"instructions, or point transcription.local.binary_path at your build."
        )
    if not model.exists():
        raise TranscriptionError(
            f"Whisper model not found at '{model}'. See README.md for download "
            f"instructions, or point transcription.local.model_path at your model."
        )

    auto_detect = settings.transcription.auto_detect_language
    lang_arg = "auto" if auto_detect else settings.transcription.language

    if (auto_detect or lang_arg != "en") and model.name.endswith(".en.bin"):
        # English-only ggml models (filename ends in ".en.bin", e.g. the
        # README's default ggml-small.en.bin) ignore -l entirely -- they
        # can only ever produce English. Without this, switching language
        # or enabling auto-detect in the tray would silently do nothing.
        print(
            f"[voce] '{model.name}' is an English-only model; language "
            f"selection and auto-detect have no effect on it. Use a "
            f"non-'.en' model (e.g. ggml-small.bin) for other languages."
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_stub = Path(tmp_dir) / "out"
        cmd = [
            str(binary),
            "-m", str(model),
            "-f", str(audio_path),
            "-of", str(out_stub),
            "-otxt",
            "-nt",  # no timestamps
            "-np",  # no progress printing to stdout
            "-l", lang_arg,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
        except subprocess.TimeoutExpired as exc:
            raise TranscriptionError("whisper.cpp timed out after 120s") from exc

        if result.returncode != 0:
            raise TranscriptionError(f"whisper.cpp failed: {result.stderr.strip()}")

        out_file = out_stub.with_suffix(".txt")
        if not out_file.exists():
            raise TranscriptionError("whisper.cpp produced no output file")
        text = out_file.read_text(encoding="utf-8").strip()

        detected_language = lang_arg
        if auto_detect:
            # Best-effort: whisper.cpp prints a line like
            # "whisper_full_with_state: auto-detected language: en (p = 0.99...)"
            # to stderr when -l auto is used. This format is NOT a stable,
            # documented CLI contract -- it can change across whisper.cpp
            # builds/versions. Falls back to the literal "auto" if the
            # pattern isn't found, rather than raising.
            match = re.search(r"auto-detected language:\s*(\w+)", result.stderr)
            detected_language = match.group(1) if match else "auto"

        return TranscriptionResult(text=text, language=detected_language)


def _vocabulary_prompt(settings: Settings) -> Optional[str]:
    """Joins settings.transcription.vocabulary_hints into the Groq/OpenAI
    API's "prompt" hint, or None if the list is empty. Whisper's prompt
    parameter biases transcription toward the words it contains -- it's a
    hint, not a strict allowlist, so it helps most with names/jargon the
    model otherwise mishears rather than guaranteeing exact matches."""
    hints = settings.transcription.vocabulary_hints
    return ", ".join(hints) if hints else None


def _transcribe_groq(audio_path: Path, settings: Settings) -> TranscriptionResult:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise TranscriptionError("GROQ_API_KEY is not set in .env")

    auto_detect = settings.transcription.auto_detect_language
    data = {
        "model": settings.transcription.groq_model,
        # verbose_json (instead of plain "text") is required to get the
        # detected/used language back from the API at all.
        "response_format": "verbose_json",
    }
    if not auto_detect:
        data["language"] = settings.transcription.language
    prompt = _vocabulary_prompt(settings)
    if prompt:
        data["prompt"] = prompt

    with open(audio_path, "rb") as f:
        response = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (audio_path.name, f, "audio/wav")},
            data=data,
            timeout=60,
        )
    if response.status_code != 200:
        raise TranscriptionError(
            f"Groq API error {response.status_code}: {response.text}"
        )

    payload = response.json()
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    return TranscriptionResult(text=text, language=language)


def _transcribe_openai(audio_path: Path, settings: Settings) -> TranscriptionResult:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionError("OPENAI_API_KEY is not set in .env")

    auto_detect = settings.transcription.auto_detect_language
    data = {
        "model": settings.transcription.openai_model,
        "response_format": "verbose_json",
    }
    if not auto_detect:
        data["language"] = settings.transcription.language
    prompt = _vocabulary_prompt(settings)
    if prompt:
        data["prompt"] = prompt

    with open(audio_path, "rb") as f:
        response = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (audio_path.name, f, "audio/wav")},
            data=data,
            timeout=60,
        )
    if response.status_code != 200:
        raise TranscriptionError(
            f"OpenAI API error {response.status_code}: {response.text}"
        )

    payload = response.json()
    text = str(payload.get("text", "")).strip()
    language = payload.get("language")
    return TranscriptionResult(text=text, language=language)
