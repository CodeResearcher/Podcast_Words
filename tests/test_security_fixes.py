"""Regression tests for the OWASP-review hardening fixes."""

import warnings

import pytest

from podcast_words.catalog import Episode
from podcast_words.config import SourceConfig
from podcast_words.sources import apple, rss
from podcast_words.sources._net import UnsafeURLError, assert_safe_url


def test_csv_formula_injection_is_neutralized():
    row = Episode(number=1, title="=HYPERLINK(\"http://evil\")", link="@SUM(A1)").to_row()
    assert row["title"].startswith("'=")
    assert row["link"].startswith("'@")


def test_csv_safe_leaves_normal_values_untouched():
    row = Episode(number=2, title="Normal Title", link="https://example.com/ep").to_row()
    assert row["title"] == "Normal Title"
    assert row["link"] == "https://example.com/ep"


def test_apple_rejects_non_numeric_source_id(monkeypatch):
    monkeypatch.setattr(apple, "ensure_supported", lambda: None)
    podcast = object()
    source = object()
    episode = Episode(number=1, source_id="--cache-bearer-token")
    with pytest.raises(ValueError):
        apple.fetch_transcript(podcast, source, episode)


@pytest.mark.parametrize("url", ["10.0.0.1", "127.0.0.1", "169.254.169.254"])
def test_ssrf_guard_blocks_non_public_addresses(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(f"http://{url}/audio.mp3")


def test_ssrf_guard_blocks_non_http_scheme():
    with pytest.raises(UnsafeURLError):
        assert_safe_url("file:///etc/passwd")


def test_rss_rejects_dtd_bearing_feed():
    malicious = b"""<?xml version="1.0"?>
<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<rss><channel><item><title>&xxe;</title></item></channel></rss>"""
    with pytest.raises(ValueError):
        rss._reject_unsafe_xml(malicious)


def test_rss_accepts_plain_feed():
    feed = b"<rss><channel><item><title>Episode 1</title></item></channel></rss>"
    rss._reject_unsafe_xml(feed)  # should not raise


def test_insecure_url_warns():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SourceConfig(type="podlove", api_base="http://feeds.example.com/v2")
    assert any("insecure scheme" in str(w.message) for w in caught)


def test_https_url_does_not_warn():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        SourceConfig(type="podlove", api_base="https://feeds.example.com/v2")
    assert not any("insecure scheme" in str(w.message) for w in caught)
