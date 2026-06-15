from pathlib import Path

from podcast_words.transcripts import ttml

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata">
  <body>
    <div>
      <p begin="00:00:01.000" end="00:00:03.500" ttm:agent="spk1"><span>Hello</span> <span>world.</span></p>
      <p begin="3.5s" end="6s">Offset timing line.</p>
      <p begin="00:00:06.000" end="00:00:09.000">Line with<br/>a break.</p>
    </div>
  </body>
</tt>"""


def test_parse_namespaced_ttml():
    transcript = ttml.parse(SAMPLE)
    assert len(transcript.cues) == 3


def test_span_and_voice():
    cue = ttml.parse(SAMPLE).cues[0]
    assert cue.text == "Hello world."
    assert cue.voice == "spk1"
    assert cue.start_ms == 1000
    assert cue.end_ms == 3500


def test_offset_timing():
    cue = ttml.parse(SAMPLE).cues[1]
    assert cue.start_ms == 3500
    assert cue.end_ms == 6000


def test_line_break_collapsed():
    cue = ttml.parse(SAMPLE).cues[2]
    assert cue.text == "Line with a break."


def test_to_vtt_conversion():
    vtt_text = ttml.parse(SAMPLE).to_vtt()
    assert vtt_text.startswith("WEBVTT")
    assert "-->" in vtt_text


# Apple word-level TTML: each word in its own <span> with no separating space.
WORD_LEVEL = """<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttm="http://www.w3.org/ns/ttml#metadata">
  <body><div>
    <p begin="0.5" end="3.0" ttm:agent="SPEAKER_1"><span begin="0.5" end="2.0"><span begin="0.5" end="0.8">Herzlich</span><span begin="0.9" end="1.2">Willkommen</span><span begin="1.3" end="2.0">beim</span></span></p>
  </div></body>
</tt>"""


def test_word_level_spans_get_spaced():
    cue = ttml.parse(WORD_LEVEL).cues[0]
    assert cue.text == "Herzlich Willkommen beim"


def test_parse_minute_second_clock():
    assert ttml._parse_clock("1:01.340") == 61_340
    assert ttml._parse_clock("5:40.220") == 340_220
    assert ttml._parse_clock("2:14.480") == 134_480


def test_parse_ligatour_episode_1_ttml():
    path = Path(__file__).resolve().parents[1] / "data/ligatour/transcripts/raw/episode_1.ttml"
    if not path.exists():
        return
    transcript = ttml.parse_file(path)
    assert len(transcript.cues) == 22
    assert transcript.cues[-1].text.endswith("Ciao.")
    assert max(cue.end_ms for cue in transcript.cues) >= 340_000
