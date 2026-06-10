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


def test_discover_parses_number_from_title(monkeypatch):
    monkeypatch.setattr(
        podlove, "_api_get", lambda *a, **k: _FakeResponse(EPISODES_RESPONSE)
    )
    episodes = podlove.discover(_podcast(), _source())
    assert len(episodes) == 2
    assert episodes[0].number == 308
    assert episodes[0].source_id == "1867"


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
