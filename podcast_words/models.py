"""Core data models shared across transcript sources and the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


def _format_timestamp(ms: int) -> str:
    """Render milliseconds as a WebVTT timestamp (HH:MM:SS.mmm)."""
    ms = max(0, int(ms))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


@dataclass
class TranscriptCue:
    """A single timed segment of a transcript."""

    start_ms: int
    end_ms: int
    text: str
    voice: str | None = None


@dataclass
class Transcript:
    """A full transcript as an ordered list of cues."""

    cues: list[TranscriptCue] = field(default_factory=list)

    def plain_text(self) -> str:
        """Concatenate all cue text for word counting."""
        return " ".join(cue.text.strip() for cue in self.cues if cue.text.strip())

    def to_vtt(self) -> str:
        """Serialize the transcript as a canonical WebVTT document."""
        lines = ["WEBVTT", ""]
        for cue in self.cues:
            timing = f"{_format_timestamp(cue.start_ms)} --> {_format_timestamp(cue.end_ms)}"
            lines.append(timing)
            text = cue.text.strip()
            if cue.voice:
                lines.append(f"<v {cue.voice}>{text}")
            else:
                lines.append(text)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"
