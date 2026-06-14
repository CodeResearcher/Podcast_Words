import json
import re
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objs as go
import streamlit as st

from podcast_words.catalog import STATE_DONE, Catalog
from podcast_words.config import load_config, sorted_podcast_ids

st.set_page_config(layout="wide")

_SOURCE_LABELS = {
    "podlove": "PodLove",
    "apple": "Apple Podcasts",
    "whisper": "Whisper",
    "whisper_rss": "Whisper",
    "manual": "Manual",
    "vtt_import": "Manual import",
    "unknown": "Unknown",
}

_AUDIO_SUFFIXES = (".mp3", ".m4a", ".wav", ".ogg", ".aac")
_HOVER_WITH_LINK = (
    "Episode %{x}<br>%{customdata[1]}"
    "<br><a href='%{customdata[0]}'>Open episode</a><extra></extra>"
)
_HOVER_NO_LINK = "Episode %{x}<br>%{customdata[1]}<extra></extra>"


def _is_audio_url(url: str) -> bool:
    lower = url.lower().split("?", 1)[0]
    return (
        lower.endswith(_AUDIO_SUFFIXES)
        or "/podlove/file/" in lower
        or "podigee-cdn" in lower
        or "archive.org" in lower
    )


def _episode_url(episode, podcast) -> str:
    """Best public URL for an episode page, falling back to audio when needed."""
    link = (episode.link or "").strip()
    if link and not _is_audio_url(link):
        return link

    apple = podcast.source_of_type("apple")
    track_id = episode.source_id or ""
    # Apple track IDs are long numerics; PodLove/RSS internal IDs are shorter.
    if (
        apple
        and episode.transcript_source == "apple"
        and track_id.isdigit()
        and len(track_id) >= 9
    ):
        country = (apple.country or "US").lower()
        return (
            f"https://podcasts.apple.com/{country}/podcast/"
            f"id{apple.podcast_id}?i={track_id}"
        )

    return link


def _episode_hover_customdata(episode_numbers, meta: dict[int, dict[str, str]]):
    urls: list[str] = []
    titles: list[str] = []
    for number in episode_numbers:
        row = meta.get(int(number), {})
        urls.append(row.get("url", ""))
        titles.append(row.get("title", "") or f"Episode {number}")
    return list(zip(urls, titles, strict=True))


def _hover_template(customdata: list[tuple[str, str]]) -> str:
    return _HOVER_WITH_LINK if any(url for url, _ in customdata) else _HOVER_NO_LINK


def _selection_points(selection) -> list:
    if selection is None:
        return []
    if hasattr(selection, "get"):
        return selection.get("points") or []
    return getattr(selection, "points", None) or []


def _show_selected_episode_link(selection, meta: dict[int, dict[str, str]], *, axis: str = "x") -> None:
    points = _selection_points(selection)
    if not points:
        return
    point = points[0]
    raw = point.get(axis) if isinstance(point, dict) else getattr(point, axis, None)
    if raw is None:
        return
    try:
        number = int(raw)
    except (TypeError, ValueError):
        match = re.search(r"(\d+)", str(raw))
        if not match:
            return
        number = int(match.group(1))
    row = meta.get(number, {})
    url = row.get("url", "")
    title = row.get("title", "") or f"Episode {number}"
    if url:
        st.link_button(f"Open episode {number}: {title}", url, use_container_width=False)


@st.cache_data
def load_episode_meta(podcast_id: str) -> dict[int, dict[str, str]]:
    config = get_config()
    podcast = config[podcast_id]
    meta: dict[int, dict[str, str]] = {}
    if not podcast.episodes_csv.exists():
        return meta
    catalog = Catalog.load(podcast.episodes_csv)
    for ep in catalog:
        if ep.state != STATE_DONE:
            continue
        meta[ep.number] = {"title": ep.title, "url": _episode_url(ep, podcast)}
    return meta


@st.cache_data
def get_config():
    return {pid: p for pid, p in load_config().items()}


@st.cache_data
def load_data(podcast_id: str):
    config = get_config()
    podcast = config[podcast_id]
    df = pd.read_csv(podcast.word_counts_csv, index_col=0)
    df.fillna(0, inplace=True)
    df = df[df["is_stop"] == False]  # only relevant words
    df = df.drop(columns=["is_stop"])
    df = df.astype("uint32")
    df = df.T  # episodes become rows
    df.index.name = "Episode"
    df.reset_index(inplace=True)
    return df


