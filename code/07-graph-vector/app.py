import os
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from fastembed import TextEmbedding
from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Fraud Detection Explorer",
    page_icon="🔍",
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
EMBED_MODEL    = "BAAI/bge-small-en-v1.5"
RANDOM_SEED    = 42

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
# Embedding model
# ---------------------------------------------------------------------------

@st.cache_resource
def get_embed_model():
    return TextEmbedding(EMBED_MODEL)

def get_embedding(text: str) -> list:
    return list(get_embed_model().embed([text]))[0].tolist()

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def find_rings(driver, hops, min_amount, max_amount, limit=20):
    with driver.session(database=NEO4J_DATABASE) as session:
        if hops == 3:
            result = session.run("""
                MATCH (a1:Account)-[:MADE]->(t1:Transaction)-[:TO]->(a2:Account),
                      (a2)-[:MADE]->(t2:Transaction)-[:TO]->(a3:Account),
                      (a3)-[:MADE]->(t3:Transaction)-[:TO]->(a1)
                WHERE t1.amount >= $min_amount AND t1.amount <= $max_amount
                  AND t2.amount >= $min_amount AND t2.amount <= $max_amount
                  AND t3.amount >= $min_amount AND t3.amount <= $max_amount
                  AND a1.account_id < a2.account_id
                  AND a1.account_id < a3.account_id
                  AND abs(duration.between(datetime(t1.timestamp), datetime(t2.timestamp)).minutes) < 90
                  AND abs(duration.between(datetime(t2.timestamp), datetime(t3.timestamp)).minutes) < 90
                RETURN a1.account_id AS account_1,
                       a2.account_id AS account_2,
                       a3.account_id AS account_3,
                       t1.amount AS amount_1,
                       t2.amount AS amount_2,
                       t3.amount AS amount_3
                LIMIT $limit
            """, min_amount=min_amount, max_amount=max_amount, limit=limit)
        elif hops == 4:
            result = session.run("""
                MATCH (a1:Account)-[:MADE]->(t1:Transaction)-[:TO]->(a2:Account),
                      (a2)-[:MADE]->(t2:Transaction)-[:TO]->(a3:Account),
                      (a3)-[:MADE]->(t3:Transaction)-[:TO]->(a4:Account),
                      (a4)-[:MADE]->(t4:Transaction)-[:TO]->(a1)
                WHERE t1.amount >= $min_amount AND t1.amount <= $max_amount
                  AND t2.amount >= $min_amount AND t2.amount <= $max_amount
                  AND t3.amount >= $min_amount AND t3.amount <= $max_amount
                  AND t4.amount >= $min_amount AND t4.amount <= $max_amount
                  AND a1.account_id < a2.account_id
                  AND a1.account_id < a3.account_id
                  AND a1.account_id < a4.account_id
                  AND abs(duration.between(datetime(t1.timestamp), datetime(t2.timestamp)).minutes) < 90
                  AND abs(duration.between(datetime(t2.timestamp), datetime(t3.timestamp)).minutes) < 90
                  AND abs(duration.between(datetime(t3.timestamp), datetime(t4.timestamp)).minutes) < 90
                RETURN a1.account_id AS account_1,
                       a2.account_id AS account_2,
                       a3.account_id AS account_3,
                       a4.account_id AS account_4,
                       t1.amount AS amount_1,
                       t2.amount AS amount_2,
                       t3.amount AS amount_3,
                       t4.amount AS amount_4
                LIMIT $limit
            """, min_amount=min_amount, max_amount=max_amount, limit=limit)
        else:  # 5-hop
            result = session.run("""
                MATCH (a1:Account)-[:MADE]->(t1:Transaction)-[:TO]->(a2:Account),
                      (a2)-[:MADE]->(t2:Transaction)-[:TO]->(a3:Account),
                      (a3)-[:MADE]->(t3:Transaction)-[:TO]->(a4:Account),
                      (a4)-[:MADE]->(t4:Transaction)-[:TO]->(a5:Account),
                      (a5)-[:MADE]->(t5:Transaction)-[:TO]->(a1)
                WHERE t1.amount >= $min_amount AND t1.amount <= $max_amount
                  AND t2.amount >= $min_amount AND t2.amount <= $max_amount
                  AND t3.amount >= $min_amount AND t3.amount <= $max_amount
                  AND t4.amount >= $min_amount AND t4.amount <= $max_amount
                  AND t5.amount >= $min_amount AND t5.amount <= $max_amount
                  AND a1.account_id < a2.account_id
                  AND a1.account_id < a3.account_id
                  AND a1.account_id < a4.account_id
                  AND a1.account_id < a5.account_id
                  AND abs(duration.between(datetime(t1.timestamp), datetime(t2.timestamp)).minutes) < 90
                  AND abs(duration.between(datetime(t2.timestamp), datetime(t3.timestamp)).minutes) < 90
                  AND abs(duration.between(datetime(t3.timestamp), datetime(t4.timestamp)).minutes) < 90
                  AND abs(duration.between(datetime(t4.timestamp), datetime(t5.timestamp)).minutes) < 90
                RETURN a1.account_id AS account_1,
                       a2.account_id AS account_2,
                       a3.account_id AS account_3,
                       a4.account_id AS account_4,
                       a5.account_id AS account_5,
                       t1.amount AS amount_1,
                       t2.amount AS amount_2,
                       t3.amount AS amount_3,
                       t4.amount AS amount_4,
                       t5.amount AS amount_5
                LIMIT $limit
            """, min_amount=min_amount, max_amount=max_amount, limit=limit)
        return result.data()


