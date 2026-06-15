# Apple FetchTranscript helper

`FetchTranscript.m` downloads an Apple Podcasts episode transcript (TTML) given
an episode ID. It is vendored from
[dado3212/apple-podcast-transcript-downloader](https://github.com/dado3212/apple-podcast-transcript-downloader)
(MIT License) and called by `podcast_words/sources/apple.py`.

## Requirements

- macOS 15.5 or newer (confirmed not to work on macOS 14.x)
- Xcode command line tools (`clang`)
- The Apple Podcasts app signed in on this machine (used to obtain a bearer token)

## Build

```bash
clang -Wno-objc-method-access \
  -framework Foundation \
  -F/System/Library/PrivateFrameworks \
  -framework AppleMediaServices \
  FetchTranscript.m -o FetchTranscript
```

This produces the `FetchTranscript` binary that `apple.py` expects at
`tools/apple/FetchTranscript`.

## Usage

```bash
./FetchTranscript <episodeId> [--cache-bearer-token]
./FetchTranscript --bearer-token-only [--cache-bearer-token]
```

`--bearer-token-only` prints a Bearer token for amp-api catalog requests (used
by `apple_catalog.py` when a show has more than 200 episodes).

The episode ID is the `?i=` query value from an Apple Podcasts share link, e.g.
`https://podcasts.apple.com/us/podcast/.../id1728932037?i=1000714478537` →
`1000714478537`. `podcast_words` discovers these IDs automatically from the show
Podcast ID via the iTunes Lookup API (and amp-api for larger catalogs), so you
normally do not run this directly.
