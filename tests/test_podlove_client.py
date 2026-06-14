from podcast_words.catalog import Episode
from podcast_words.config import EpisodeIdConfig, PodcastConfig, SourceConfig
from podcast_words.sources import podlove

EPISODES_RESPONSE = {
    "results": [
        {"id": "1867", "title": "FS308 Casual Punk"},
        {"id": "1866", "title": "FS307 Die Null"},
    ],
    "_version": "v2",
}

EPISODE_DETAIL = {
    "id": 1867,
    "title": "FS308 Casual Punk",
    "number": "308",
    "link": "https://example.test/fs308-casual-punk",
    "publicationDate": "2026-06-02T22:05:41+02:00",
}

TRANSCRIPT_RESPONSE = {
    "_version": "v2",
    "transcript": [
        {"start_ms": 1000, "end_ms": 2000, "voice": "tim", "text": "Hallo."},
        {"start_ms": 2000, "end_ms": 3000, "voice": "roddi", "text": "Moin."},
    ],
}


class _FakeResponse:
    def __init__(self, payload, status=200, content_type="application/json"):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload

    @property
    def text(self):
        return ""


def _podcast():
    return PodcastConfig(
        id="freakshow",
        name="Freak Show",
        language="de",
        episode_id=EpisodeIdConfig(type="podlove_number"),
    )


def _source():
    return SourceConfig(type="podlove", api_base="http://example.test/v2")


def _fake_api_get(url: str, params=None):
    if url.endswith("/episodes/1867"):
        return _FakeResponse(EPISODE_DETAIL)
    if url.endswith("/episodes/1866"):
        return _FakeResponse(
            {
                "id": 1866,
                "title": "FS307 Die Null",
                "number": "307",
                "link": "https://example.test/fs307-die-null",
            }
        )
    if url.endswith("/episodes"):
        return _FakeResponse(EPISODES_RESPONSE)
    raise AssertionError(f"unexpected URL: {url}")


def test_discover_parses_number_from_title(monkeypatch):
    monkeypatch.setattr(podlove, "_api_get", _fake_api_get)
    episodes = podlove.discover(_podcast(), _source())
    assert len(episodes) == 2
    assert episodes[0].number == 308
    assert episodes[0].source_id == "1867"
    assert episodes[0].link == "https://example.test/fs308-casual-punk"
    assert episodes[1].link == "https://example.test/fs307-die-null"


def test_fetch_transcript_json_array(monkeypatch):
    monkeypatch.setattr(
        podlove, "_api_get", lambda *a, **k: _FakeResponse(TRANSCRIPT_RESPONSE)
    )
    episode = Episode(number=308, source_id="1867")
    transcript = podlove.fetch_transcript(_podcast(), _source(), episode)
    assert transcript is not None
    assert len(transcript.cues) == 2
    assert transcript.cues[0].voice == "tim"
    assert transcript.plain_text() == "Hallo. Moin."


def test_fetch_transcript_404(monkeypatch):
    monkeypatch.setattr(
        podlove, "_api_get", lambda *a, **k: _FakeResponse({}, status=404)
    )
    episode = Episode(number=1, source_id="999")
    assert podlove.fetch_transcript(_podcast(), _source(), episode) is None


def test_fetch_transcript_no_source_id():
    episode = Episode(number=1, source_id="")
    assert podlove.fetch_transcript(_podcast(), _source(), episode) is None


def test_discover_sequential_sorts_by_podlove_id(monkeypatch):
    def fake_api_get(url: str, params=None):
        if url.endswith("/episodes/616"):
            return _FakeResponse(
                {
                    "id": 616,
                    "title": "Kracht&#8217;s Air",
                    "link": "https://example.test/krachts-air",
                }
            )
        if url.endswith("/episodes/9"):
            return _FakeResponse(
                {
                    "id": 9,
                    "title": "Eine neue Zeit",
                    "link": "https://example.test/eine-neue-zeit",
                }
            )
        if url.endswith("/episodes"):
            return _FakeResponse(
                {
                    "results": [
                        {"id": "616", "title": "Kracht&#8217;s Air"},
                        {"id": "9", "title": "Eine neue Zeit"},
                    ]
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(podlove, "_api_get", fake_api_get)
    podcast = PodcastConfig(
        id="neue_zwanziger",
        name="Die Neuen Zwanziger",
        language="de",
        episode_id=EpisodeIdConfig(type="sequential"),
    )
    episodes = podlove.discover(podcast, _source())
    assert [ep.number for ep in episodes] == [1, 2]
    assert episodes[0].title == "Eine neue Zeit"
    assert episodes[0].link == "https://example.test/eine-neue-zeit"
    assert episodes[1].title.startswith("Kracht")
    assert episodes[1].link == "https://example.test/krachts-air"
