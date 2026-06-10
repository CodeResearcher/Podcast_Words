import pytest

import podcast_words.config as config_module
from podcast_words.config import EpisodeIdConfig, PodcastConfig, SourceConfig


@pytest.fixture
def temp_podcast(tmp_path, monkeypatch):
    """A podcast whose data lives under a temporary directory."""
    monkeypatch.setattr(config_module, "DATA_ROOT", tmp_path)
    podcast = PodcastConfig(
        id="test",
        name="Test Podcast",
        language="de",
        episode_id=EpisodeIdConfig(type="sequential"),
        sources=[SourceConfig(type="podlove", api_base="http://example.test/v2")],
    )
    podcast.ensure_dirs()
    return podcast