@st.cache_data
def load_stats(podcast_id: str):
    config = get_config()
    podcast = config[podcast_id]
    with open(podcast.episode_stats_json, "r", encoding="utf-8") as f:
        stats = json.load(f)
    episodes_stats_df = pd.DataFrame(stats["episodes"])
    return stats, episodes_stats_df


@st.cache_data
def load_coverage(podcast_id: str):
    config = get_config()
    podcast = config[podcast_id]
    if not podcast.episodes_csv.exists():
        return None
    catalog = Catalog.load(podcast.episodes_csv)

    by_source: dict[str, int] = {}
    for ep in catalog:
        if ep.state == STATE_DONE:
            src = ep.transcript_source or "unknown"
            by_source[src] = by_source.get(src, 0) + 1

    latest_at: datetime | None = None
    latest_episode: int | None = None
    episode_re = re.compile(r"episode_(\d+)\.vtt$")
    for vtt_path in podcast.transcripts_dir.glob("episode_*.vtt"):
        match = episode_re.search(vtt_path.name)
        if not match:
            continue
        mtime = datetime.fromtimestamp(vtt_path.stat().st_mtime, tz=timezone.utc)
        if latest_at is None or mtime > latest_at:
            latest_at = mtime
            latest_episode = int(match.group(1))

    latest_title = ""
    if latest_episode is not None:
        ep = catalog.get(latest_episode)
        latest_title = ep.title if ep else ""

    return {
        "total": len(catalog),
        "states": catalog.state_counts(),
        "by_source": by_source,
        "latest_transcript_at": latest_at,
        "latest_transcript_episode": latest_episode,
        "latest_transcript_title": latest_title,
    }


config = get_config()
available_ids = sorted_podcast_ids({pid: p for pid, p in config.items() if p.has_data()})
available = {pid: config[pid] for pid in available_ids}

st.sidebar.title("🎙️ Podcast Words")
if not available:
    st.title("🎙️ Podcast Words")
    st.warning(
        "No podcast data found yet. Build a dataset with:\n\n"
        "`python -m podcast_words sync --podcast <id>`"
    )
    st.stop()

podcast_id = st.sidebar.selectbox(
    "Podcast",
    options=available_ids,
    format_func=lambda pid: available[pid].name,
)

podcast = available[podcast_id]
coverage = load_coverage(podcast_id)

if coverage:
    with_transcript = coverage["states"].get("done", 0)
    st.sidebar.caption(
        f"{with_transcript}/{coverage['total']} episodes with transcripts"
    )
    if coverage["latest_transcript_at"] is not None:
        fetched = coverage["latest_transcript_at"].astimezone()
        ep_no = coverage["latest_transcript_episode"]
        title = coverage["latest_transcript_title"]
        label = f"#{ep_no} {title}".strip() if ep_no is not None else "—"
        st.sidebar.caption(
            f"Latest transcript: {fetched.strftime('%Y-%m-%d %H:%M %Z')} — {label}"
        )
    if coverage["by_source"]:
        parts = [
            f"{_SOURCE_LABELS.get(src, src)}: {count}"
            for src, count in sorted(
                coverage["by_source"].items(), key=lambda item: (-item[1], item[0])
            )
        ]
        st.sidebar.caption("Transcripts by source: " + " · ".join(parts))

df = load_data(podcast_id)
stats, episodes_stats_df = load_stats(podcast_id)
episode_meta = load_episode_meta(podcast_id)

st.title(f"🎙️ {podcast.name} — Word Analysis")

if coverage:
    with_transcript = coverage["states"].get("done", 0)
    st.caption(f"{with_transcript}/{coverage['total']} episodes with transcripts")

# Word selection
word_columns = df.columns.drop("Episode")
default_words = [w for w in podcast.search_words if w in set(word_columns)]
selected_words = st.multiselect("🔍 Choose words", word_columns, default=default_words)

