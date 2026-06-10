"""SubRip (.srt) parsing into the unified Transcript model."""

from __future__ import annotations

import re
from pathlib import Path

from podcast_words.models import Transcript, TranscriptCue
from podcast_words.transcripts.vtt import timestamp_to_ms

_TIMING_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


def parse(content: str) -> Transcript:
    cues: list[TranscriptCue] = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        timing_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing_idx is None:
            continue
        match = _TIMING_RE.search(lines[timing_idx])
        if not match:
            continue
        start_ms = timestamp_to_ms(match.group("start"))
        end_ms = timestamp_to_ms(match.group("end"))
        text = " ".join(lines[timing_idx + 1 :]).strip()
        if text:
            cues.append(TranscriptCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return Transcript(cues=cues)


def parse_file(path: str | Path) -> Transcript:
    return parse(Path(path).read_text(encoding="utf-8"))
