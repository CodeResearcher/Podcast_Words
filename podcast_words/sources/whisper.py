"""Whisper transcription for the whisper_rss source.

Downloads an episode's audio and transcribes it with a German Whisper model,
returning a Transcript built from the timestamped chunks. The model is loaded
lazily and cached so a backfill of many episodes only loads it once.

Heavy ML dependencies (torch, transformers) are imported lazily so the rest of
the package works without them installed.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import requests

from podcast_words.catalog import Episode
from podcast_words.config import PodcastConfig, SourceConfig
from podcast_words.models import Transcript, TranscriptCue
from podcast_words.sources._net import UnsafeURLError, assert_safe_url

_MODEL_ID = "primeline/whisper-large-v3-turbo-german"
_TIMEOUT = 120
# Cap audio downloads so a hostile/oversized enclosure can't exhaust disk.
_MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
_pipe = None


def _get_pipeline():
    global _pipe
    if _pipe is not None:
        return _pipe

    import torch
    from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

    # Prefer CUDA, then Apple Silicon (MPS), then CPU. fp16 only helps on GPU;
    # MPS lacks kernels for some fp16 ops, so keep fp32 there for correctness.
    if torch.cuda.is_available():
        device = "cuda:0"
        torch_dtype = torch.float16
    elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        device = "mps"
        torch_dtype = torch.float32
    else:
        device = "cpu"
        torch_dtype = torch.float32

    model = AutoModelForSpeechSeq2Seq.from_pretrained(
        _MODEL_ID, torch_dtype=torch_dtype, low_cpu_mem_usage=True, use_safetensors=True
    )
    model.to(device)
    processor = AutoProcessor.from_pretrained(_MODEL_ID)

    _pipe = pipeline(
        "automatic-speech-recognition",
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        chunk_length_s=30,
        batch_size=8,
        torch_dtype=torch_dtype,
        device=device,
        return_timestamps=True,
    )
    return _pipe


def _download(url: str, dest: Path) -> bool:
    try:
        assert_safe_url(url)
    except UnsafeURLError as exc:
        print(f"  refusing to download {url}: {exc}")
        return False
    try:
        resp = requests.get(url, stream=True, timeout=_TIMEOUT)
    except requests.RequestException:
        return False
    if resp.status_code != 200:
        return False
    written = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(8192):
            written += len(chunk)
            if written > _MAX_DOWNLOAD_BYTES:
                print(
                    f"  aborting download of {url}: exceeds "
                    f"{_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB limit."
                )
                return False
            f.write(chunk)
    return True


def _chunks_to_transcript(chunks: list[dict]) -> Transcript:
    cues: list[TranscriptCue] = []
    previous_end = 0
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        ts = chunk.get("timestamp") or (None, None)
        start, end = (list(ts) + [None, None])[:2]
        start_ms = int(start * 1000) if start is not None else previous_end
        end_ms = int(end * 1000) if end is not None else start_ms
        if end_ms < start_ms:
            end_ms = start_ms
        previous_end = end_ms
        cues.append(TranscriptCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return Transcript(cues=cues)


def fetch_transcript(
    podcast: PodcastConfig, source: SourceConfig, episode: Episode
) -> Transcript | None:
    """Download and transcribe an episode, or None if the audio is unavailable."""
    if not episode.link:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = Path(tmp) / f"episode_{episode.number}.mp3"
        if not _download(episode.link, audio_path):
            return None
        pipe = _get_pipeline()
        result = pipe(str(audio_path))
        chunks = result.get("chunks") if isinstance(result, dict) else None
        if not chunks:
            return None
        transcript = _chunks_to_transcript(chunks)
        return transcript if transcript.cues else None
