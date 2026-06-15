from pathlib import Path

from podcast_words.config import PodcastConfig
from podcast_words.pipeline import reconvert_raw
from podcast_words.transcripts import ttml, vtt

SAMPLE_TTML = """<?xml version="1.0"?>
<tt xmlns="http://www.w3.org/ns/ttml">
  <body>
    <p begin="0.340" end="1:01.239">First cue.</p>
    <p begin="1:01.239" end="2:00.000">Second cue.</p>
  </body>
</tt>
"""


def test_reconvert_raw_updates_incomplete_vtt(tmp_path, monkeypatch):
    podcast = PodcastConfig(id="demo", name="Demo", language="en")
    monkeypatch.setattr(
        PodcastConfig,
        "transcripts_dir",
        property(lambda self: tmp_path / "transcripts"),
    )
    raw_dir = podcast.transcripts_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "episode_7.ttml").write_text(SAMPLE_TTML, encoding="utf-8")

    # Truncated VTT: only one cue while TTML has two.
    single_cue = ttml.parse(
        """<?xml version="1.0"?>
<tt xmlns="http://www.w3.org/ns/ttml"><body>
<p begin="0.340" end="1:01.239">First cue.</p>
</body></tt>"""
    )
    vtt.write_file(single_cue, podcast.transcripts_dir / "episode_7.vtt")

    result = reconvert_raw.reconvert_raw(podcast)
    assert result["updated"] == 1
    assert len(vtt.parse_file(podcast.transcripts_dir / "episode_7.vtt").cues) == 2


def test_reconvert_raw_skips_complete_vtt(tmp_path, monkeypatch):
    podcast = PodcastConfig(id="demo", name="Demo", language="en")
    monkeypatch.setattr(
        PodcastConfig,
        "transcripts_dir",
        property(lambda self: tmp_path / "transcripts"),
    )
    raw_dir = podcast.transcripts_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "episode_3.ttml").write_text(SAMPLE_TTML, encoding="utf-8")
    transcript = ttml.parse(SAMPLE_TTML)
    vtt.write_file(transcript, podcast.transcripts_dir / "episode_3.vtt")

    result = reconvert_raw.reconvert_raw(podcast)
    assert result["updated"] == 0
    assert result["skipped"] == 1
