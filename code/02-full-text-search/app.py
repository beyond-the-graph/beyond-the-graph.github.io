import networkx as nx
import os
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Research Paper Explorer",
    page_icon="📄",
    layout="wide"
)

pio.renderers.default = "browser"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEO4J_URI      = os.environ["NEO4J_URI"]
NEO4J_USERNAME = os.environ["NEO4J_USERNAME"]
NEO4J_PASSWORD = os.environ["NEO4J_PASSWORD"]

# ---------------------------------------------------------------------------
# Neo4j connection
# ---------------------------------------------------------------------------

@st.cache_resource
def get_driver():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
    driver.verify_connectivity()
    return driver

# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def build_query(raw: str, mode: str) -> str:
    if mode == "Phrase":
        return f'"{raw}"'
    if mode == "Fuzzy":
        return " ".join(f"{w}~" for w in raw.split())
    return raw


def run_search(driver, query: str, field: str, min_year: int,
               min_citations: int, top_k: int):
    filters = []
    if field:         filters.append("p.field = $field")
    if min_year:      filters.append("p.year >= $min_year")
    if min_citations: filters.append("p.citation_count >= $min_citations")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    cypher = f"""
        CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
        YIELD node AS p, score
        {where}
        RETURN p.title          AS title,
               p.field          AS field,
               p.venue          AS venue,
               p.year           AS year,
               p.citation_count AS citation_count,
               score
        ORDER BY score DESC
        LIMIT $top_k
    """
    with driver.session() as session:
        results = session.run(
            cypher,
            search_query=query,
            field=field or None,
            min_year=min_year or None,
            min_citations=min_citations or None,
            top_k=top_k
        )
        return [r.data() for r in results]


def run_cited_papers(driver, query: str, top_k: int):
    with driver.session() as session:
        results = session.run("""
            CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
            YIELD node AS p, score
            WITH p, score ORDER BY score DESC LIMIT 1
            MATCH (p)-[:CITES]->(cited:Paper)
            RETURN p.title               AS source_title,
                   score                 AS source_score,
                   cited.title          AS title,
                   cited.field          AS field,
                   cited.year           AS year,
                   cited.citation_count AS citation_count
            ORDER BY cited.citation_count DESC
            LIMIT $top_k
        """, search_query=query, top_k=top_k)
        return [r.data() for r in results]


def run_citing_papers(driver, query: str, top_k: int):
    with driver.session() as session:
        results = session.run("""
            CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
            YIELD node AS p, score
            WITH p, score ORDER BY score DESC LIMIT 1
            MATCH (citing:Paper)-[:CITES]->(p)
            RETURN p.title                AS source_title,
                   score                  AS source_score,
                   citing.title          AS title,
                   citing.field          AS field,
                   citing.year           AS year,
                   citing.citation_count AS citation_count
            ORDER BY citing.year DESC
            LIMIT $top_k
        """, search_query=query, top_k=top_k)
        return [r.data() for r in results]


def run_author_papers(driver, query: str, top_k: int):
    with driver.session() as session:
        results = session.run("""
            CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
            YIELD node AS p, score
            WITH p, score ORDER BY score DESC LIMIT 1
            MATCH (a:Author)-[:AUTHORED]->(p)
            MATCH (a)-[:AUTHORED]->(other:Paper)
            WHERE other <> p
            RETURN p.title               AS source_title,
                   score                 AS source_score,
                   a.name               AS author,
                   other.title          AS title,
                   other.field          AS field,
                   other.year           AS year,
                   other.citation_count AS citation_count
            ORDER BY other.citation_count DESC
            LIMIT $top_k
        """, search_query=query, top_k=top_k)
        return [r.data() for r in results]


def run_cocited_papers(driver, query: str, top_k: int):
    with driver.session() as session:
        results = session.run("""
            CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
            YIELD node AS p, score
            WITH p, score ORDER BY score DESC LIMIT 1
            MATCH (citing:Paper)-[:CITES]->(p)
            MATCH (citing)-[:CITES]->(cocited:Paper)
            WHERE cocited <> p
            WITH p, score, cocited, count(citing) AS shared_citations
            RETURN p.title               AS source_title,
                   score                 AS source_score,
                   cocited.title         AS title,
                   cocited.field         AS field,
                   cocited.year          AS year,
                   shared_citations
            ORDER BY shared_citations DESC
            LIMIT $top_k
        """, search_query=query, top_k=top_k)
        return [r.data() for r in results]


