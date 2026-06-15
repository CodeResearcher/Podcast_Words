from podcast_words.config import PodcastConfig
from podcast_words.word_search import (
    active_search_term,
    default_selected_words,
    format_selected_display,
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


def test_format_selected_display():
    assert format_selected_display([]) == ""
    assert format_selected_display(["eimer", "münze", "cent"]) == "eimer, münze, cent"


def test_active_search_term():
    assert active_search_term("") == ""
    assert active_search_term("ukraine") == "ukraine"
    assert active_search_term("eimer, münze, dat") == "dat"
    assert active_search_term("eimer, ") == ""


def test_default_selected_words():
    podcast = PodcastConfig(
        id="test",
        name="Test",
        language="de",
        search_words=["alpha", "missing", "beta"],
    )
    vocab = frozenset({"alpha", "beta", "gamma"})
    assert default_selected_words(podcast.search_words, vocab) == ["alpha", "beta"]
