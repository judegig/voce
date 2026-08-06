"""Whisper-family language codes and display names.

Shared across all three transcription engines (local whisper.cpp, Groq,
OpenAI) since all three speak the same Whisper language vocabulary.

This is a curated subset for the tray menu, not the full ~99-language
Whisper set -- a flat tray submenu with 99 entries is unusable. Any
Whisper-supported code not listed here still works if set directly in
settings.json (transcription.language); this list only bounds what's
practical to show as a picker.
"""
from __future__ import annotations

# code -> display name, in the order they should appear in the tray menu.
LANGUAGES: dict[str, str] = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "ar": "Arabic",
    "hi": "Hindi",
    "tr": "Turkish",
    "pl": "Polish",
    "sv": "Swedish",
    "da": "Danish",
    "no": "Norwegian",
    "fi": "Finnish",
    "el": "Greek",
    "he": "Hebrew",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "uk": "Ukrainian",
}