def run_citation_network(driver, query: str):
    with driver.session() as session:
        top = session.run("""
            CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
            YIELD node AS p, score
            RETURN p.paper_id AS paper_id, p.title AS title,
                   p.citation_count AS citation_count, score
            ORDER BY score DESC LIMIT 1
        """, search_query=query).single()

        if not top:
            return None, None

        root_id = top["paper_id"]

        edges_raw = session.run("""
            MATCH (root:Paper {paper_id: $root_id})
            OPTIONAL MATCH (root)-[:CITES]->(cited:Paper)
            OPTIONAL MATCH (citing:Paper)-[:CITES]->(root)
            WITH root,
                 collect(DISTINCT {id: cited.paper_id,  title: cited.title,
                                   cc: cited.citation_count,  dir: 'out'}) AS out_nodes,
                 collect(DISTINCT {id: citing.paper_id, title: citing.title,
                                   cc: citing.citation_count, dir: 'in'})  AS in_nodes
            RETURN root.paper_id       AS root_id,
                   root.title          AS root_title,
                   root.citation_count AS root_cc,
                   out_nodes, in_nodes
        """, root_id=root_id).single()

    return top["title"], edges_raw


def build_citation_figure(root_title, edges_raw):
    import networkx as nx

    G = nx.DiGraph()
    root_id = edges_raw["root_id"]
    root_cc = edges_raw["root_cc"] or 1

    G.add_node(root_id, title=root_title, cc=root_cc, role="root")

    for n in edges_raw["out_nodes"]:
        if n["id"] is None:
            continue
        G.add_node(n["id"], title=n["title"], cc=n["cc"] or 1, role="cited")
        G.add_edge(root_id, n["id"])

    for n in edges_raw["in_nodes"]:
        if n["id"] is None:
            continue
        G.add_node(n["id"], title=n["title"], cc=n["cc"] or 1, role="citing")
        G.add_edge(n["id"], root_id)

    pos = nx.spring_layout(G, seed=42, k=0.3)

    color_map = {"root": "#EF553B", "cited": "#636EFA", "citing": "#00CC96"}

    edge_x, edge_y = [], []
    for u, v in G.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        mode="lines",
        line=dict(width=1, color="#aaa"),
        hoverinfo="none",
        showlegend=False,
    )

    node_x, node_y, node_text, node_color, node_size, node_hover = [], [], [], [], [], []
    for node_id, data in G.nodes(data=True):
        x, y = pos[node_id]
        node_x.append(x)
        node_y.append(y)
        short = data["title"][:40] + "..." if len(data["title"]) > 40 else data["title"]
        node_text.append(short)
        node_color.append(color_map[data["role"]])
        node_size.append(20 + min(data["cc"], 300) / 30)
        node_hover.append(f"{data['title']}<br>Citations: {data['cc']}")

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_text,
        textposition=[
            "middle right" if pos[node_id][0] < 0 else "middle left"
            for node_id in G.nodes()
        ],
        textfont=dict(size=9),
        hovertext=node_hover,
        hoverinfo="text",
        marker=dict(size=node_size, color=node_color,
                    line=dict(width=1, color="white")),
        showlegend=False,
    )

    legend_traces = [
        go.Scatter(x=[None], y=[None], mode="markers",
                   marker=dict(size=10, color="#EF553B"), name="Top result"),
        go.Scatter(x=[None], y=[None], mode="markers",
                   marker=dict(size=10, color="#636EFA"), name="Cites"),
        go.Scatter(x=[None], y=[None], mode="markers",
                   marker=dict(size=10, color="#00CC96"), name="Cited by"),
    ]

    fig = go.Figure(
        data=[edge_trace, node_trace] + legend_traces,
        layout=go.Layout(
            title=f'Citation network: "{root_title[:60]}"',
            showlegend=True,
            hovermode="closest",
            height=480,
            margin=dict(l=80, r=80, t=60, b=60),
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="right", x=1),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        )
    )
    return fig

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

st.title("Research Paper Explorer")
st.caption(
    "Full-text search and graph traversal on a research paper citation graph, "
    "powered by Neo4j."
)

driver = get_driver()

FIELDS = [
    "", "Machine Learning", "Computer Vision", "Natural Language Processing",
    "Reinforcement Learning", "Graph Neural Networks", "Robotics",
    "Bioinformatics", "Quantum Computing", "Cybersecurity", "Data Engineering",
]

tab1, tab2 = st.tabs(["Search", "Explore"])

# ---------------------------------------------------------------------------
# Tab 1: Search
# ---------------------------------------------------------------------------

