import json

import pandas as pd
import plotly.graph_objs as go
import streamlit as st

from podcast_words.catalog import Catalog
from podcast_words.config import load_config

st.set_page_config(layout="wide")


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
    return {"total": len(catalog), "states": catalog.state_counts()}


config = get_config()
available = {pid: p for pid, p in config.items() if p.has_data()}

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
    options=list(available),
    format_func=lambda pid: available[pid].name,
)

podcast = available[podcast_id]
df = load_data(podcast_id)
stats, episodes_stats_df = load_stats(podcast_id)
coverage = load_coverage(podcast_id)

st.title(f"🎙️ {podcast.name} — Word Analysis")

if coverage:
    with_transcript = coverage["states"].get("done", 0)
    st.caption(
        f"{with_transcript}/{coverage['total']} episodes with transcripts "
        f"(states: {coverage['states']})"
    )

# Word selection
word_columns = df.columns.drop("Episode")
default_words = [w for w in podcast.search_words if w in set(word_columns)]
selected_words = st.multiselect("🔍 Choose words", word_columns, default=default_words)

if selected_words:
    df_selected = df[["Episode"] + selected_words]

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
            )
        )
    fig_line.update_layout(xaxis_title="Episode", yaxis_title="Count", width=1000, height=400)
    st.plotly_chart(fig_line, use_container_width=False)

    st.subheader("🏅 Top 10 episodes for the selected words")
    df_selected = df_selected.copy()
    df_selected["total_selected"] = df_selected[selected_words].sum(axis=1)
    top10 = df_selected.sort_values("total_selected", ascending=False).head(10)
    top10["Episode_str"] = "Episode " + top10["Episode"].astype(str)
    top10_sorted = top10.sort_values("total_selected", ascending=True)

    fig_bar = go.Figure()
    for word in selected_words:
        fig_bar.add_trace(
            go.Bar(
                x=top10_sorted[word],
                y=top10_sorted["Episode_str"],
                name=word,
                orientation="h",
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
    st.plotly_chart(fig_bar, use_container_width=False)
else:
    st.info("⬆ Please select one or more words above.")

# General statistics
st.header("📋 General statistics")
col1, col2, col3 = st.columns(3)
col1.metric("🎧 Episodes", stats["total_episodes"])
col2.metric("🗣️ Total words spoken", f"{stats['total_words']:,}")
col3.metric("🔤 Distinct words", f"{stats['total_unique_words']:,}")

st.subheader("📈 Words per episode")
fig_total = go.Figure(
    go.Scatter(x=episodes_stats_df["episode"], y=episodes_stats_df["total_words"], mode="lines")
)
fig_total.update_layout(xaxis_title="Episode", yaxis_title="Words", width=1000, height=300)
st.plotly_chart(fig_total, use_container_width=False)

st.subheader("🔠 Distinct words per episode")
fig_unique = go.Figure(
    go.Scatter(x=episodes_stats_df["episode"], y=episodes_stats_df["unique_words"], mode="lines")
)
fig_unique.update_layout(xaxis_title="Episode", yaxis_title="Count", width=1000, height=300)
st.plotly_chart(fig_unique, use_container_width=False)

st.subheader("🆕 New words per episode")
fig_new = go.Figure(
    go.Scatter(x=episodes_stats_df["episode"], y=episodes_stats_df["new_words"], mode="lines")
)
fig_new.update_layout(
    xaxis_title="Episode",
    yaxis_title="New words",
    yaxis_type="log",
    title="New words per episode (logarithmic)",
    width=1000,
    height=300,
)
st.plotly_chart(fig_new, use_container_width=False)

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
