import numpy as np
import os
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from collections import Counter
from neo4j import GraphDatabase
from plotly.subplots import make_subplots
from sklearn.datasets import fetch_openml
import pandas as pd

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Fashion-MNIST Vector Search",
    page_icon="👗",
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

CLASSES = [
    "t_shirt_top", "trouser", "pullover", "dress", "coat",
    "sandal",      "shirt",   "sneaker",  "bag",   "ankle_boot"
]

# ---------------------------------------------------------------------------
# Neo4j connection
# ---------------------------------------------------------------------------

@st.cache_resource
def get_driver():
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        notifications_disabled_categories=["DEPRECATION"]
    )
    driver.verify_connectivity()
    return driver

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data
def load_images():
    fashion = fetch_openml(name="Fashion-MNIST", version=1, as_frame=False)
    X, y = fashion.data, fashion.target.astype(np.uint8)
    train_raw    = X[:60000].reshape(-1, 28, 28)
    test_raw     = X[60000:].reshape(-1, 28, 28)
    train_labels = y[:60000]
    test_labels  = y[60000:]
    return train_raw, test_raw, train_labels, test_labels

@st.cache_data
def get_class_ids(_train_labels, _test_labels):
    """Build a lookup of class -> list of (id, split) tuples."""
    lookup = {cls: [] for cls in CLASSES}
    for i, label_idx in enumerate(_train_labels):
        lookup[CLASSES[label_idx]].append((i, "train"))
    for i, label_idx in enumerate(_test_labels):
        lookup[CLASSES[label_idx]].append((i, "test"))
    return lookup

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_item_vector(driver, item_id, split):
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            MATCH (i:Item {id: $id, split: $split})
            RETURN i.vector AS vector, i.label AS label
        """, id=item_id, split=split)
        return result.single()


def run_knn(driver, vector, k, split_filter, category_filter):
    fetch_k = k * 10
    with driver.session(database=NEO4J_DATABASE) as session:
        if category_filter and category_filter != "All":
            result = session.run("""
                CALL db.index.vector.queryNodes('item_vector', $k, $vector)
                YIELD node AS i, score
                MATCH (i)-[:BELONGS_TO]->(c:Category {name: $category})
                WHERE $split = 'Both' OR i.split = $split
                RETURN i.id    AS id,
                       i.label AS label,
                       i.split AS split,
                       score
                ORDER BY score DESC
            """, k=fetch_k, vector=vector,
                 category=category_filter,
                 split=split_filter)
        else:
            result = session.run("""
                CALL db.index.vector.queryNodes('item_vector', $k, $vector)
                YIELD node AS i, score
                WHERE $split = 'Both' OR i.split = $split
                RETURN i.id    AS id,
                       i.label AS label,
                       i.split AS split,
                       score
                ORDER BY score DESC
            """, k=fetch_k, vector=vector, split=split_filter)
        return [r.data() for r in result]

# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def render_image_grid(query_id, query_split, query_label, results,
                      train_raw, test_raw):
    def get_img(item_id, split):
        return train_raw[item_id] if split == "train" else test_raw[item_id]

    all_items = [(query_id, query_split, "Query", None, query_label)] + [
        (r["id"], r["split"], f"#{i+1}", r["score"], r["label"])
        for i, r in enumerate(results)
    ]

    n = len(all_items)
    titles = [
        f"{tag}<br>{label}" + (f"<br>{score:.3f}" if score is not None else "")
        for _, _, tag, score, label in all_items
    ]

    fig = make_subplots(rows=1, cols=n, subplot_titles=titles)
    for col, (iid, split, _, _, _) in enumerate(all_items):
        fig.add_trace(
            go.Heatmap(z=get_img(iid, split)[::-1],
                       colorscale="gray_r", showscale=False),
            row=1, col=col + 1
        )
    fig.update_xaxes(showticklabels=False)
    fig.update_yaxes(showticklabels=False)
    fig.update_layout(height=220, margin=dict(t=60, b=10))
    return fig

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.title("Fashion-MNIST Vector Search")
st.caption(
    "k-NN similarity search on 70,000 Fashion-MNIST images using "
    "Neo4j vector indexes."
)

driver = get_driver()

with st.spinner("Loading Fashion-MNIST images..."):
    train_raw, test_raw, train_labels, test_labels = load_images()
    class_ids = get_class_ids(train_labels, test_labels)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Controls")

    st.markdown("**Query image**")
    query_category = st.selectbox("Category", CLASSES, index=3)  # dress default
    query_split    = st.selectbox("Split", ["train", "test"])

    st.divider()
    st.markdown("**Search options**")
    split_filter    = st.selectbox("Results split", ["Both", "train", "test"])
    category_filter = st.selectbox("Results category", ["All"] + CLASSES)
    k               = st.slider("Nearest neighbors (k)", 1, 10, 5)

    find_btn = st.button("Pick random item and search", type="primary")

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

if find_btn:
    # Pick a random item from the selected category and split
    candidates = [
        (iid, split) for iid, split in class_ids[query_category]
        if split == query_split
    ]
    if not candidates:
        st.error(f"No items found for {query_category} in {query_split} split.")
    else:
        query_id, chosen_split = candidates[np.random.randint(len(candidates))]

        with st.spinner("Fetching query vector..."):
            item = get_item_vector(driver, query_id, chosen_split)

        if item is None:
            st.error(f"Item {query_id} ({chosen_split}) not found in the database.")
        else:
            vector = item["vector"]
            label  = item["label"]

            with st.spinner("Running k-NN search..."):
                results = run_knn(driver, vector, k, split_filter, category_filter)

            # Exclude the query item itself
            results = [r for r in results
                       if not (r["id"] == query_id and r["split"] == chosen_split)]
            results = results[:k]

            st.session_state["query_id"]    = query_id
            st.session_state["query_split"] = chosen_split
            st.session_state["label"]       = label
            st.session_state["results"]     = results

if "results" in st.session_state:
    query_id    = st.session_state["query_id"]
    query_split = st.session_state["query_split"]
    label       = st.session_state["label"]
    results     = st.session_state["results"]

    st.markdown(f"### Query: item {query_id} ({query_split}) -- **{label}**")

    col1, col2, col3 = st.columns(3)
    col1.metric("Query item", f"{query_id} ({query_split})")
    col2.metric("Category", label)
    col3.metric("Results returned", len(results))

    if not results:
        st.info("No results found. Try adjusting the filters.")
    else:
        # Image grid
        fig_grid = render_image_grid(
            query_id, query_split, label, results, train_raw, test_raw
        )
        st.plotly_chart(fig_grid, width="stretch")

        # Category breakdown chart
        cat_counts = Counter(r["label"] for r in results)
        fig_bar = go.Figure(go.Bar(
            x=list(cat_counts.keys()),
            y=list(cat_counts.values()),
            marker_color="#636EFA"
        ))
        fig_bar.update_layout(
            title="Category breakdown of k-NN results",
            xaxis_title="Category",
            yaxis_title="Count",
            height=300,
            margin=dict(t=40, b=40)
        )
        st.plotly_chart(fig_bar, width="stretch")

        # Results table
        with st.expander("Full results table"):
            st.dataframe(
                pd.DataFrame(results),
                hide_index=True,
                width="stretch"
            )
