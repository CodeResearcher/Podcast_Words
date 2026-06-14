import os

from podcast_words import progress


def test_progress_disabled_outside_tty(monkeypatch):
    monkeypatch.setenv("PODCASTWORDS_NO_PROGRESS", "1")
    assert progress.progress_enabled() is False
    assert list(progress.iter_progress([1, 2, 3], desc="test")) == [1, 2, 3]


def test_progress_opt_out_env(monkeypatch):
    monkeypatch.delenv("PODCASTWORDS_NO_PROGRESS", raising=False)
    monkeypatch.setattr(progress.sys.stderr, "isatty", lambda: True)
    monkeypatch.setenv("PODCASTWORDS_NO_PROGRESS", "1")
    assert progress.progress_enabled() is False


def test_write_without_bar(capsys, monkeypatch):
    monkeypatch.setenv("PODCASTWORDS_NO_PROGRESS", "1")
    progress.write("hello")
    assert capsys.readouterr().out.strip() == "hello"
