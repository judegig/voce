"""Runs the raw transcript through Claude to strip filler words, fix
punctuation, and match dictation casing. Falls back to the raw transcript
if cleanup is disabled or no API key is configured, so dictation still
works with zero cloud dependency.
"""
from __future__ import annotations

import os

import anthropic

from .config import Settings

SYSTEM_PROMPT = (
    "You clean up raw speech-to-text dictation. Remove filler words and false "
    "starts (um, uh, like, you know, I mean), fix punctuation and capitalization, "
    "and keep the speaker's own words and meaning otherwise unchanged. Match a "
    "natural written dictation style. Do not summarize, answer, or add anything "
    "that wasn't said. Return only the cleaned text, with no preamble or "
    "explanation."
)


def clean_transcript(raw_text: str, settings: Settings) -> str:
    if not raw_text.strip():
        return raw_text

    if not settings.cleanup.enabled:
        return raw_text

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return raw_text

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=settings.cleanup.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": raw_text}],
        )
    except Exception as exc:  # noqa: BLE001 - cleanup must never break dictation
        print(f"[voce] cleanup failed, pasting raw transcript instead: {exc}")
        return raw_text

    text = "".join(block.text for block in response.content if block.type == "text")
    return text.strip() or raw_text
