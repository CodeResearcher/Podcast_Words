import pytest

from podcast_words.config import load_config


def _write_config(tmp_path, body: str):
    path = tmp_path / "podcasts.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_default_config():
    config = load_config()
    assert "pufo" in config
    assert config["pufo"].language == "de"
    assert config["pufo"].spacy_model == "de_core_news_lg"
    assert config["pufo"].primary_source().type == "whisper_rss"


def test_paths_are_namespaced_per_podcast():
    config = load_config()
    pufo = config["pufo"]
    assert pufo.data_dir.name == "pufo"
    assert pufo.word_counts_csv.name == "word_counts.csv"
    assert pufo.episodes_csv.parent == pufo.data_dir


def test_invalid_source_type_rejected(tmp_path):
    path = _write_config(
        tmp_path,
        """
podcasts:
  bad:
    name: Bad
    sources:
      - type: not_a_real_source
""",
    )
    with pytest.raises(ValueError):
        load_config(path)


def test_regex_episode_id_requires_pattern(tmp_path):
    path = _write_config(
        tmp_path,
        """
podcasts:
  bad:
    name: Bad
    episode_id:
      type: regex
""",
    )
    with pytest.raises(ValueError):
        load_config(path)


def test_apple_source_requires_podcast_id(tmp_path):
    path = _write_config(
        tmp_path,
        """
podcasts:
  bad:
    name: Bad
    sources:
      - type: apple
""",
    )
    with pytest.raises(ValueError):
        load_config(path)


def test_sorted_podcast_ids_respects_order(tmp_path):
    path = _write_config(
        tmp_path,
        """
podcasts:
  second:
    name: Second
    order: 20
    sources:
      - type: apple
        podcast_id: "1"
  first:
    name: First
    order: 10
    sources:
      - type: apple
        podcast_id: "2"
  third:
    name: Third
    sources:
      - type: apple
        podcast_id: "3"
""",
    )
    from podcast_words.config import sorted_podcast_ids

    assert sorted_podcast_ids(load_config(path)) == ["first", "second", "third"]
