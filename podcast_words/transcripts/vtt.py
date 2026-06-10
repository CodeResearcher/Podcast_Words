"""WebVTT parsing and writing.

VTT is the canonical on-disk format, so this module both reads imported VTT
files and writes the transcripts produced by every other adapter.
"""

from __future__ import annotations

import re
from pathlib import Path

from podcast_words.models import Transcript, TranscriptCue

_TIMING_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)
_VOICE_RE = re.compile(r"<v\s+([^>]+)>(.*)", re.IGNORECASE)
_TAG_RE = re.compile(r"</?[^>]+>")


def timestamp_to_ms(value: str) -> int:
    """Parse a VTT/SRT timestamp into milliseconds."""
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, rest = parts
    elif len(parts) == 2:
        hours, minutes, rest = "0", parts[0], parts[1]
    else:
        raise ValueError(f"Unrecognized timestamp: {value!r}")
    seconds, _, millis = rest.partition(".")
    millis = (millis + "000")[:3] if millis else "0"
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(millis)
    )


def _strip_tags(text: str) -> tuple[str, str | None]:
    """Return (clean_text, voice) from a cue payload, handling <v Speaker>."""
    voice = None
    match = _VOICE_RE.match(text.strip())
    if match:
        voice = match.group(1).strip()
        text = match.group(2)
    clean = _TAG_RE.sub("", text)
    return clean.strip(), voice


def parse(content: str) -> Transcript:
    """Parse WebVTT text into a Transcript."""
    cues: list[TranscriptCue] = []
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        timing_idx = None
        for idx, line in enumerate(lines):
            if "-->" in line:
                timing_idx = idx
                break
        if timing_idx is None:
            continue  # header (WEBVTT), NOTE, or STYLE block
        match = _TIMING_RE.search(lines[timing_idx])
        if not match:
            continue
        start_ms = timestamp_to_ms(match.group("start"))
        end_ms = timestamp_to_ms(match.group("end"))
        payload = " ".join(lines[timing_idx + 1 :]).strip()
        if not payload:
            continue
        text, voice = _strip_tags(payload)
        if text:
            cues.append(TranscriptCue(start_ms=start_ms, end_ms=end_ms, text=text, voice=voice))
    return Transcript(cues=cues)


def parse_file(path: str | Path) -> Transcript:
    return parse(Path(path).read_text(encoding="utf-8"))


def write_file(transcript: Transcript, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript.to_vtt(), encoding="utf-8")
