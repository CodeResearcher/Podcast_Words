"""Whisper transcription for the whisper_rss source.

Downloads an episode's audio and transcribes it with a German Whisper model,
returning a Transcript built from the timestamped chunks. The model is loaded
lazily and cached so a backfill of many episodes only loads it once.

Long podcasts (Freak Show episodes routinely run 3-5 hours) are decoded to a
16 kHz mono WAV and split into fixed-length segments that are transcribed one
at a time. This keeps peak memory flat regardless of episode length (feeding a
whole multi-hour file to the pipeline at once is what previously OOM-killed the
process) and lets us persist progress to the VTT after every segment, so a
crash never throws away finished work.

Heavy ML dependencies (torch, transformers) are imported lazily so the rest of
the package works without them installed.
"""

from __future__ import annotations

import gc
import os
import subprocess
import tempfile
from pathlib import Path

import requests

from podcast_words.catalog import Episode
from podcast_words.config import PodcastConfig, SourceConfig
from podcast_words.models import Transcript, TranscriptCue
from podcast_words.sources._net import UnsafeURLError, assert_safe_url
from podcast_words.transcripts import vtt

_MODEL_ID = "primeline/whisper-large-v3-turbo-german"
_TIMEOUT = 120
# Cap audio downloads so a hostile/oversized enclosure can't exhaust disk.
_MAX_DOWNLOAD_BYTES = 800 * 1024 * 1024  # 800 MB

_SAMPLE_RATE = 16000
# Tunable without code changes; keep batches small so peak GPU/shared memory
# stays bounded, and segments short enough that one unit of work is cheap.
_SEGMENT_SECONDS = int(os.environ.get("PODCASTWORDS_WHISPER_SEGMENT", "600"))
_BATCH_SIZE = int(os.environ.get("PODCASTWORDS_WHISPER_BATCH", "4"))

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
        batch_size=_BATCH_SIZE,
        torch_dtype=torch_dtype,
        device=device,
        return_timestamps=True,
    )
    return _pipe


def _free_memory() -> None:
    """Release cached GPU/MPS allocations between segments and episodes."""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            torch.mps.empty_cache()
    except Exception:
        pass


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


def _ffmpeg(*args: str) -> bool:
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("  ffmpeg not found on PATH; cannot decode audio.")
        return False
    if proc.returncode != 0:
        print(f"  ffmpeg failed: {proc.stderr.decode('utf-8', 'replace')[:200]}")
    return proc.returncode == 0


def _decode_to_wav(src: Path, dst: Path) -> bool:
    """Decode arbitrary audio to 16 kHz mono PCM WAV (Whisper's expected input)."""
    return _ffmpeg("-i", str(src), "-vn", "-ac", "1", "-ar", str(_SAMPLE_RATE), str(dst))


def _segment_wav(wav: Path, out_dir: Path) -> list[Path]:
    """Split a WAV into fixed-length pieces. PCM splits at exact second offsets."""
    pattern = str(out_dir / "seg_%05d.wav")
    ok = _ffmpeg(
        "-i", str(wav),
        "-f", "segment",
        "-segment_time", str(_SEGMENT_SECONDS),
        "-c", "copy",
        pattern,
    )
    if not ok:
        return []
    return sorted(out_dir.glob("seg_*.wav"))


def _cues_from_chunks(chunks: list[dict], offset_ms: int) -> list[TranscriptCue]:
    cues: list[TranscriptCue] = []
    previous_end = offset_ms
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        ts = chunk.get("timestamp") or (None, None)
        start, end = (list(ts) + [None, None])[:2]
        start_ms = int(start * 1000) + offset_ms if start is not None else previous_end
        end_ms = int(end * 1000) + offset_ms if end is not None else start_ms
        if end_ms < start_ms:
            end_ms = start_ms
        previous_end = end_ms
        cues.append(TranscriptCue(start_ms=start_ms, end_ms=end_ms, text=text))
    return cues


def fetch_transcript(
    podcast: PodcastConfig, source: SourceConfig, episode: Episode
) -> Transcript | None:
    """Download and transcribe an episode, or None if the audio is unavailable.

    The audio is decoded once, segmented, and transcribed segment-by-segment so
    memory stays bounded; the VTT is rewritten after each segment so progress
    survives an interruption.
    """
    if not episode.link:
        return None

    out_vtt = podcast.transcripts_dir / f"episode_{episode.number}.vtt"
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        src_path = tmpdir / f"episode_{episode.number}.audio"
        if not _download(episode.link, src_path):
            return None

        wav_path = tmpdir / "audio.wav"
        if not _decode_to_wav(src_path, wav_path):
            return None
        src_path.unlink(missing_ok=True)  # free disk before segmenting

        seg_dir = tmpdir / "segments"
        seg_dir.mkdir()
        segments = _segment_wav(wav_path, seg_dir)
        if not segments:
            segments = [wav_path]
        else:
            wav_path.unlink(missing_ok=True)

        pipe = _get_pipeline()
        cues: list[TranscriptCue] = []
        total = len(segments)
        for index, segment in enumerate(segments):
            offset_ms = index * _SEGMENT_SECONDS * 1000
            result = pipe(
                str(segment),
                generate_kwargs={"language": "german", "task": "transcribe"},
            )
            chunks = result.get("chunks") if isinstance(result, dict) else None
            if chunks:
                cues.extend(_cues_from_chunks(chunks, offset_ms))
            segment.unlink(missing_ok=True)

            # Persist after every segment so a crash keeps the work done so far.
            if cues:
                podcast.transcripts_dir.mkdir(parents=True, exist_ok=True)
                vtt.write_file(Transcript(cues=cues), out_vtt)
            print(f"    segment {index + 1}/{total} done ({len(cues)} cues)", flush=True)
            _free_memory()

        return Transcript(cues=cues) if cues else None