def run_vector_search(driver, query, top_k, threshold):
    embedding = get_embedding(query)
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run("""
            CALL db.index.vector.queryNodes(
                'transaction_embeddings', $top_k, $embedding
            ) YIELD node AS t, score
            WHERE score >= $threshold
            MATCH (src:Account)-[:MADE]->(t)-[:TO]->(tgt:Account)
            RETURN t.tx_id           AS tx_id,
                   src.account_id    AS source_account,
                   tgt.account_id    AS target_account,
                   t.amount          AS amount,
                   t.is_fraud_ring   AS is_fraud_ring,
                   t.description     AS description,
                   score
            ORDER BY score DESC
        """, embedding=embedding, top_k=top_k, threshold=threshold)
        return result.data()


def run_graph_vector_search(driver, query, top_k, threshold,
                            min_amount, max_amount, ring_hops):
    embedding = get_embedding(query)
    with driver.session(database=NEO4J_DATABASE) as session:
        if ring_hops == 3:
            ring_match = """
                MATCH (a1:Account)-[:MADE]->(t)-[:TO]->(x1:Account),
                      (x1)-[:MADE]->(rt1:Transaction)-[:TO]->(x2:Account),
                      (x2)-[:MADE]->(rt2:Transaction)-[:TO]->(x3:Account),
                      (x3)-[:MADE]->(rt3:Transaction)-[:TO]->(x1)
            """
            ring_where = (
                "rt1.amount >= $min_amount AND rt1.amount <= $max_amount"
                " AND rt2.amount >= $min_amount AND rt2.amount <= $max_amount"
                " AND rt3.amount >= $min_amount AND rt3.amount <= $max_amount"
                " AND abs(duration.between(datetime(rt1.timestamp), datetime(rt2.timestamp)).minutes) < 90"
                " AND abs(duration.between(datetime(rt2.timestamp), datetime(rt3.timestamp)).minutes) < 90"
            )
            ring_return = "[x1.account_id, x2.account_id, x3.account_id] AS ring_accounts"
        else:  # 4-hop
            ring_match = """
                MATCH (a1:Account)-[:MADE]->(t)-[:TO]->(x1:Account),
                      (x1)-[:MADE]->(rt1:Transaction)-[:TO]->(x2:Account),
                      (x2)-[:MADE]->(rt2:Transaction)-[:TO]->(x3:Account),
                      (x3)-[:MADE]->(rt3:Transaction)-[:TO]->(x4:Account),
                      (x4)-[:MADE]->(rt4:Transaction)-[:TO]->(x1)
            """
            ring_where = (
                "rt1.amount >= $min_amount AND rt1.amount <= $max_amount"
                " AND rt2.amount >= $min_amount AND rt2.amount <= $max_amount"
                " AND rt3.amount >= $min_amount AND rt3.amount <= $max_amount"
                " AND rt4.amount >= $min_amount AND rt4.amount <= $max_amount"
                " AND abs(duration.between(datetime(rt1.timestamp), datetime(rt2.timestamp)).minutes) < 90"
                " AND abs(duration.between(datetime(rt2.timestamp), datetime(rt3.timestamp)).minutes) < 90"
                " AND abs(duration.between(datetime(rt3.timestamp), datetime(rt4.timestamp)).minutes) < 90"
            )
            ring_return = "[x1.account_id, x2.account_id, x3.account_id, x4.account_id] AS ring_accounts"

        result = session.run(f"""
            CALL db.index.vector.queryNodes(
                'transaction_embeddings', $top_k, $embedding
            ) YIELD node AS t, score
            WHERE score >= $threshold
            MATCH (a1:Account)-[:MADE]->(t)
            {ring_match}
            WHERE {ring_where}
            RETURN DISTINCT
                t.tx_id         AS tx_id,
                score           AS similarity,
                a1.account_id   AS entry_account,
                t.amount        AS entry_amount,
                t.is_fraud_ring AS is_fraud_ring,
                {ring_return}
            ORDER BY score DESC
        """,
            embedding=embedding,
            top_k=top_k,
            threshold=threshold,
            min_amount=min_amount,
            max_amount=max_amount
        )
        return result.data()

# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def build_ring_plot(ring_records, hops):
    if not ring_records:
        return None

    G = nx.DiGraph()
    for r in ring_records:
        ring_nodes = [r[f"account_{i}"] for i in range(1, hops + 1)]
        for i, node in enumerate(ring_nodes):
            G.add_node(node)
            G.add_edge(node, ring_nodes[(i + 1) % hops],
                       amount=r[f"amount_{i+1}"])

    pos = nx.spring_layout(G, seed=RANDOM_SEED, k=1.0, iterations=100)

    edge_x, edge_y = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    node_x     = [pos[n][0] for n in G.nodes()]
    node_y     = [pos[n][1] for n in G.nodes()]
    node_text  = list(G.nodes())

    fig = go.Figure(
        data=[
            go.Scatter(
                x=edge_x, y=edge_y,
                mode="lines",
                line=dict(width=1, color="#AAAAAA"),
                hoverinfo="none",
                showlegend=False
            ),
            go.Scatter(
                x=node_x, y=node_y,
                mode="markers+text",
                marker=dict(size=12, color="#E63946",
                            line=dict(width=1.5, color="#333")),
                text=node_text,
                textposition="top center",
                textfont=dict(size=8),
                hovertext=node_text,
                hoverinfo="text",
                showlegend=False
            ),
        ],
        layout=go.Layout(
            title=f"{hops}-hop fraud rings",
            showlegend=False,
            hovermode="closest",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            plot_bgcolor="#FAFAFA",
            paper_bgcolor="#FAFAFA",
            height=600,
            margin=dict(l=80, r=80, t=60, b=60),
        )
    )
    return fig

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Controls")

    query_type = st.selectbox(
        "Query type",
        ["Pure Graph", "Pure Vector", "Graph + Vector"]
    )

    if query_type == "Pure Graph":
        hops = st.selectbox("Ring depth (hops)", [3, 4, 5], index=0)
        min_amount = st.slider(
            "Min amount ($)", 1000, 9000, 3000, step=500
        )
        max_amount = st.slider(
            "Max amount ($)", 1000, 9999, 9999, step=500
        )
        limit = st.slider("Max rings to return", 5, 50, 20)

    if query_type in ("Pure Vector", "Graph + Vector"):
        query_text = st.text_area(
            "Search query",
            value="circular money transfer through intermediary accounts",
            height=80
        )
        top_k = st.slider("Vector candidates (k)", 5, 50, 20)
        threshold = st.slider(
            "Similarity threshold", 0.5, 1.0, 0.7, step=0.05
        )

    if query_type == "Graph + Vector":
        ring_hops = st.selectbox("Ring depth (hops)", [3, 4], index=0)
        min_amount = st.slider(
            "Min amount ($)", 1000, 9000, 2000, step=500
        )
        max_amount = st.slider(
            "Max amount ($)", 1000, 9999, 9999, step=500
        )

    run_btn = st.button("Run query", type="primary")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.title("Fraud Detection Explorer")