with tab1:
    st.subheader("Search papers")
    st.write(
        "Search across paper titles and abstracts using keyword, phrase or fuzzy matching. "
        "Use the filters to narrow results by field, year or citation count."
    )

    query_input = st.text_input(
        "Search query",
        value="transformer models for natural language understanding",
        key="search_query"
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        mode = st.radio(
            "Search mode",
            ["Keyword", "Phrase", "Fuzzy"],
            horizontal=True
        )
    with col2:
        top_k = st.slider("Results", min_value=1, max_value=10, value=5,
                          key="search_top_k")

    with st.expander("Filters (optional)"):
        fcol1, fcol2, fcol3 = st.columns(3)
        with fcol1:
            field_filter = st.selectbox("Field", FIELDS)
        with fcol2:
            min_year = st.number_input("Min year", min_value=2015,
                                       max_value=2024, value=2015, step=1)
            min_year = int(min_year) if min_year > 2015 else None
        with fcol3:
            min_citations = st.number_input("Min citations", min_value=0,
                                            max_value=500, value=0, step=10)
            min_citations = int(min_citations) if min_citations > 0 else None

    if st.button("Search", type="primary", key="search_btn"):
        if not query_input.strip():
            st.warning("Please enter a search query.")
        else:
            lucene_query = build_query(query_input.strip(), mode)

            with st.spinner("Searching..."):
                rows = run_search(
                    driver, lucene_query,
                    field_filter or None,
                    min_year, min_citations, top_k
                )

            if not rows:
                st.info("No results found. Try a different query or relax the filters.")
            else:
                st.markdown(
                    f"**{len(rows)} result{'s' if len(rows) != 1 else ''}** "
                    f"for *{mode.lower()}* search: `{lucene_query}`"
                )

                # Result cards
                for r in rows:
                    with st.container(border=True):
                        st.markdown(f"**{r['title']}**")
                        st.caption(
                            f"{r['field']} &nbsp;|&nbsp; {r['venue']} "
                            f"&nbsp;|&nbsp; {r['year']} "
                            f"&nbsp;|&nbsp; Citations: {r['citation_count']} "
                            f"&nbsp;|&nbsp; Score: {r['score']:.3f}"
                        )

                # Score chart
                titles_short = [
                    (r["title"][:50] + "...") if len(r["title"]) > 50
                    else r["title"]
                    for r in rows
                ]
                scores = [r["score"] for r in rows]

                fig = go.Figure(go.Bar(
                    x=scores,
                    y=titles_short,
                    orientation="h",
                    marker_color="#636EFA"
                ))
                fig.update_layout(
                    title="Lucene relevance scores",
                    xaxis_title="Score",
                    yaxis=dict(autorange="reversed"),
                    height=60 + len(rows) * 50,
                    margin=dict(l=10, r=10, t=40, b=40)
                )
                st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------------------
# Tab 2: Explore
# ---------------------------------------------------------------------------

with tab2:
    st.subheader("Explore the citation graph")
    st.write(
        "Find the top-scoring paper for a query, then traverse the citation graph "
        "to discover related work."
    )

    explore_query = st.text_input(
        "Search query",
        value="transformer models for natural language understanding",
        key="explore_query"
    )

    traversal = st.radio(
        "Traversal type",
        [
            "Papers it cites",
            "Papers that cite it",
            "Other work by same authors",
            "Co-cited papers"
        ],
        horizontal=True
    )

    top_k_e = st.slider("Results", min_value=1, max_value=10, value=5,
                         key="explore_top_k")

    if st.button("Explore", type="primary", key="explore_btn"):
        if not explore_query.strip():
            st.warning("Please enter a search query.")
        else:
            q = explore_query.strip()
            with st.spinner("Traversing graph..."):
                if traversal == "Papers it cites":
                    rows = run_cited_papers(driver, q, top_k_e)
                elif traversal == "Papers that cite it":
                    rows = run_citing_papers(driver, q, top_k_e)
                elif traversal == "Other work by same authors":
                    rows = run_author_papers(driver, q, top_k_e)
                else:
                    rows = run_cocited_papers(driver, q, top_k_e)
            st.session_state["explore_rows"]  = rows
            st.session_state["explore_q"]     = q
            st.session_state["explore_label"] = traversal
            st.session_state.pop("network_fig", None)

    if "explore_rows" in st.session_state:
        rows  = st.session_state["explore_rows"]
        q     = st.session_state["explore_q"]
        label = st.session_state["explore_label"]

        if not rows:
            st.info("No results found.")
        else:
            source = rows[0].get("source_title", "")
            score  = rows[0].get("source_score", 0)
            st.markdown(f"**Top result:** {source} *(score: {score:.3f})*")
            st.markdown(f"**{label}:**")

            for r in rows:
                with st.container(border=True):
                    st.markdown(f"**{r['title']}**")
                    if label == "Other work by same authors":
                        st.caption(
                            f"Author: {r.get('author', '')} &nbsp;|&nbsp; "
                            f"{r['field']} &nbsp;|&nbsp; {r['year']} "
                            f"&nbsp;|&nbsp; Citations: {r['citation_count']}"
                        )
                    elif label == "Co-cited papers":
                        st.caption(
                            f"{r['field']} &nbsp;|&nbsp; {r['year']} "
                            f"&nbsp;|&nbsp; Shared citations: {r.get('shared_citations', '')}"
                        )
                    else:
                        st.caption(
                            f"{r['field']} &nbsp;|&nbsp; {r['year']} "
                            f"&nbsp;|&nbsp; Citations: {r['citation_count']}"
                        )

        st.divider()
        if st.button("Show citation network", key="network_btn"):
            with st.spinner("Building citation network..."):
                root_title, edges_raw = run_citation_network(driver, q)
            if edges_raw is None:
                st.info("No citation network found for this query.")
            else:
                st.session_state["network_fig"] = build_citation_figure(
                    root_title, edges_raw
                )

        if "network_fig" in st.session_state:
            st.plotly_chart(
                st.session_state["network_fig"],
                width="stretch"
            )
