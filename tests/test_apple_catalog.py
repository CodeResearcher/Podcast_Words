from podcast_words.config import EpisodeIdConfig, PodcastConfig, SourceConfig
from podcast_words.sources import apple_catalog

LOOKUP_RESPONSE = {
    "resultCount": 3,
    "results": [
        {"wrapperType": "track", "kind": "podcast", "collectionName": "Show"},
        {
            "wrapperType": "podcastEpisode",
            "trackId": 222,
            "trackName": "Second Episode",
            "releaseDate": "2024-02-01T00:00:00Z",
            "episodeUrl": "http://audio/2.mp3",
        },
        {
            "wrapperType": "podcastEpisode",
            "trackId": 111,
            "trackName": "First Episode",
            "releaseDate": "2024-01-01T00:00:00Z",
            "episodeUrl": "http://audio/1.mp3",
        },
    ],
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_discover_orders_oldest_first(monkeypatch):
    monkeypatch.setattr(
        apple_catalog.requests, "get", lambda *a, **k: _FakeResponse(LOOKUP_RESPONSE)
    )
    podcast = PodcastConfig(
        id="daily", name="Daily", language="en", episode_id=EpisodeIdConfig(type="sequential")
    )
    source = SourceConfig(type="apple", podcast_id="123", country="US")

    episodes = apple_catalog.discover(podcast, source)
    assert len(episodes) == 2
    # Oldest release date becomes episode 1.
    assert episodes[0].number == 1
    assert episodes[0].title == "First Episode"
    assert episodes[0].source_id == "111"
    assert episodes[1].number == 2
    assert episodes[1].title == "Second Episode"


def test_discover_uses_regex_numbers(monkeypatch):
    payload = {
        "results": [
            {"wrapperType": "track"},
            {
                "wrapperType": "podcastEpisode",
                "trackId": 9,
                "trackName": "EP042 Something",
                "releaseDate": "2024-01-01T00:00:00Z",
            },
        ]
    }
    monkeypatch.setattr(apple_catalog.requests, "get", lambda *a, **k: _FakeResponse(payload))
    podcast = PodcastConfig(
        id="x",
        name="X",
        language="en",
        episode_id=EpisodeIdConfig(type="regex", pattern=r"EP(\d+)"),
    )
    source = SourceConfig(type="apple", podcast_id="123")
    episodes = apple_catalog.discover(podcast, source)
    assert episodes[0].number == 42
