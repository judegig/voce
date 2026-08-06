"""Loads settings.json and .env, and provides typed access to both."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = PROJECT_ROOT / "settings.json"
ENV_PATH = PROJECT_ROOT / ".env"


@dataclass
class LocalWhisperConfig:
    binary_path: str = "whisper.cpp/build/bin/whisper-cli"
    model_path: str = "whisper.cpp/models/ggml-small.en.bin"


@dataclass
class TranscriptionConfig:
    engine: str = "local"  # "local" | "groq" | "openai"
    local: LocalWhisperConfig = field(default_factory=LocalWhisperConfig)
    groq_model: str = "whisper-large-v3-turbo"
    openai_model: str = "whisper-1"
    language: str = "en"  # used when auto_detect_language is False
    auto_detect_language: bool = False


@dataclass
class CleanupConfig:
    enabled: bool = True
    model: str = "claude-haiku-4-5"


@dataclass
class Settings:
    hotkey: str = "ctrl_r"
    hotkey_mode: str = "hold"  # "hold" (hold to talk) | "toggle" (tap to start/stop)
    sample_rate: int = 16000
    input_device: Optional[int] = None  # None = system default input device
    transcription: TranscriptionConfig = field(default_factory=TranscriptionConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    launch_at_login: bool = False


HOTKEY_MODES = ("hold", "toggle")


def _valid_hotkey_mode(value: object) -> str:
    """settings.json is hand-editable (the README says so), so a typo here
    must not take the app down. Anything unrecognized falls back to the
    default with a warning instead of raising at construction time."""
    if value in HOTKEY_MODES:
        return str(value)
    print(
        f"[wispr] invalid hotkey_mode {value!r} in settings.json; "
        f"expected one of {HOTKEY_MODES}. Falling back to "
        f"{Settings.hotkey_mode!r}."
    )
    return Settings.hotkey_mode


def _settings_from_dict(data: dict) -> Settings:
    transcription_data = data.get("transcription", {})
    local_data = transcription_data.get("local", {})
    cleanup_data = data.get("cleanup", {})

    return Settings(
        hotkey=data.get("hotkey", Settings.hotkey),
        hotkey_mode=_valid_hotkey_mode(data.get("hotkey_mode", Settings.hotkey_mode)),
        sample_rate=data.get("sample_rate", Settings.sample_rate),
        input_device=data.get("input_device", Settings.input_device),
        transcription=TranscriptionConfig(
            engine=transcription_data.get("engine", TranscriptionConfig.engine),
            local=LocalWhisperConfig(
                binary_path=local_data.get("binary_path", LocalWhisperConfig.binary_path),
                model_path=local_data.get("model_path", LocalWhisperConfig.model_path),
            ),
            groq_model=transcription_data.get("groq_model", TranscriptionConfig.groq_model),
            openai_model=transcription_data.get("openai_model", TranscriptionConfig.openai_model),
            language=transcription_data.get("language", TranscriptionConfig.language),
            auto_detect_language=transcription_data.get(
                "auto_detect_language", TranscriptionConfig.auto_detect_language
            ),
        ),
        cleanup=CleanupConfig(
            enabled=cleanup_data.get("enabled", CleanupConfig.enabled),
            model=cleanup_data.get("model", CleanupConfig.model),
        ),
        launch_at_login=data.get("launch_at_login", Settings.launch_at_login),
    )


def load_settings() -> Settings:
    """Loads .env into the process environment and settings.json into a Settings
    object. Creates settings.json with defaults on first run."""
    load_dotenv(ENV_PATH)
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # A hand-edited settings.json with a stray comma shouldn't stop
            # the app from starting -- run on defaults and say why.
            print(
                f"[wispr] could not read settings.json ({exc}); "
                f"using default settings for this run."
            )
            return Settings()
        return _settings_from_dict(data)
    settings = Settings()
    save_settings(settings)
    return settings


def save_settings(settings: Settings) -> None:
    SETTINGS_PATH.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
