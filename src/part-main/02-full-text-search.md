# Chapter 2: Full-Text Search

## What Is It?

Neo4j ships with Apache Lucene built in, giving you full-text search -- phrase matching, fuzzy matching, relevance scoring -- without a separate service. When your data are already in a graph, that search becomes an entry point into something a standalone search engine can't do: you find your initial results with Lucene, then traverse the graph to discover what surrounds them.

The full-text index in Neo4j is created with a single Cypher procedure call and covers one or more properties across one or more node labels. Queries against it use Lucene's query syntax -- single terms, quoted phrases, boolean operators, fuzzy matching with `~` -- and return nodes ranked by BM25 relevance score. The higher the score, the closer the match.

What makes this distinctive is the combination with graph traversal. A standalone search engine returns documents. Neo4j returns nodes -- and nodes are connected to other nodes by relationships. A full-text search that finds a paper can immediately extend into a Cypher query that follows citation links, finds co-authors, or surfaces papers that are frequently cited alongside the result. That combination, in a single Cypher statement, is what sets Neo4j's full-text search apart from running a search engine alongside a database.

## When Would You Reach for It?

Full-text search in Neo4j earns its place when the text you're searching is embedded in a graph and the graph structure is part of what you want to explore. Research literature is the canonical example: papers are text-heavy entities, but the citations between them form a network that carries as much signal as the content itself.

Reach for Neo4j's full-text search when:

- Your text entities have relationships to other entities that matter for the query
- You want to combine keyword or phrase search with graph traversal in a single operation
- You need relevance-ranked results with BM25 scoring
- You're already using Neo4j and don't want to maintain a separate search index

If you're building a standalone search engine over billions of documents with no graph component, a dedicated search platform is the better choice. But for connected text -- papers that cite each other, articles linked by authorship, tickets connected by dependency -- Neo4j's full-text search is a natural fit.

## The Use Case

For this chapter we'll build a research paper discovery tool. Users can search for papers by keyword, phrase or fuzzy match, filter results by field, year or citation count and then traverse the citation graph from any result to discover related work. The traversal options include following outgoing citations, incoming citations, other papers by the same authors and papers that are co-cited alongside the top result.

## The Data

