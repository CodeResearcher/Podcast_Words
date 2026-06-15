from podcast_words.config import EpisodeIdConfig, PodcastConfig, SourceConfig
from podcast_words.sources import apple_catalog
import pytest

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


def test_discover_uses_podlove_number_from_title(monkeypatch):
    payload = {
        "results": [
            {"wrapperType": "track"},
            {
                "wrapperType": "podcastEpisode",
                "trackId": 9,
                "trackName": "FS150 Syntactic Cancer",
                "releaseDate": "2015-02-05T15:49:21Z",
            },
        ]
    }
    monkeypatch.setattr(apple_catalog.requests, "get", lambda *a, **k: _FakeResponse(payload))
    podcast = PodcastConfig(
        id="freakshow",
        name="Freak Show",
        language="de",
        episode_id=EpisodeIdConfig(type="podlove_number"),
    )
    source = SourceConfig(type="apple", podcast_id="123")
    episodes = apple_catalog.discover(podcast, source)
    assert episodes[0].number == 150


def test_discover_uses_amp_api_when_lookup_is_truncated(monkeypatch):
    lookup_payload = {
        "results": [
            {"wrapperType": "track", "trackCount": 309},
            *[
                {
                    "wrapperType": "podcastEpisode",
                    "trackId": 1000 + i,
                    "trackName": f"Lookup Episode {i}",
                    "releaseDate": f"2024-01-{i:02d}T00:00:00Z",
                }
                for i in range(1, 201)
            ],
        ]
    }
    amp_pages = [
        {
            "data": [
                {
                    "id": "9001",
                    "attributes": {
                        "name": "FS001 First",
                        "releaseDateTime": "2008-04-01T00:00:00Z",
                        "mediaKind": "audio",
                        "url": "https://podcasts.apple.com/de/podcast/x/id1?i=9001",
                    },
                }
            ],
            "next": False,
            "meta": {"total": 309},
        }
    ]

    def fake_get(url, *args, **kwargs):
        if url == apple_catalog._LOOKUP_URL:
            return _FakeResponse(lookup_payload)
        assert "amp-api.podcasts.apple.com" in url
        return _FakeResponse(amp_pages.pop(0))

    monkeypatch.setattr(apple_catalog.requests, "get", fake_get)
    monkeypatch.setattr(apple_catalog, "get_bearer_token", lambda **k: "ey.test.token")

    podcast = PodcastConfig(
        id="freakshow",
        name="Freak Show",
        language="de",
        episode_id=EpisodeIdConfig(type="podlove_number"),
    )
    source = SourceConfig(type="apple", podcast_id="277518737", country="DE")
    episodes = apple_catalog.discover(podcast, source)
    assert len(episodes) == 1
    assert episodes[0].source_id == "9001"
    assert episodes[0].number == 1


def test_discover_falls_back_to_lookup_when_amp_unavailable(monkeypatch):
    lookup_payload = {
        "results": [
            {"wrapperType": "track", "trackCount": 250},
            {
                "wrapperType": "podcastEpisode",
                "trackId": 111,
                "trackName": "Only Lookup Episode",
                "releaseDate": "2024-01-01T00:00:00Z",
            },
        ]
    }
    monkeypatch.setattr(
        apple_catalog.requests, "get", lambda *a, **k: _FakeResponse(lookup_payload)
    )

    def _unsupported(**kwargs):
        raise apple_catalog.AppleUnsupportedError("no macOS")

    monkeypatch.setattr(apple_catalog, "get_bearer_token", _unsupported)

    podcast = PodcastConfig(
        id="daily", name="Daily", language="en", episode_id=EpisodeIdConfig(type="sequential")
    )
    source = SourceConfig(type="apple", podcast_id="123", country="US")

    with pytest.warns(UserWarning, match="amp-api discovery unavailable"):
        episodes = apple_catalog.discover(podcast, source)

    assert len(episodes) == 1
    assert episodes[0].title == "Only Lookup Episode"
