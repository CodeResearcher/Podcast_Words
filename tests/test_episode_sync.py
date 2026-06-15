from podcast_words.catalog import Catalog, Episode, STATE_DONE, STATE_NO_TRANSCRIPT, STATE_PENDING, _prefer_episode_link
from podcast_words.config import SourceConfig
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

    with open(temp_podcast.sync_state_json, encoding="utf-8") as f:
        sync_state = __import__("json").load(f)
    assert sync_state["last_episode_number"] == 3
    assert sync_state["last_episode_title"] == "C"


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


class TwoSourceFake:
    """Primary source leaves episode 2 without a transcript; the fallback has it."""

    def __init__(self):
        self.primary_remote = [
            Episode(number=1, title="FS1 One", source_id="p1", state=STATE_PENDING),
            Episode(number=2, title="FS2 Two", source_id="p2", state=STATE_PENDING),
        ]
        # Fallback (Apple) episodes carry their own ids; matched by title number.
        self.fallback_remote = [
            Episode(number=99, title="FS1 One", source_id="apple-1", state=STATE_PENDING),
            Episode(number=99, title="FS2 Two", source_id="apple-2", state=STATE_PENDING),
        ]

    def discover(self, podcast, source):
        remote = self.primary_remote if source.type == "podlove" else self.fallback_remote
        return [Episode(**vars(e)) for e in remote]

    def fetch(self, podcast, source, episode):
        if source.type == "podlove":
            if episode.number == 2:
                return None
            return Transcript([TranscriptCue(0, 1000, "primary text")])
        # Fallback source: only serves the matched Apple id.
        if episode.source_id == "apple-2":
            return Transcript([TranscriptCue(0, 1000, "apple text")])
        if episode.source_id == "apple-1":
            return Transcript([TranscriptCue(0, 1000, "apple one text")])
        return None


def test_fallback_recovers_missing_transcripts(temp_podcast, monkeypatch):
    temp_podcast.sources.append(SourceConfig(type="apple", podcast_id="277518737"))
    fake = TwoSourceFake()
    _wire(monkeypatch, fake)

    summary = episode_sync.sync(temp_podcast, count=False, fallback=True)
    assert summary["fetched"] == 1
    assert summary["no_transcript"] == 1
    assert summary["fallback"]["recovered"] == 1
    assert summary["fallback"]["still_missing"] == 0

    catalog = Catalog.load(temp_podcast.episodes_csv)
    assert catalog.get(2).state == STATE_DONE
    assert catalog.get(2).transcript_source == "apple"
    vtt_path = temp_podcast.transcripts_dir / "episode_2.vtt"
    assert "apple text" in vtt_path.read_text()


def test_fallback_disabled_by_default(temp_podcast, monkeypatch):
    temp_podcast.sources.append(SourceConfig(type="apple", podcast_id="277518737"))
    fake = TwoSourceFake()
    _wire(monkeypatch, fake)

    summary = episode_sync.sync(temp_podcast, count=False)
    assert "fallback" not in summary
    catalog = Catalog.load(temp_podcast.episodes_csv)
    assert catalog.get(2).state == STATE_NO_TRANSCRIPT


def test_replace_from_alternate_source(temp_podcast, monkeypatch):
    temp_podcast.sources.append(SourceConfig(type="apple", podcast_id="277518737"))
    fake = TwoSourceFake()
    _wire(monkeypatch, fake)

    episode_sync.sync(temp_podcast, count=False)
    apple = temp_podcast.source_of_type("apple")
    summary = episode_sync.sync(
        temp_podcast,
        replace_from=apple,
        count=False,
    )
    assert summary["replace"]["replaced"] == 1
    assert summary["replace"]["skipped"] == 0

    catalog = Catalog.load(temp_podcast.episodes_csv)
    assert catalog.get(1).transcript_source == "apple"
    assert "apple one text" in (temp_podcast.transcripts_dir / "episode_1.vtt").read_text()


