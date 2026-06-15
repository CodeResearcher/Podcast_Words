from podcast_words.catalog import Episode
from podcast_words.config import EpisodeIdConfig, PodcastConfig
from podcast_words.episode_number import (
    catalog_number_for_remote,
    normalize_title,
    number_from_title,
    published_date_key,
)
from podcast_words.pipeline.remote_index import RemoteIndex, build_remote_index


def test_podlove_number_from_fs_prefix():
    podcast = PodcastConfig(
        id="freakshow",
        name="Freak Show",
        language="de",
        episode_id=EpisodeIdConfig(type="podlove_number"),
    )
    assert number_from_title(podcast, "FS150 Syntactic Cancer") == 150
    assert number_from_title(podcast, "MM047 Haptischer Orgasmus") == 47
    assert number_from_title(podcast, "Syntactic Cancer") is None


def test_regex_number_from_title():
    podcast = PodcastConfig(
        id="lnp",
        name="LNP",
        language="de",
        episode_id=EpisodeIdConfig(type="regex", pattern=r"LNP(\d+)"),
    )
    assert number_from_title(podcast, "LNP357 Wie Autocorrect") == 357


def test_normalize_title_strips_prefix():
    assert normalize_title("FS150 Syntactic Cancer") == "syntactic cancer"
    assert normalize_title("Syntactic Cancer") == "syntactic cancer"


def test_remote_index_finds_by_title_when_number_missing():
    podcast = PodcastConfig(
        id="freakshow",
        name="Freak Show",
        language="de",
        episode_id=EpisodeIdConfig(type="podlove_number"),
    )
    discovered = [
        Episode(
            number=41,
            title="Syntactic Cancer",
            source_id="1000534887674",
            published_at="2015-02-05T15:49:21Z",
        )
    ]
    index = build_remote_index(podcast, discovered)
    catalog_ep = Episode(
        number=150,
        title="FS150 Syntactic Cancer",
        published_at="Thu, 05 Feb 2015 15:49:21 +0000",
    )
    remote = index.find(catalog_ep)
    assert remote is not None
    assert remote.source_id == "1000534887674"


def test_remote_index_finds_by_date():
    podcast = PodcastConfig(
        id="freakshow",
        name="Freak Show",
        language="de",
        episode_id=EpisodeIdConfig(type="podlove_number"),
    )
    discovered = [
        Episode(
            number=41,
            title="Totally Different Title",
            source_id="track-1",
            published_at="2015-02-05T15:49:21Z",
        )
    ]
    index = build_remote_index(podcast, discovered)
    catalog_ep = Episode(
        number=150,
        title="FS150 Syntactic Cancer",
        published_at="Thu, 05 Feb 2015 15:49:21 +0000",
    )
    assert index.find(catalog_ep).source_id == "track-1"


def test_catalog_number_for_remote_skips_sequential_fallback():
    podcast = PodcastConfig(
        id="freakshow",
        name="Freak Show",
        language="de",
        episode_id=EpisodeIdConfig(type="podlove_number"),
    )
    ep = Episode(number=41, title="Syntactic Cancer")
    assert catalog_number_for_remote(podcast, ep) is None


def test_published_date_key_parses_rss_and_iso():
    assert published_date_key("2015-02-05T15:49:21Z") == "2015-02-05"
    assert published_date_key("Thu, 05 Feb 2015 15:49:21 +0000") == "2015-02-05"
