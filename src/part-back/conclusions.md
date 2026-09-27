# Conclusions

## What We Built

Over seven chapters we built seven example applications, each demonstrating a different Neo4j capability. We found shortest paths on the London Underground, discovered research papers through full-text search, queried air quality data across the Pyrenees corridor, analyzed five years of S&P 500 prices, managed a library inventory with heterogeneous metadata, searched 70,000 fashion images by visual similarity and detected fraud rings by combining vector search with graph traversal.

Every notebook runs on Neo4j Aura's free tier. Every application is a working Streamlit app. The gotchas are real. The "what you'd hit in production" sections are meant.

## What We Learned

### Neo4j is more than a graph database

The most consistent theme across the seven chapters is that Neo4j's graph model is the foundation, not the ceiling. Full-text search, geospatial indexing, temporal queries, document-style properties and vector similarity are all native capabilities -- not integrations with external systems, not add-ons that require separate infrastructure. They work with Cypher and they work together.

Many Neo4j users never explore beyond the graph. The chapters in this book are an attempt to show what's available when you do.

### The combination is the point

Each capability is useful on its own. But the most compelling demonstrations in this book are the ones where two capabilities work together: a spatial proximity query that uses a pre-computed graph for cross-border neighbor lookups, a full-text search that extends into citation traversal, a vector search that filters by graph structure in a single Cypher statement.

Chapter 7 is the clearest example. Pure vector search flags suspicious transactions. Pure graph search finds circular money flows. Neither alone is enough -- the combination, in a single query, is what produces a strong fraud signal. That combination is something no relational database, document database or standalone vector database can replicate naturally.

### Cypher is expressive enough

One thing that might surprise readers coming from SQL is how much Cypher can do in a single statement. The ring detection query in chapter 7 -- vector search, source account lookup, three-hop ring traversal, amount and timestamp filters, deduplication, all in one query -- would be a multi-step process in any other system. The fact that it's a single Cypher statement isn't a novelty. It's what makes the pattern operationally practical.

### The "when to look elsewhere" sections are also true

Neo4j is not the right tool for every problem in this book. High-frequency time series data belongs in a purpose-built time series database. Pure geospatial problems belong in a GIS platform. Billions of documents with no graph component belong in a dedicated search engine. Adding Neo4j to a stack that doesn't need its graph or multi-model capabilities means unnecessary complexity.

The right question is not "can Neo4j do this?" -- it usually can. The right question is "does the graph or multi-model dimension add enough value to justify Neo4j over a simpler alternative?"

## A Practical Decision Guide

**Use Neo4j's native graph model** when the connections between entities are the signal: transport networks, social graphs, supply chains, recommendation engines, fraud detection based on account relationships.

**Add full-text search** when your graph nodes carry text and you want to combine keyword or phrase search with graph traversal in a single query.

**Add geospatial** when your entities have coordinates and meaningful relationships to each other and you want to query both dimensions together.

**Add temporal** when time-varying data are connected to other entities in a graph and you want to combine date-range queries with traversal.

**Add document-style properties** when your nodes carry variable-structure metadata that doesn't need to be independently indexed or traversed as graph structure. Serialize as JSON, parse with APOC. Promote frequently filtered fields to top-level properties.

**Add vector search** when similarity is the query -- finding items that resemble a given item, regardless of shared property values. Combine with graph filters when the interesting constraint is structural, not just categorical.

**Combine graph and vector** when suspicious behavior has both a semantic signature and a structural pattern. Vector search to identify candidates. Graph traversal to validate structure. The combination, in a single Cypher query, is Neo4j's most distinctive capability.

The table below summarizes the specific Neo4j features and functions used in each chapter. It serves as a quick reference for the capabilities covered in this book.

| Chapter | Capability | Key Features |
| --- | --- | --- |
| 1 | Native Graph | Node and relationship storage, bidirectional relationships, `shortestPath()`, variable-depth traversal (`*1..n`), `UNWIND` batch operations, uniqueness constraints |
| 2 | Full-Text Search | Apache Lucene integration, BM25 relevance scoring, keyword/phrase/fuzzy (`~`) search, `FULLTEXT INDEX`, `db.index.fulltext.queryNodes()`, asynchronous index polling |
| 3 | Geospatial | Native `point` type, `POINT INDEX`, `point.distance()`, composite uniqueness constraints, `elementId()` deduplication, latest-record pattern with `collect()[0]` |
| 4 | Temporal | Native `date` and `datetime` types, range index on date properties, `date()` filtering, `min()`/`max()` date anchoring |
| 5 | Document-Style Properties | JSON string property storage, `apoc.convert.fromJsonMap()`, `apoc.convert.toJson()`, `apoc.map.removeKey()`, `ANY()` over deserialized lists, map spread operator |
| 6 | Vector Search | `VECTOR INDEX`, ANN search, euclidean similarity, `db.index.vector.queryNodes()`, post-filter oversampling (`k * n`), graph-filtered k-NN |
| 7 | Graph + Vector | Vector search + graph traversal in a single Cypher query, comma-separated `MATCH` for ring detection, `duration.between()` timestamp constraints, dynamic hop count, `DISTINCT` deduplication |

## What Comes Next

The multi-model database landscape is moving quickly. Neo4j continues to expand product capabilities. APOC continues to grow. The Graph Data Science library adds community detection, centrality algorithms and machine learning pipelines that build directly on the graph model.

The specific procedures and syntax in this book may evolve. The underlying capabilities -- and the architectural patterns that make them useful -- will not.

## A Final Note

The goal of this book was not to argue that Neo4j should replace every database in your stack. It was to show that if you're using Neo4j or considering it for a graph use case, you already have access to full-text search, geospatial queries, temporal reasoning, document properties and vector similarity. Combining these capabilities with graph traversal is something no other database does as naturally.

This book is supported with Jupyter notebooks and Streamlit applications. The best way to decide whether any of these capabilities fits your use case is to run the code.
