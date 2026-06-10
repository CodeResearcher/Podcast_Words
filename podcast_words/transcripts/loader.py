"""Dispatch transcript files to the correct adapter based on extension/content."""

from __future__ import annotations

from pathlib import Path

from podcast_words.models import Transcript
from podcast_words.transcripts import plain, srt, ttml, vtt, whisper_legacy

TRANSCRIPT_EXTENSIONS = {".vtt", ".srt", ".ttml", ".xml", ".txt"}


def load_transcript(path: str | Path) -> Transcript:
    """Load any supported transcript format into the unified model.

    The .txt extension is ambiguous: the original pipeline wrote Python-literal
    Whisper output there, while a manual import may be plain prose. We sniff the
    content to pick the right adapter.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".vtt":
        return vtt.parse_file(path)
    if suffix == ".srt":
        return srt.parse_file(path)
    if suffix in (".ttml", ".xml"):
        return ttml.parse_file(path)
    if suffix == ".txt":
        content = path.read_text(encoding="utf-8")
        if whisper_legacy.looks_like_legacy(content):
            return whisper_legacy.parse(content)
        return plain.parse(content)

    raise ValueError(
        f"Unsupported transcript format '{suffix}' for {path}. "
        f"Supported: {sorted(TRANSCRIPT_EXTENSIONS)}."
    )
