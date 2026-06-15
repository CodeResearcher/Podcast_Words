"""Apple TTML (Timed Text Markup Language) parsing into a Transcript.

Apple Podcasts transcripts are TTML documents whose timed text lives in <p>
elements (optionally split into <span> children). Speaker labels are carried in
ttm:agent / region attributes; we surface them as cue voices when present.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree as ET  # types only; parsing uses defusedxml

from defusedxml.ElementTree import fromstring as _safe_fromstring

from podcast_words.models import Transcript, TranscriptCue


def _local(tag: str) -> str:
    """Strip XML namespace from a tag name."""
    return tag.rsplit("}", 1)[-1]


def _parse_clock(value: str | None) -> int | None:
    """Parse a TTML time expression into milliseconds.

    Supports clock-time (HH:MM:SS(.fff), MM:SS(.fff)) and offset-time
    (e.g. '12.5s', '500ms', bare seconds like '7.640').
    """
    if not value:
        return None
    value = value.strip()
    offset = re.fullmatch(r"(?P<num>\d+(?:\.\d+)?)(?P<unit>h|m|s|ms|f|t)?", value)
    if offset:
        num = float(offset.group("num"))
        unit = offset.group("unit") or "s"
        factor = {"h": 3_600_000, "m": 60_000, "s": 1_000, "ms": 1}.get(unit)
        if factor is not None:
            return int(num * factor)
    if ":" not in value:
        return None
    parts = value.split(":")
    if len(parts) == 3:
        hours, minutes, rest = parts
        seconds, _, frac = rest.partition(".")
        millis = int((frac + "000")[:3]) if frac else 0
        return (
            int(hours) * 3_600_000
            + int(minutes) * 60_000
            + int(seconds) * 1_000
            + millis
        )
    if len(parts) == 2:
        minutes, rest = parts
        seconds, _, frac = rest.partition(".")
        millis = int((frac + "000")[:3]) if frac else 0
        return int(minutes) * 60_000 + int(seconds) * 1_000 + millis
    return None


def _gather_text(element: ET.Element) -> str:
    """Collect text from an element and its inline children (e.g. <span>, <br>).

    Apple word-level TTML nests one <span podcasts:unit="word"> per word with no
    separating whitespace, so child contributions are joined with a space (and
    runs of whitespace are then collapsed). Transcripts that already include
    explicit spacing are unaffected because the collapse removes duplicates.
    """
    fragments: list[str] = []
    if element.text:
        fragments.append(element.text)
    for child in element:
        if _local(child.tag) == "br":
            fragments.append(" ")
        else:
            fragments.append(" ")
            fragments.append(_gather_text(child))
        if child.tail:
            fragments.append(child.tail)
    return re.sub(r"\s+", " ", "".join(fragments)).strip()


def parse(content: str) -> Transcript:
    # defusedxml rejects DTDs/external entities and entity-expansion attacks.
    root = _safe_fromstring(content)
    cues: list[TranscriptCue] = []
    for elem in root.iter():
        if _local(elem.tag) != "p":
            continue
        start = _parse_clock(elem.get("begin"))
        end = _parse_clock(elem.get("end"))
        if start is None:
            continue
        if end is None:
            end = start
        text = _gather_text(elem)
        if not text:
            continue
        voice = elem.get("{http://www.w3.org/ns/ttml#metadata}agent") or elem.get("region")
        cues.append(TranscriptCue(start_ms=start, end_ms=end, text=text, voice=voice))
    return Transcript(cues=cues)


def parse_file(path: str | Path) -> Transcript:
    return parse(Path(path).read_text(encoding="utf-8"))
