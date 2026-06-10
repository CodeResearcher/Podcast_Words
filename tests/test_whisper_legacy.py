from podcast_words.transcripts import whisper_legacy
from podcast_words.transcripts.loader import load_transcript

LEGACY = (
    "[{'timestamp': (0.0, 2.5), 'text': ' Hallo Welt.'}, "
    "{'timestamp': (2.5, 5.0), 'text': 'Zweiter Teil.'}]"
)


def test_parse_legacy_chunks():
    transcript = whisper_legacy.parse(LEGACY)
    assert len(transcript.cues) == 2
    assert transcript.cues[0].start_ms == 0
    assert transcript.cues[0].end_ms == 2500
    assert transcript.cues[0].text == "Hallo Welt."


def test_looks_like_legacy():
    assert whisper_legacy.looks_like_legacy(LEGACY)
    assert not whisper_legacy.looks_like_legacy("Just some prose text.")


def test_loader_detects_legacy_txt(tmp_path):
    path = tmp_path / "episode_3.txt"
    path.write_text(LEGACY, encoding="utf-8")
    transcript = load_transcript(path)
    assert transcript.plain_text() == "Hallo Welt. Zweiter Teil."


def test_loader_detects_plain_txt(tmp_path):
    path = tmp_path / "episode_4.txt"
    path.write_text("This is plain prose without timestamps.", encoding="utf-8")
    transcript = load_transcript(path)
    assert len(transcript.cues) == 1
    assert "plain prose" in transcript.plain_text()
