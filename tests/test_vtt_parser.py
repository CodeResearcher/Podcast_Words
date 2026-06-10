from podcast_words.models import Transcript, TranscriptCue
from podcast_words.transcripts import vtt

SAMPLE = """WEBVTT

00:00:01.000 --> 00:00:04.000
<v Alice>Hello there.

00:00:04.500 --> 00:00:06.000
General response.
"""


def test_parse_basic_cues():
    transcript = vtt.parse(SAMPLE)
    assert len(transcript.cues) == 2
    first = transcript.cues[0]
    assert first.start_ms == 1000
    assert first.end_ms == 4000
    assert first.text == "Hello there."
    assert first.voice == "Alice"


def test_parse_plain_text():
    transcript = vtt.parse(SAMPLE)
    assert transcript.plain_text() == "Hello there. General response."


def test_timestamp_to_ms_variants():
    assert vtt.timestamp_to_ms("00:00:01.500") == 1500
    assert vtt.timestamp_to_ms("01:02:03.004") == 3_723_004
    assert vtt.timestamp_to_ms("00:30.250") == 30_250


def test_round_trip():
    transcript = Transcript(
        cues=[TranscriptCue(start_ms=1000, end_ms=2000, text="One", voice="Bob")]
    )
    reparsed = vtt.parse(transcript.to_vtt())
    assert reparsed.cues[0].text == "One"
    assert reparsed.cues[0].voice == "Bob"
    assert reparsed.cues[0].start_ms == 1000
