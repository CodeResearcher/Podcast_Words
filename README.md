# Podcast Words

Analyze how often words are spoken across podcast episodes. Originally built for
the German comedy podcast *Das Podcast-Ufo* (to find an episode when you only
half-remember what was said), it now supports **multiple podcasts** and several
transcript sources.

🚀 **[Live demo (PUFO)](https://podcast-words.streamlit.app/)** 🎧

![App screenshot](app_example.png "Screenshot")

## Features

- **Multiple podcasts**, configured in `config/podcasts.yaml`
- **Switch between podcasts** in the Streamlit app (display order via `order`)
- **Per-podcast transcript sources:**
  - PodLove Publisher API (all episodes)
  - Apple Podcasts by Podcast ID (all episodes, macOS)
  - RSS feed + Whisper transcription (with Apple Silicon / CUDA support)
  - Manual import of a single episode transcript
- **Multi-source fallback:** recover missing transcripts from secondary sources
  (`sync --fallback`)
- **Replace existing transcripts** from another configured source
  (`sync --replace-from`)
- **Import all existing episodes** (backfill) and **pick up newly published
  episodes** (incremental) with one command
- **Progress bars** for transcript fetching and word counting in the CLI
- **Common transcript formats:** WebVTT, SRT, Apple TTML, plain text, and the
  legacy Whisper output

## How it works

Each podcast keeps its own data under `data/{podcast_id}/`:

| Path | Contents |
|------|----------|
| `episodes.csv` | The episode catalog (every known episode + transcript state) |
| `transcripts/` | Canonical WebVTT transcripts (`episode_{n}.vtt`) |
| `word_counts.csv` | Word-frequency matrix (one column per episode) |
| `episode_stats.json` | Per-episode and aggregate statistics |
| `sync_state.json` | Last sync timestamp and episode count |

Transcripts are collected from the configured source, normalized to WebVTT,
lemmatized with spaCy (stop words removed), and aggregated into the word matrix
that the Streamlit app visualizes.

```
config/podcasts.yaml ─▶ sync (discover ▶ import ▶ count) ─▶ data/{id}/ ─▶ app.py
```

## Installation

Tested with Python 3.11+. `ffmpeg` is required for Whisper transcription.

```sh
python -m venv .venv
source .venv/bin/activate

# App + core tooling (pinned versions in requirements.txt)
pip install -r requirements.txt

# spaCy language models (per podcast language)
python -m spacy download de_core_news_lg   # German
python -m spacy download en_core_web_lg     # English

# Optional: Whisper transcription stack (only for the whisper_rss source)
pip install torch torchvision torchaudio
pip install transformers accelerate
```

## Configuration

Define your podcasts in `config/podcasts.yaml`. Each entry supports:

| Field | Purpose |
|-------|---------|
| `name` | Display name in the app |
| `order` | Sort order in the Streamlit selector (lower = first) |
| `language` | spaCy model language (`de`, `en`, …) |
| `episode_id` | How to number episodes (`regex`, `podlove_number`, `sequential`) |
| `sources` | One or more transcript sources (tried in order) |
| `defaults.search_words` | Pre-selected words in the Streamlit app |

Example with PodLove primary source and Apple fallback:

```yaml
podcasts:
  freakshow:
    name: "Freak Show"
    order: 10
    language: de
    episode_id:
      type: podlove_number
    sources:
      - type: podlove
        api_base: "https://freakshow.fm/wp-json/podlove/v2"
      - type: apple
        podcast_id: "277518737"
        country: DE
      - type: whisper_rss
        feed_url: "https://freakshow.fm/feed/mp3"
    defaults:
      search_words: []

  tribuenengespraech:
    name: "Rasenfunk – Tribünengespräch"
    order: 50
    language: de
    episode_id:
      type: sequential
    sources:
      - type: apple
        podcast_id: "916269734"
        country: DE
    defaults:
      search_words: []
```

Configured podcasts in this repository: **Freak Show**, **Logbuch:Netzpolitik**,
**UKW**, **Die Neuen Zwanziger**, **Rasenfunk – Tribünengespräch**, and
**Das Podcast-Ufo**.

## Command-line usage

```sh
# List configured podcasts (✓ marks ones with built data)
python -m podcast_words list

# Sync: discover episodes, import transcripts, count words.
# First run backfills ALL existing episodes; later runs add only new ones.
python -m podcast_words sync --podcast freakshow

# Recover missing transcripts from secondary sources (e.g. Apple after PodLove)
python -m podcast_words sync --podcast freakshow --fallback

# Replace existing transcripts with ones from another source
python -m podcast_words sync --podcast freakshow --replace-from apple
python -m podcast_words sync --podcast freakshow --replace-from whisper_rss \
  --replace-if-from podlove

# Retry every pending / missing transcript across the full catalog
python -m podcast_words sync --podcast freakshow --backfill

# Re-fetch all transcripts from scratch
python -m podcast_words sync --podcast freakshow --force

# Batch slow sources (Whisper): fetch/count only the first N episodes
python -m podcast_words sync --podcast freakshow --source whisper_rss \
  --backfill --limit 3 --no-count

# Skip word counting during sync (faster for large backfills)
python -m podcast_words sync --podcast logbuch_netzpolitik --no-count

# Manually import a single episode transcript (auto-detects format)
python -m podcast_words import --podcast pufo --episode 420 --file ./episode.vtt

# Import every transcript file in a folder
python -m podcast_words import --podcast pufo --dir ./transcripts/

# Recompute word counts only
python -m podcast_words count --podcast pufo
python -m podcast_words count --podcast pufo --rebuild
```

Progress bars appear automatically in the terminal. Set
`PODCASTWORDS_NO_PROGRESS=1` to disable them.

Whisper tuning (optional environment variables):

| Variable | Default | Purpose |
|----------|---------|---------|
| `PODCASTWORDS_WHISPER_SEGMENT` | `600` | Audio segment length in seconds |
| `PODCASTWORDS_WHISPER_BATCH` | `4` | Pipeline batch size |

### Source-specific notes

- **PodLove** needs only the public `api_base` URL; transcripts are fetched
  read-only. Episode numbering uses `podlove_number`, a title regex, or
  sequential order by PodLove ID.
- **RSS + Whisper** downloads each episode's audio and transcribes it locally.
  Long episodes are split into segments to keep memory bounded; partial results
  are saved after each segment. Uses CUDA when available, then Apple Silicon
  (MPS), then CPU.
- **Apple Podcasts** is described below.

## Apple Podcasts by Podcast ID

You configure only the **Podcast ID** (the show ID); episode discovery and
transcript fetching are automatic.

Find the Podcast ID in the show URL on
[podcasts.apple.com](https://podcasts.apple.com): the number after `id`, e.g.
`https://podcasts.apple.com/de/podcast/rasenfunk-trib%C3%BCnengespr%C3%A4ch/id916269734`
→ `916269734`.

Episode discovery uses the public iTunes Lookup API for shows with at most 200
episodes. Larger catalogs fall back to paginated amp-api requests (same bearer
token as transcript download). Fetching the actual transcript requires the
vendored `FetchTranscript` helper:

- **macOS 15.5 or newer only** (does not work on macOS 14.x or on Linux/CI)
- Requires the Apple Podcasts app signed in on the machine (for the bearer token)
- Build the helper once (see [tools/apple/README.md](tools/apple/README.md)):

```sh
cd tools/apple
clang -Wno-objc-method-access -framework Foundation \
  -F/System/Library/PrivateFrameworks -framework AppleMediaServices \
  FetchTranscript.m -o FetchTranscript
```

Then `python -m podcast_words sync --podcast tribuenengespraech` discovers all
episodes and downloads their transcripts (TTML), converting them to WebVTT. If
you already have transcripts cached locally by the Apple Podcasts app, you can
also export them with
[apple-podcast-transcript-extractor](https://github.com/Danjohnsonnj/apple-podcast-transcript-extractor)
and `import --dir` the resulting files.

## Running the app

```sh
source .venv/bin/activate
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501).

The sidebar shows:

- Podcast selector (sorted by `order` in config)
- Episode coverage and **transcripts by source** (PodLove, Apple, Whisper, …)
- **Latest fetched transcript** (date, episode number, title)

Charts include episode titles in tooltips, clickable links to episode pages
(hover or click a point), and pre-selected search words from config.

Only podcasts with a built `word_counts.csv` appear in the selector.

### Deploying the app securely

The dashboard is **read-only and has no authentication** — it only displays
already-built, public word-frequency data. If you expose it beyond your own
machine:

- Put it **behind a reverse proxy with TLS** (e.g. nginx/Caddy); do not bind
  Streamlit directly to a public interface.
- Keep the shipped [`.streamlit/config.toml`](.streamlit/config.toml), which
  disables usage telemetry and CORS and keeps XSRF protection on.
- The sync/import CLI is for trusted operators only. Transcript sources are
  validated where practical (XML is parsed with `defusedxml`, audio downloads
  are size-capped and blocked from non-public addresses, configured non-HTTPS
  URLs emit a warning), but you should still only configure feeds you trust.

## Migrating the original PUFO data

If you have the original repository layout (root `word_counts.csv`,
`episode_stats.json`, and `episode_processor/text/`), run the one-time
migration to populate `data/pufo/`:

```sh
python scripts/migrate_pufo.py
```

This copies the generated data, converts the legacy Whisper `.txt` transcripts
to WebVTT, and builds the `episodes.csv` catalog.

## Development

```sh
pip install -e ".[dev]"
pytest
```

See [docs/PLAN.md](docs/PLAN.md) for the full implementation plan.

## Limitations

- Whisper occasionally mis-transcribes words, especially with crosstalk.
- spaCy lemmatization is imperfect; not every word maps to a clean stem.
- Apple transcript fetching is macOS-only and depends on Apple's private API.
- Word counting on CPU is slow for large catalogs; run `--no-count` during sync
  and count separately.

## ToDos

- add YouTube transcripts as additional source
- count words by speaker in total and per episode

## Disclaimer

This fork was extended with the help of **Cursor AI**. The multi-podcast
refactor, transcript adapters, sync pipeline, security hardening, and tests
were planned and implemented using Cursor with Anthropic Claude models (Claude
Opus 4.x). Generated code was reviewed and validated against the live PodLove,
RSS, and iTunes endpoints, but please double-check anything security- or
billing-sensitive before relying on it.
