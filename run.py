"""Entry point for Voce — a lightweight, offline-first, system-wide
dictation tool. Hold the configured hotkey to record, release to
transcribe + clean up + paste at the cursor.

Usage:
    python run.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from voce.app import main  # noqa: E402

if __name__ == "__main__":
    main()
