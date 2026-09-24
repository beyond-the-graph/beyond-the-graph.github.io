import json
import os
import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit as st

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Library Inventory Explorer",
    page_icon="📚",
    layout="wide"
)

pio.renderers.default = "browser"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]
NEO4J_DATABASE = os.environ["NEO4J_DATABASE"]

# ---------------------------------------------------------------------------
# Neo4j connection
# ---------------------------------------------------------------------------

@st.cache_resource
def get_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    driver.verify_connectivity()
    return driver

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@st.cache_data
def load_all_items(_driver):
    with _driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (pub:Publisher)-[:PUBLISHED]->(i:Item)
            WITH i, pub, apoc.convert.fromJsonMap(i.metadata) AS meta
            OPTIONAL MATCH (a:Author)-[:AUTHORED]->(i)
            RETURN i.id        AS id,
                   i.title     AS title,
                   i.item_type AS item_type,
                   pub.name    AS publisher,
                   a.name      AS author,
                   meta        AS metadata
            ORDER BY i.item_type, i.id
        """)
        return [r.data() for r in result]


@st.cache_data
def load_chart_data(_driver):
    with _driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (i:Item)
            RETURN i.item_type AS item_type, count(*) AS count
            ORDER BY count DESC
        """)
        return pd.DataFrame([r.data() for r in result])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def render_metadata(item):
    meta     = item["metadata"]
    itype    = item["item_type"]
    author   = item.get("author")

    if itype == "book":
        st.markdown(
            f"**ISBN:** {meta.get('isbn', 'N/A')}  \n"
            f"**Pages:** {meta.get('pages', 'N/A')}  \n"
            f"**Language:** {meta.get('language', 'N/A')}  \n"
            f"**Author:** {author or 'N/A'}"
        )

    elif itype == "journal":
        st.markdown(
            f"**Editor:** {meta.get('editor', 'N/A')}  \n"
            f"**Volume:** {meta.get('volume', 'N/A')} ({meta.get('year', 'N/A')})  \n"
            f"**Articles:** {len(meta.get('articles', []))}"
        )
        articles = meta.get("articles", [])
        if articles:
            with st.expander("Article titles"):
                for article in articles:
                    st.write(f"- {article}")

    elif itype == "multimedia":
        st.markdown(
            f"**Format:** {meta.get('format', 'N/A')}  \n"
            f"**Duration:** {meta.get('duration_min', 'N/A')} min  \n"
            f"**Language:** {meta.get('language', 'N/A')}"
        )
        contributors = meta.get("contributors", {})
        if contributors:
            with st.expander("Contributors"):
                for role, name in contributors.items():
                    st.write(f"- **{role.capitalize()}:** {name}")


ITEM_TYPE_COLORS = {
    "book":       "#636EFA",
    "journal":    "#EF553B",
    "multimedia": "#00CC96",
}

ITEM_TYPE_ICONS = {
    "book":       "📖",
    "journal":    "📰",
    "multimedia": "🎬",
}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.title("Library Inventory Explorer")
st.caption(
    "Document-style metadata stored as JSON strings in Neo4j, "
    "queried with APOC and displayed here."
)

driver   = get_driver()
all_items = load_all_items(driver)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Filter")

    item_type_filter = st.selectbox(
        "Item type",
        ["All", "Book", "Journal", "Multimedia"]
    )

    keyword = st.text_input("Keyword search", placeholder="e.g. AI, English, DVD")

    st.divider()
    st.markdown("**Collection summary**")
    chart_df = load_chart_data(driver)
    fig = px.bar(
        chart_df,
        x="item_type",
        y="count",
        color="item_type",
        color_discrete_map=ITEM_TYPE_COLORS,
        labels={"item_type": "", "count": "Items"},
    )
    fig.update_layout(
        showlegend=False,
        height=200,
        margin=dict(l=0, r=0, t=10, b=0)
    )
    st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------------------
# Filter items
# ---------------------------------------------------------------------------

filtered = all_items

if item_type_filter != "All":
    filtered = [i for i in filtered if i["item_type"] == item_type_filter.lower()]

if keyword.strip():
    kw = keyword.strip().lower()
    def matches(item):
        # Search title
        if kw in item["title"].lower():
            return True
        meta = item["metadata"]
        # Search within articles list for journals
        if item["item_type"] == "journal":
            articles = meta.get("articles", [])
            if any(kw in a.lower() for a in articles):
                return True
        # Search language, format, editor, isbn
        for field in ["language", "format", "editor", "isbn"]:
            val = meta.get(field, "")
            if val and kw in str(val).lower():
                return True
        # Search author name
        if item.get("author") and kw in item["author"].lower():
            return True
        return False
    filtered = [i for i in filtered if matches(i)]

# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

st.markdown(f"**{len(filtered)} item{'s' if len(filtered) != 1 else ''} found**")

if not filtered:
    st.info("No items match your filter. Try a different keyword or item type.")
else:
    for item in filtered:
        itype = item["item_type"]
        icon  = ITEM_TYPE_ICONS.get(itype, "")
        color = ITEM_TYPE_COLORS.get(itype, "#888888")

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"### {icon} {item['title']}")
                st.caption(
                    f"**{itype.capitalize()}** &nbsp;|&nbsp; "
                    f"Published by {item['publisher']}"
                )
            with col2:
                st.markdown(
                    f'<div style="text-align:right;padding-top:8px;">'
                    f'<span style="background:{color};color:white;padding:4px 10px;'
                    f'border-radius:12px;font-size:12px;">{itype}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            render_metadata(item)
