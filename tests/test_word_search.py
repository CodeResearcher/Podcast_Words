from podcast_words.config import PodcastConfig
from podcast_words.word_search import (
    default_selected_words,
    extract_query,
    search_vocabulary,
)


def test_search_vocabulary_prefix_and_substring():
    vocab = tuple(
        sorted(
            [
                "datenschutz",
                "hacken",
                "netz",
                "netzpolitik",
                "politik",
                "vorratsdatenspeicherung",
            ]
        )
    )
    assert search_vocabulary(vocab, "n") == []
    assert search_vocabulary(vocab, "net") == ["netz", "netzpolitik"]
    assert search_vocabulary(vocab, "pol") == ["politik", "netzpolitik"]


def test_extract_query():
    assert extract_query("", []) == ""
    assert extract_query("ukraine", []) == "ukraine"
    assert extract_query("ukraine", ["ukraine"]) == ""
    assert extract_query("ukraine dat", ["ukraine"]) == "dat"
    assert extract_query("eimer, münze, dat", ["eimer", "münze"]) == "dat"
    assert extract_query("Eimer, MÜNZE", ["eimer", "münze"]) == ""


def test_default_selected_words():
    podcast = PodcastConfig(
        id="test",
        name="Test",
        language="de",
        search_words=["alpha", "missing", "beta"],
    )
    vocab = frozenset({"alpha", "beta", "gamma"})
    assert default_selected_words(podcast.search_words, vocab) == ["alpha", "beta"]
