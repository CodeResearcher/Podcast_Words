# Podcast Words

Analyze how often words are spoken across podcast episodes. Originally built for
the German comedy podcast *Das Podcast-Ufo* (to find an episode when you only
half-remember what was said), it now supports **multiple podcasts** and several
transcript sources.

🚀 **[Live demo (PUFO)](https://pufo-words.streamlit.app/)** 🎧

![App screenshot](app_example.png "Screenshot")

## Features

- **Multiple podcasts**, configured in `config/podcasts.yaml`
- **Switch between podcasts** in the Streamlit app
- **Per-podcast transcript sources:**
  - RSS feed + Whisper transcription
  - Manual import of a single episode transcript
  - PodLove Publisher API (all episodes)
  - Apple Podcasts by Podcast ID (all episodes, macOS)
- **Import all existing episodes** (backfill) and **pick up newly published episodes** (incremental) with one command
- **Common transcript formats:** WebVTT, SRT, Apple TTML, plain text, and the legacy Whisper output

## How it works

Each podcast keeps its own data under `data/{podcast_id}/`:

| Path | Contents |
|------|----------|
| `episodes.csv` | The episode catalog (every known episode + transcript state) |
| `transcripts/` | Canonical WebVTT transcripts (`episode_{n}.vtt`) |
| `word_counts.csv` | Word-frequency matrix (one column per episode) |
| `episode_stats.json` | Per-episode and aggregate statistics |

Transcripts are collected from the configured source, normalized to WebVTT,
lemmatized with spaCy (stop words removed), and aggregated into the word matrix
that the Streamlit app visualizes.

```
config/podcasts.yaml ─▶ sync (discover ▶ import ▶ count) ─▶ data/{id}/ ─▶ app.py
```

## Installation

Tested with Python 3.11+. `ffmpeg` is required for Whisper transcription.

```sh
# App + core tooling
pip install -r requirements.txt

# spaCy language models (per podcast language)
python -m spacy download de_core_news_lg   # German
python -m spacy download en_core_web_lg     # English

# Optional: Whisper transcription stack (only for the whisper_rss source)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

## Configuration

Define your podcasts in `config/podcasts.yaml`:

```yaml
podcasts:
  pufo:
    name: "Das Podcast-Ufo"
    language: de
    episode_id:
      type: regex          # regex | podlove_number | sequential
      pattern: "UFO(\\d+)"
    sources:
      - type: whisper_rss
        feed_url: "https://feeds.acast.com/public/shows/podcast-ufo"
    defaults:
      search_words: [eimer, münze, cent]

  freakshow:
    name: "Freak Show"
    language: de
    episode_id:
      type: podlove_number
    sources:
      - type: podlove
        api_base: "https://freakshow.fm/wp-json/podlove/v2"

  daily:
    name: "The Daily"
    language: en
    episode_id:
      type: sequential
    sources:
      - type: apple
        podcast_id: "1200361736"   # see "Apple Podcasts" below
        country: US
```

## Command-line usage

```sh
# List configured podcasts (✓ marks ones with built data)
python -m podcast_words list

# Sync: discover episodes, import transcripts, count words.
# First run backfills ALL existing episodes; later runs add only new ones.
python -m podcast_words sync --podcast freakshow

# Retry every pending / missing transcript across the full catalog
python -m podcast_words sync --podcast freakshow --backfill

# Re-fetch all transcripts from scratch
python -m podcast_words sync --podcast freakshow --force

# Manually import a single episode transcript (auto-detects format)
python -m podcast_words import --podcast pufo --episode 420 --file ./episode.vtt

# Import every transcript file in a folder
python -m podcast_words import --podcast pufo --dir ./transcripts/

# Recompute word counts only
python -m podcast_words count --podcast pufo
```

### Source-specific notes

- **PodLove** needs only the public `api_base` URL; transcripts are fetched read-only.
- **RSS + Whisper** downloads each episode's audio and transcribes it locally
  (GPU strongly recommended). Only episodes without a transcript are processed.
- **Apple Podcasts** is described below.

## Apple Podcasts by Podcast ID

You configure only the **Podcast ID** (the show ID); episode discovery and
transcript fetching are automatic.

Find the Podcast ID in the show URL on
[podcasts.apple.com](https://podcasts.apple.com): the number after `id`, e.g.
`https://podcasts.apple.com/us/podcast/the-daily/id1200361736` → `1200361736`.

Episode discovery uses the public iTunes Lookup API (no authentication).
Fetching the actual transcript requires the vendored `FetchTranscript` helper:

- **macOS 15.5 or newer only** (does not work on macOS 14.x or on Linux/CI)
- Requires the Apple Podcasts app signed in on the machine (for the bearer token)
- Build the helper once (see [tools/apple/README.md](tools/apple/README.md)):

```sh
cd tools/apple
clang -Wno-objc-method-access -framework Foundation \
  -F/System/Library/PrivateFrameworks -framework AppleMediaServices \
  FetchTranscript.m -o FetchTranscript
```

Then `python -m podcast_words sync --podcast daily` discovers all episodes and
downloads their transcripts (TTML), converting them to WebVTT. If you already
have transcripts cached locally by the Apple Podcasts app, you can also export
them with
[apple-podcast-transcript-extractor](https://github.com/Danjohnsonnj/apple-podcast-transcript-extractor)
and `import --dir` the resulting files.

## Running the app

```sh
streamlit run app.py
```

Pick a podcast in the sidebar to load its full episode set, charts, and stats.
Only podcasts with a built `word_counts.csv` appear in the selector.

## Migrating the original PUFO data

If you have the original repository layout (root `word_counts.csv`,
`episode_stats.json`, and `episode_processor/text/`), run the one-time
migration to populate `data/pufo/`:

```sh
python scripts/migrate_pufo.py
```

This copies the generated data, converts the legacy Whisper `.txt` transcripts
to WebVTT, and builds the `episodes.csv` catalog.

## Limitations

- Whisper occasionally mis-transcribes words, especially with crosstalk.
- spaCy lemmatization is imperfect; not every word maps to a clean stem.
- Apple transcript fetching is macOS-only and depends on Apple's private API.

## Disclaimer

This fork was extended with the help of **Cursor AI**. The multi-podcast
refactor, transcript adapters, sync pipeline, and tests were planned and
implemented using Cursor with Anthropic Claude models (Claude Opus 4.x).
Generated code was reviewed and validated against the live PodLove, RSS, and
iTunes endpoints, but please double-check anything security- or
billing-sensitive before relying on it.
