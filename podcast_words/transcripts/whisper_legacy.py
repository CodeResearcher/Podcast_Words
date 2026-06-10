"""Adapter for the legacy Whisper output format used by the original PUFO pipeline.

Each episode_N.txt holds a Python literal list of chunk dicts, e.g.
    [{'timestamp': (0.0, 85.52), 'text': ' ... '}, ...]
"""

from __future__ import annotations

import ast
from pathlib import Path

from podcast_words.models import Transcript, TranscriptCue


def _to_ms(seconds) -> int:
    try:
        return int(float(seconds) * 1000)
    except (TypeError, ValueError):
        return 0


def parse(content: str) -> Transcript:
    data = ast.literal_eval(content)
    cues: list[TranscriptCue] = []
    previous_end = 0
    for entry in data:
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        timestamp = entry.get("timestamp") or (None, None)
        start_raw, end_raw = (timestamp + (None, None))[:2] if isinstance(timestamp, (list, tuple)) else (None, None)
        start_ms = _to_ms(start_raw) if start_raw is not None else previous_end
        end_ms = _to_ms(end_raw) if end_raw is not None else start_ms
        if end_ms < start_ms:
            end_ms = start_ms
        previous_end = end_ms
        cues.append(TranscriptCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return Transcript(cues=cues)


def parse_file(path: str | Path) -> Transcript:
    return parse(Path(path).read_text(encoding="utf-8"))


def looks_like_legacy(content: str) -> bool:
    """Heuristic: legacy files start with a Python list literal."""
    stripped = content.lstrip()
    return stripped.startswith("[{") or stripped.startswith("[ {")