if selected_words:
    df_selected = df[["Episode"] + selected_words]
    line_customdata = _episode_hover_customdata(df_selected["Episode"], episode_meta)

    st.subheader("📊 Frequency of selected words across all episodes")
    fig_line = go.Figure()
    for word in selected_words:
        fig_line.add_trace(
            go.Scatter(
                x=df_selected["Episode"],
                y=df_selected[word],
                mode="lines",
                stackgroup="one",
                name=word,
                customdata=line_customdata,
                hovertemplate=_hover_template(line_customdata),
            )
        )
    fig_line.update_layout(xaxis_title="Episode", yaxis_title="Count", width=1000, height=400)
    line_event = st.plotly_chart(fig_line, use_container_width=False, on_select="rerun", key="word_line")
    _show_selected_episode_link(line_event.selection if line_event else None, episode_meta)

    st.subheader("🏅 Top 10 episodes for the selected words")
    df_selected = df_selected.copy()
    df_selected["total_selected"] = df_selected[selected_words].sum(axis=1)
    top10 = df_selected.sort_values("total_selected", ascending=False).head(10)
    top10["Episode_str"] = "Episode " + top10["Episode"].astype(str)
    top10_sorted = top10.sort_values("total_selected", ascending=True)
    bar_customdata = _episode_hover_customdata(top10_sorted["Episode"], episode_meta)

    fig_bar = go.Figure()
    for word in selected_words:
        fig_bar.add_trace(
            go.Bar(
                x=top10_sorted[word],
                y=top10_sorted["Episode_str"],
                name=word,
                orientation="h",
                customdata=bar_customdata,
                hovertemplate=(
                    "%{y}<br>%{customdata[1]}"
                    + (
                        "<br><a href='%{customdata[0]}'>Open episode</a><extra></extra>"
                        if any(url for url, _ in bar_customdata)
                        else "<extra></extra>"
                    )
                ),
            )
        )
    fig_bar.update_layout(
        barmode="stack",
        xaxis_title="Count",
        yaxis_title="Episode (top 10)",
        width=1000,
        height=500,
        yaxis=dict(type="category"),
    )
    bar_event = st.plotly_chart(fig_bar, use_container_width=False, on_select="rerun", key="word_bar")
    _show_selected_episode_link(bar_event.selection if bar_event else None, episode_meta, axis="y")
else:
    st.info("⬆ Please select one or more words above.")

# General statistics
st.header("📋 General statistics")
col1, col2, col3 = st.columns(3)
col1.metric("🎧 Episodes", stats["total_episodes"])
col2.metric("🗣️ Total words spoken", f"{stats['total_words']:,}")
col3.metric("🔤 Distinct words", f"{stats['total_unique_words']:,}")

stats_customdata = _episode_hover_customdata(episodes_stats_df["episode"], episode_meta)
stats_hover = _hover_template(stats_customdata)

st.subheader("📈 Words per episode")
fig_total = go.Figure(
    go.Scatter(
        x=episodes_stats_df["episode"],
        y=episodes_stats_df["total_words"],
        mode="lines+markers",
        customdata=stats_customdata,
        hovertemplate=stats_hover,
    )
)
fig_total.update_layout(xaxis_title="Episode", yaxis_title="Words", width=1000, height=300)
total_event = st.plotly_chart(fig_total, use_container_width=False, on_select="rerun", key="stats_total")
_show_selected_episode_link(total_event.selection if total_event else None, episode_meta)

st.subheader("🔠 Distinct words per episode")
fig_unique = go.Figure(
    go.Scatter(
        x=episodes_stats_df["episode"],
        y=episodes_stats_df["unique_words"],
        mode="lines+markers",
        customdata=stats_customdata,
        hovertemplate=stats_hover,
    )
)
fig_unique.update_layout(xaxis_title="Episode", yaxis_title="Count", width=1000, height=300)
unique_event = st.plotly_chart(fig_unique, use_container_width=False, on_select="rerun", key="stats_unique")
_show_selected_episode_link(unique_event.selection if unique_event else None, episode_meta)

st.subheader("🆕 New words per episode")
fig_new = go.Figure(
    go.Scatter(
        x=episodes_stats_df["episode"],
        y=episodes_stats_df["new_words"],
        mode="lines+markers",
        customdata=stats_customdata,
        hovertemplate=stats_hover,
    )
)
fig_new.update_layout(
    xaxis_title="Episode",
    yaxis_title="New words",
    yaxis_type="log",
    title="New words per episode (logarithmic)",
    width=1000,
    height=300,
)
new_event = st.plotly_chart(fig_new, use_container_width=False, on_select="rerun", key="stats_new")
_show_selected_episode_link(new_event.selection if new_event else None, episode_meta)

with st.expander("🔧 How this analysis is built"):
    st.markdown(
        """
        Transcripts are collected per podcast from the configured source
        (RSS + Whisper, the PodLove Publisher API, Apple Podcasts, or manual
        import) and stored as WebVTT files. They are then lemmatized with spaCy,
        stop words are removed, and word frequencies are aggregated per episode.

        See the project README for the full multi-podcast workflow.
        """
    )
