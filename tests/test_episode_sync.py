from podcast_words.catalog import Catalog, Episode, STATE_DONE, STATE_NO_TRANSCRIPT, STATE_PENDING
from podcast_words.models import Transcript, TranscriptCue
from podcast_words.pipeline import episode_sync


class FakeSource:
    """A controllable in-memory source for backfill/incremental tests."""

    def __init__(self):
        self.remote = [
            Episode(number=1, title="A", source_id="a", state=STATE_PENDING),
            Episode(number=2, title="B", source_id="b", state=STATE_PENDING),
        ]
        self.fetched: list[int] = []

    def discover(self, podcast, source):
        return [Episode(**vars(e)) for e in self.remote]

    def fetch(self, podcast, source, episode):
        self.fetched.append(episode.number)
        if episode.number == 2:
            return None  # simulate no transcript available
        return Transcript([TranscriptCue(0, 1000, "hello world")])


def _wire(monkeypatch, fake):
    monkeypatch.setattr(episode_sync, "_discover_fn", lambda t: fake.discover)
    monkeypatch.setattr(episode_sync, "_fetch_fn", lambda t: fake.fetch)


def test_backfill_then_incremental(temp_podcast, monkeypatch):
    fake = FakeSource()
    _wire(monkeypatch, fake)

    first = episode_sync.sync(temp_podcast, count=False)
    assert first["new_episodes"] == 2
    assert first["fetched"] == 1
    assert first["no_transcript"] == 1

    # A new episode is published.
    fake.remote.append(Episode(number=3, title="C", source_id="c", state=STATE_PENDING))
    fake.fetched.clear()

    second = episode_sync.sync(temp_podcast, count=False)
    assert second["new_episodes"] == 1
    # Episode 1 is done and must NOT be refetched; ep 2 (no_transcript) and ep 3 (new) are.
    assert 1 not in fake.fetched
    assert set(fake.fetched) == {2, 3}

    catalog = Catalog.load(temp_podcast.episodes_csv)
    assert catalog.get(1).state == STATE_DONE
    assert catalog.get(2).state == STATE_NO_TRANSCRIPT
    assert catalog.get(3).state == STATE_DONE


def test_force_refetches_everything(temp_podcast, monkeypatch):
    fake = FakeSource()
    _wire(monkeypatch, fake)
    episode_sync.sync(temp_podcast, count=False)
    fake.fetched.clear()

    episode_sync.sync(temp_podcast, force=True, count=False)
    assert set(fake.fetched) == {1, 2}


def test_transcript_saved_as_vtt(temp_podcast, monkeypatch):
    fake = FakeSource()
    _wire(monkeypatch, fake)
    episode_sync.sync(temp_podcast, count=False)
    vtt_path = temp_podcast.transcripts_dir / "episode_1.vtt"
    assert vtt_path.exists()
    assert "hello world" in vtt_path.read_text()
