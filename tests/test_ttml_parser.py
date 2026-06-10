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
