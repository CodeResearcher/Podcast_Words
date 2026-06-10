import json

import pytest

from podcast_words.models import Transcript, TranscriptCue
from podcast_words.pipeline import word_counter
from podcast_words.transcripts import vtt

spacy = pytest.importorskip("spacy")


def _has_model(name: str) -> bool:
    try:
        spacy.load(name)
        return True
    except OSError:
        return False


MODEL = "de_core_news_sm"
pytestmark = pytest.mark.skipif(
    not _has_model(MODEL), reason=f"spaCy model {MODEL} not installed"
)


def _write(podcast, number, text):
    vtt.write_file(
        Transcript([TranscriptCue(0, 1000, text)]),
        podcast.transcripts_dir / f"episode_{number}.vtt",
    )


def test_count_and_skip(temp_podcast, monkeypatch):
    monkeypatch.setattr(word_counter, "_load_spacy", lambda name: spacy.load(MODEL))

    _write(temp_podcast, 1, "Der Eimer Eimer Eimer.")
    _write(temp_podcast, 2, "Die Münze und der Cent.")

    first = word_counter.count_words(temp_podcast)
    assert first["processed"] == 2

    second = word_counter.count_words(temp_podcast)
    assert second["processed"] == 0
    assert second["skipped"] == 2

    stats = json.loads(temp_podcast.episode_stats_json.read_text())
    assert stats["total_episodes"] == 2