We use the same synthetic 200-paper research dataset from the [Weaviate chapter](https://seven-vector-databases.github.io/part-main/day4-weaviate.html) of *Seven Vector Databases in Seven Days* -- identical fields, venues, author names, abstract templates and random seed -- so the papers are directly comparable across both books. Two things are added that the Weaviate version didn't have: `Author` nodes connected to papers via `AUTHORED` relationships and `CITES` relationships between papers, with a citation bias toward papers in the same or adjacent research fields.

The graph has two node types:

- `Paper` -- with `paper_id`, `title`, `abstract`, `field`, `venue`, `year` and `citation_count` properties
- `Author` -- with a `name` property

And two relationship types:

- `(Author)-[:AUTHORED]->(Paper)`
- `(Paper)-[:CITES]->(Paper)` -- with citations biased toward same-field or adjacent-field papers and only toward papers with lower IDs (older papers)

The `abstract` and `title` properties are the target for full-text search. The structured fields -- `field`, `year`, `citation_count` -- serve as filters.

## Building the Application

### Prerequisites

The same Aura environment variables as chapter 1. All data are generated in the notebook.

### Loading the Graph

We clear the database before each run. To avoid transaction timeouts on Aura, we drop constraints and indexes first, then delete nodes in batches of 1,000:

```python
# Drop all constraints
constraints = session.run("SHOW CONSTRAINTS YIELD name RETURN name").data()
for con in constraints:
    session.run(f"DROP CONSTRAINT {con['name']} IF EXISTS")

# Drop all non-system indexes
indexes = session.run(
    "SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name"
).data()
for idx in indexes:
    session.run(f"DROP INDEX {idx['name']} IF EXISTS")

# Delete in batches
while True:
    result = session.run("""
        MATCH (n) WITH n LIMIT 1000
        DETACH DELETE n
        RETURN count(*) AS deleted
    """)
    if result.single()["deleted"] == 0:
        break
```

A simple `MATCH (n) DETACH DELETE n` works for small graphs but can time out on Aura when there are many nodes. The batched approach is safer and worth using as a habit.

We then load in three passes -- papers, authors and authorship, citations:

```python
# Paper nodes
session.run("""
    UNWIND $records AS r
    CREATE (p:Paper {
        paper_id:       r.paper_id,
        title:          r.title,
        year:           r.year,
        field:          r.field,
        venue:          r.venue,
        citation_count: r.citation_count,
        abstract:       r.abstract
    })
""", records=paper_records)

# Author nodes and AUTHORED relationships
# MERGE on Author so each author name becomes one node across all papers
session.run("""
    UNWIND $records AS r
    MERGE (a:Author {name: r.author_name})
    WITH a, r
    MATCH (p:Paper {paper_id: r.paper_id})
    CREATE (a)-[:AUTHORED]->(p)
""", records=author_records)

# CITES relationships
session.run("""
    UNWIND $citations AS c
    MATCH (from:Paper {paper_id: c.from_id})
    MATCH (to:Paper   {paper_id: c.to_id})
    CREATE (from)-[:CITES]->(to)
""", citations=citations)
```

### Creating the Full-Text Index

A single procedure call creates a Lucene index over both `title` and `abstract`:

```python
session.run("""
    CREATE FULLTEXT INDEX paper_fulltext IF NOT EXISTS
    FOR (p:Paper)
    ON EACH [p.title, p.abstract]
""")
```

The index is created asynchronously. We poll until it's `ONLINE` before querying:

```python
for _ in range(30):
    result = session.run("""
        SHOW INDEXES YIELD name, state
        WHERE name = 'paper_fulltext'
        RETURN state
    """)
    state = result.single()["state"]
    if state == "ONLINE":
        break
    time.sleep(1)
```

### Basic Full-Text Search

Querying the index uses `db.index.fulltext.queryNodes`. It returns nodes ranked by BM25 score:

```python
def search_papers(query: str, top_k: int = 5):
    with driver.session() as session:
        results = session.run("""
            CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
            YIELD node AS p, score
            RETURN p.title          AS title,
                   p.field          AS field,
                   p.year           AS year,
                   p.citation_count AS citation_count,
                   score
            ORDER BY score DESC
            LIMIT $top_k
        """, search_query=query, top_k=top_k)
```

Note the parameter name: `search_query`, not `query`. The Neo4j Python driver reserves `query` as the keyword argument for the Cypher string itself. Using `query=...` in the keyword arguments conflicts with the driver internals and causes an error. Use `search_query`, `q` or any other name.

### Keyword, Phrase and Fuzzy Search

Lucene's full query syntax is available. The three most useful modes for discovery:

**Keyword** -- individual terms scored independently. A query for `graph neural networks` returns papers containing any of those words, with higher scores for more matches:

```python
search_papers("graph neural networks")
```

**Phrase** -- wrapping in double quotes requires the words to appear together in that order:

```python
search_papers('"graph neural networks"')
```

**Fuzzy** -- appending `~` to a term enables edit-distance matching. Useful for misspelled terms or variant spellings:

```python
# 'tranformer' matches 'transformer'
search_papers("tranformer~")
```

The notebook includes a `compare_search_modes()` function that runs the same query in both keyword and phrase mode and plots the BM25 scores side by side. This makes the scoring difference concrete: phrase mode scores are generally lower and more selective, while keyword mode casts a wider net with more variance in relevance.

### Filtered Search

Full-text search narrows by relevance; structured filters narrow by property. The two compose naturally in Cypher with a `WHERE` clause after the `YIELD`:

```python
cypher = f"""
    CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
    YIELD node AS p, score
    {where_clause}
    RETURN p.title, p.field, p.year, p.citation_count, score
    ORDER BY score DESC
    LIMIT $top_k
"""
```

Where `where_clause` is built dynamically from whichever filters are active -- field, minimum year, minimum citation count. The Lucene index does the text matching first; the `WHERE` clause filters the resulting nodes. This is the same pattern as filtered vector search in chapter 6 and chapter 7.

### Search Then Traverse: The Graph Layer

This is where Neo4j's full-text search separates itself from a standalone search engine. Once we have a top-scoring paper, we can immediately traverse the graph from it.

**Papers it cites** -- follow outgoing `CITES` edges from the top result to see what it builds on:

```python
session.run("""
    CALL db.index.fulltext.queryNodes('paper_fulltext', $search_query)
    YIELD node AS p, score
    WITH p, score ORDER BY score DESC LIMIT 1
    MATCH (p)-[:CITES]->(cited:Paper)
    RETURN p.title AS source_title, cited.title AS cited_title,
           cited.field AS cited_field, cited.citation_count AS cited_citations
    ORDER BY cited.citation_count DESC
    LIMIT $top_k
""", search_query=query, top_k=top_k)
```

**Papers that cite it** -- traverse incoming `CITES` edges to find papers that considered this work important enough to build on:

```python
MATCH (citing:Paper)-[:CITES]->(p)
```

**Other work by the same authors** -- traverse from the paper to its authors, then to their other papers. This path doesn't exist in a standalone search index at all:

```python
MATCH (a:Author)-[:AUTHORED]->(p)
MATCH (a)-[:AUTHORED]->(other:Paper)
WHERE other <> p
```

**Co-cited papers** -- find papers that are frequently cited alongside the top result. Two papers are co-cited when a third paper cites both. Papers that are often co-cited tend to address the same problem or be considered foundational in the same area -- a relationship that appears nowhere in the papers themselves, only in how others use them:

```python
MATCH (citing:Paper)-[:CITES]->(p)
MATCH (citing)-[:CITES]->(cocited:Paper)
WHERE cocited <> p
WITH p, cocited, count(citing) AS shared_citations
RETURN cocited.title, shared_citations
ORDER BY shared_citations DESC
```

### Citation Network Visualization

The citation network around a top result is visualized as an interactive Plotly graph. The top-scoring paper is the red central node. Blue nodes are papers it cites (outgoing edges). Green nodes are papers that cite it (incoming edges). Node size reflects citation count.

The network is built with NetworkX and rendered with Plotly:

```python
G = nx.DiGraph()
G.add_node(root_id, title=root_title, cc=root_cc, role="root")

for n in edges_raw["out_nodes"]:
    G.add_node(n["id"], title=n["title"], cc=n["cc"], role="cited")
    G.add_edge(root_id, n["id"])

for n in edges_raw["in_nodes"]:
    G.add_node(n["id"], title=n["title"], cc=n["cc"], role="citing")
    G.add_edge(n["id"], root_id)

pos = nx.spring_layout(G, seed=42, k=0.3)
color_map = {"root": "#EF553B", "cited": "#636EFA", "citing": "#00CC96"}
```

### The Streamlit App

The application has two tabs. The Search tab accepts a query string and exposes the three search modes (Keyword, Phrase, Fuzzy) as a radio button, optional filters (field, year, citation count) in a collapsible expander and a results count slider. Results are displayed as cards with title, field, venue, year, citation count and Lucene score, with a horizontal bar chart showing the score distribution across all results.

The Explore tab runs a search and then applies one of four traversal types: Papers it cites, Papers that cite it, Other work by same authors, Co-cited papers. A "Show citation network" button below the traversal results builds and displays the red-blue-green citation network graph.

Both tabs use `st.session_state` to persist results across re-runs. The Explore tab also clears the cached network figure when a new search is run, so the graph doesn't show stale results from a previous query.

## What You'd Hit in Production

**Index freshness.** Lucene indexes in Neo4j are updated synchronously on write -- new nodes are indexed as soon as they're created. For bulk ingestion, creating the index after loading is faster than having the index update on every write.

**Query syntax errors.** A malformed Lucene query -- an unmatched quote, a reserved character like `+` or `!` without escaping -- throws an exception. The app should sanitize user input or wrap the query call in a try-except before passing it to `db.index.fulltext.queryNodes`.

**Fuzzy matching cost.** Fuzzy queries with `~` scan a wider set of index terms and are slower than exact term queries. For interactive search over 200 papers this is imperceptible, but for millions of documents you'd want to set an explicit edit distance (`~1` or `~2`) rather than relying on the default.

**The `query` parameter.** This is worth repeating because it's easy to hit and the error message isn't immediately obvious: never use `query` as a Cypher parameter name when using the Neo4j Python driver. It conflicts with the driver's own keyword argument for the Cypher string. Use `search_query` or any other name.

**Batched deletion.** The simple `MATCH (n) DETACH DELETE n` pattern can time out on Aura for graphs with tens of thousands of nodes. Batching deletes in groups of 1,000 is more reliable and should be the default approach for database clearing in notebooks that might be re-run.

## Going Further

Full-text search surfaces papers by content. Graph traversal extends those results through citation links and authorship. But both of these approaches are vocabulary-dependent -- a search for "neural network" won't naturally surface a paper that uses "deep learning" throughout without ever using the phrase "neural network."

Chapter 6 addresses this with vector search: by embedding the abstract as a high-dimensional vector, we can find papers that are semantically similar even when they use different vocabulary. And chapter 7 takes the combination further -- using vector search to find suspicious transactions and graph traversal to confirm whether they form a ring. The pattern of combining a search capability with graph traversal is one that recurs throughout this book, and it starts here.