st.caption(
    "Graph traversal, vector search and their combination -- "
    "powered by Neo4j and fastembed."
)

driver = get_driver()

tab1, tab2 = st.tabs(["Query Explorer", "Ring Visualization"])

# ---------------------------------------------------------------------------
# Tab 1: Query Explorer
# ---------------------------------------------------------------------------

with tab1:
    if run_btn:
        if query_type == "Pure Graph":
            with st.spinner(f"Running {hops}-hop ring detection..."):
                results = find_rings(driver, hops, min_amount, max_amount, limit)
            st.session_state.update({
                "results": results,
                "query_type": query_type,
                "hops": hops,
            })

        elif query_type == "Pure Vector":
            with st.spinner("Running vector search..."):
                results = run_vector_search(driver, query_text, top_k, threshold)
            st.session_state.update({
                "results": results,
                "query_type": query_type,
            })

        elif query_type == "Graph + Vector":
            with st.spinner("Running graph + vector search..."):
                results = run_graph_vector_search(
                    driver, query_text, top_k, threshold,
                    min_amount, max_amount, ring_hops
                )
            st.session_state.update({
                "results": results,
                "query_type": query_type,
                "ring_hops": ring_hops,
            })

    if "results" in st.session_state:
        results = st.session_state["results"]
        qtype   = st.session_state["query_type"]

        st.markdown(f"### {qtype} Results")
        st.metric("Results returned", len(results))

        if not results:
            st.info("No results found. Try adjusting the parameters.")

        elif qtype == "Pure Graph":
            h = st.session_state["hops"]
            rows = []
            for r in results:
                accounts = " -> ".join(
                    r[f"account_{i}"] for i in range(1, h + 1)
                ) + " -> (back to start)"
                amounts = " -> ".join(
                    f"${r[f'amount_{i}']:,.2f}" for i in range(1, h + 1)
                )
                rows.append({"Ring": accounts, "Amounts": amounts})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        elif qtype == "Pure Vector":
            rows = []
            for r in results:
                rows.append({
                    "TX ID":          r["tx_id"],
                    "Source":         r["source_account"],
                    "Target":         r["target_account"],
                    "Amount":         f"${r['amount']:,.2f}",
                    "Score":          f"{r['score']:.4f}",
                    "Fraud Ring":     "YES" if r["is_fraud_ring"] else "NO",
                    "Description":    r["description"],
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        elif qtype == "Graph + Vector":
            rows = []
            for r in results:
                ring = " -> ".join(r["ring_accounts"]) + " -> (back to start)"
                rows.append({
                    "TX ID":        r["tx_id"],
                    "Entry Account": r["entry_account"],
                    "Amount":       f"${r['entry_amount']:,.2f}",
                    "Score":        f"{r['similarity']:.4f}",
                    "Fraud Ring":   "YES" if r["is_fraud_ring"] else "NO",
                    "Ring":         ring,
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Tab 2: Ring Visualization
# ---------------------------------------------------------------------------

with tab2:
    st.markdown("### Ring Visualization")

    if "results" not in st.session_state:
        st.info("Run a Pure Graph query first to visualize rings.")

    elif st.session_state["query_type"] != "Pure Graph":
        st.info("Ring visualization is available for Pure Graph queries only.")

    else:
        results = st.session_state["results"]
        h       = st.session_state["hops"]

        if not results:
            st.info("No rings detected -- try adjusting the parameters.")
        else:
            fig = build_ring_plot(results, h)
            if fig:
                st.plotly_chart(fig, width="stretch")
                st.caption(
                    f"{len(results)} {h}-hop rings detected. "
                    "Each cluster of nodes forms a circular money flow."
                )
