# Plan

extend this project with following features:

- support multiple podcasts which can be configurated
- select between available podcasts in streamlit app
- support different transcript sources depending on podcast:
    - RSS feed + Whisper
    - manually add single transcripts for specific episode
    - import transcripts from PodLove Publisher API
    - import transcripts from Apple Podcasts by Podcast ID
- import all existing episodes
- import new published episodes
- support all common transcript formats
- optimize lemmatisation and counting where reasonable
- update README.md to consider latest changes and translate into English
- add disclaimer that this fork was adjusted with Cursor AI and mention the LLM versions which were used

## PodLove Publisher API

### Documentation

- https://docs.podlove.org/podlove-publisher/api/#tag/episodes
- https://docs.podlove.org/podlove-publisher/api/#tag/transcripts

### Sample Endpoint

- https://freakshow.fm/wp-json/podlove/v2/

## Apple Podcast Export

### Documentation

- https://blog.alexbeals.com/posts/downloading-arbitrary-apple-podcast-episode-transcripts
- https://alexbeals.com/projects/podcasts/

### Sample Repositories

- https://github.com/dado3212/apple-podcast-transcripts
- https://github.com/dado3212/apple-podcast-transcript-downloader
- https://github.com/Danjohnsonnj/apple-podcast-transcript-extractor