def test_replace_if_from_filters_targets(temp_podcast, monkeypatch):
    temp_podcast.sources.append(SourceConfig(type="apple", podcast_id="277518737"))
    fake = TwoSourceFake()
    _wire(monkeypatch, fake)

    episode_sync.sync(temp_podcast, count=False)
    catalog = Catalog.load(temp_podcast.episodes_csv)
    catalog.get(1).transcript_source = "whisper"
    catalog.save()

    apple = temp_podcast.source_of_type("apple")
    summary = episode_sync.sync(
        temp_podcast,
        replace_from=apple,
        replace_if_from=("podlove",),
        count=False,
    )
    assert summary["replace"]["replaced"] == 0

    catalog = Catalog.load(temp_podcast.episodes_csv)
    assert catalog.get(1).transcript_source == "whisper"


def test_replace_skips_same_source(temp_podcast, monkeypatch):
    temp_podcast.sources.append(SourceConfig(type="apple", podcast_id="277518737"))
    fake = TwoSourceFake()
    _wire(monkeypatch, fake)

    episode_sync.sync(temp_podcast, count=False, fallback=True)
    catalog = Catalog.load(temp_podcast.episodes_csv)
    assert catalog.get(2).transcript_source == "apple"

    apple = temp_podcast.source_of_type("apple")
    summary = episode_sync.sync(
        temp_podcast,
        replace_from=apple,
        count=False,
    )
    assert summary["replace"]["replaced"] == 1
    assert summary["replace"]["skipped"] == 0


def test_prefer_episode_link_keeps_page_url_over_audio():
    page = "https://neuezwanziger.de/2019/12/eine-neue-zeit/"
    audio = "https://audio.podigee-cdn.net/example.mp3?source=feed"
    assert _prefer_episode_link(page, audio) == page
    assert _prefer_episode_link(audio, page) == page


def test_prefer_episode_link_podlove_wins_over_other_page():
    podlove = "https://neuezwanziger.de/2019/12/eine-neue-zeit/"
    apple = "https://podcasts.apple.com/de/podcast/id123?i=456"
    assert _prefer_episode_link(podlove, apple, new_from_podlove=True) == podlove
    assert _prefer_episode_link(apple, podlove) == podlove


def test_upsert_keeps_page_link_when_apple_rediscovers(temp_podcast):
    catalog = Catalog.load(temp_podcast.episodes_csv)
    page = "https://neuezwanziger.de/2019/12/eine-neue-zeit/"
    audio = "https://audio.podigee-cdn.net/example.mp3?source=feed"
    catalog.upsert(Episode(number=1, title="A", link=page, source_id="9"))
    catalog.upsert(
        Episode(number=1, title="A", link=audio, source_id="1000460866307", transcript_source="apple")
    )
    assert catalog.get(1).link == page


def test_upsert_keeps_podlove_title_when_apple_rediscovers(temp_podcast):
    catalog = Catalog.load(temp_podcast.episodes_csv)
    catalog.upsert(
        Episode(
            number=30,
            title="Künstliche Intelligenz",
            link="https://example.test/cr221",
            source_id="9",
        ),
        new_from_podlove=True,
    )
    catalog.upsert(
        Episode(
            number=30,
            title="Keine Panik!",
            link="https://podcasts.apple.com/de/podcast/keine-panik/id1?i=2",
            source_id="1000423936344",
            transcript_source="apple",
        )
    )
    assert catalog.get(30).title == "Künstliche Intelligenz"
    assert catalog.get(30).link == "https://example.test/cr221"


def test_fallback_keeps_podlove_link_without_transcript(temp_podcast, monkeypatch):
    temp_podcast.sources.append(SourceConfig(type="apple", podcast_id="277518737"))
    podlove_page = "https://example.test/fs2-two"
    podlove_audio = "https://audio.podigee-cdn.net/fs2.mp3"

    class PodloveNoTranscriptFake(TwoSourceFake):
        def discover(self, podcast, source):
            episodes = super().discover(podcast, source)
            if source.type == "podlove":
                for ep in episodes:
                    if ep.number == 2:
                        ep.link = podlove_page
            else:
                for ep in episodes:
                    if ep.title == "FS2 Two":
                        ep.link = podlove_audio
            return episodes

    fake = PodloveNoTranscriptFake()
    _wire(monkeypatch, fake)

    episode_sync.sync(temp_podcast, count=False, fallback=True)
    catalog = Catalog.load(temp_podcast.episodes_csv)
    assert catalog.get(2).state == STATE_DONE
    assert catalog.get(2).transcript_source == "apple"
    assert catalog.get(2).link == podlove_page
