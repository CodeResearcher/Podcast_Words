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


def test_count_tolerates_invalid_word_rows(temp_podcast, monkeypatch):
    import pandas as pd

    monkeypatch.setattr(word_counter, "_load_spacy", lambda name: spacy.load(MODEL))

    csv_path = temp_podcast.word_counts_csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "word": [float("nan"), float("nan"), "eimer"],
            "is_stop": [False, False, False],
            "1": [None, 1.0, 2.0],
        }
    ).to_csv(csv_path, index=False)

    _write(temp_podcast, 2, "Die Münze und der Cent.")

    result = word_counter.count_words(temp_podcast)
    assert result["processed"] == 1

    df = word_counter._read_word_counts_csv(csv_path)
    assert df["word"].notna().all()
    assert not df["word"].duplicated().any()


def test_read_word_counts_preserves_null_lemma(temp_podcast):
    import pandas as pd

    csv_path = temp_podcast.word_counts_csv
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"word": ["null", "eimer"], "is_stop": [False, False], "1": [3, 2]}).to_csv(
        csv_path, index=False
    )

    df = word_counter._read_word_counts_csv(csv_path)
    assert df["word"].tolist() == ["null", "eimer"]
