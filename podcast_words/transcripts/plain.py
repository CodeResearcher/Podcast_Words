"""Plain-text transcript adapter: whole-file text with no timestamps."""

from __future__ import annotations

from pathlib import Path

from podcast_words.models import Transcript, TranscriptCue


def parse(content: str) -> Transcript:
    text = content.strip()
    if not text:
        return Transcript(cues=[])
    return Transcript(cues=[TranscriptCue(start_ms=0, end_ms=0, text=text)])


def parse_file(path: str | Path) -> Transcript:
    return parse(Path(path).read_text(encoding="utf-8"))
