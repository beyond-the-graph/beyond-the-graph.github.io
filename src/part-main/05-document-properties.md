# Chapter 5: Document-style properties

## What is it?

Neo4j node properties support primitive types -- strings, integers, floats, booleans, dates -- and arrays of primitives. Nested maps are not supported as native property values. To store heterogeneous, document-style metadata alongside graph structure, a common approach is to serialize it as a JSON string and parse it back at query time using APOC's `apoc.convert.fromJsonMap()` function.

Nested structure doesn't fit the property model and deeply nested documents are usually better handled at the edge between the database and the application than inside the graph query itself. The sweet spot is: store rich, variable-structure metadata as a JSON string on the node; use APOC to deserialize it inside Cypher when you need to query or mutate it; promote frequently filtered fields to top-level properties with their own indexes.

APOC (Awesome Procedures On Cypher) is Neo4j's standard extension library and a subset of APOC Core is pre-installed on Aura. It provides `apoc.convert.fromJsonMap()` to parse a JSON string into a Cypher map, `apoc.convert.toJson()` to serialize a map back to a string and `apoc.map.removeKey()` to delete a field from a map without touching the rest.

## When would you reach for it?

Document-style properties earn their place when your nodes need to carry structured metadata that varies across instances and that metadata doesn't need to be independently indexed or traversed as graph structure. The key question is whether you need to query inside the property or just store and retrieve it as a unit.

Reach for this pattern when:

- Your nodes carry variable-structure metadata that differs across instances of the same label
- The metadata belongs logically to the node rather than deserving its own node type
- You need to store and retrieve the metadata as a unit, or query inside it occasionally with APOC
- You want to avoid the overhead of a normalized schema for genuinely heterogeneous data

Libraries, product catalogs and content management systems are all cases where some nodes carry rich, variable metadata alongside graph-structured relationships to other entities.

## The use case

For this chapter we'll build a small library inventory system with three item types -- books, journals and multimedia -- each carrying a different metadata structure in the same `metadata` property on `Item` nodes. We demonstrate how to query across the three types using APOC, how to traverse the graph to join items with their authors and publishers and how to add and remove fields from stored metadata without re-specifying the whole object.

## The data

The inventory is small by design -- 15 items, 3 authors and 3 publishers. The point is to show the metadata pattern clearly, not to load data at scale.

The three metadata structures are:

- **Books** -- a flat map: `isbn`, `pages`, `language`, `author_id`
- **Journals** -- a map with a list: `volume`, `year`, `editor`, `articles[]`
- **Multimedia** -- a nested map: `format`, `duration_min`, `language`, `contributors{}`

All three are stored in the same `metadata` property on `Item` nodes.

The graph model is:

```
(:Publisher {id, name, location})-[:PUBLISHED]->(:Item {id, title, item_type, metadata})
(:Author    {id, name, nationality})-[:AUTHORED]->(:Item)
```

## Building the application

### Prerequisites

You'll need a Neo4j Aura free-tier instance with the connection details stored as environment variables.

### Storing metadata

The `metadata` property is stored as a JSON string. In Python, we serialize with `json.dumps()` before passing to Neo4j:

```python
ITEMS = [
    {"id": 1, "title": "The Quantum Garden", "item_type": "book",
     "publisher_id": 1,
     "metadata": {"isbn": "978-0-123456-47-2", "pages": 320,
                  "language": "English", "author_id": 1}},
    {"id": 6, "title": "Journal of Advanced Robotics - Vol 12",
     "item_type": "journal", "publisher_id": 2,
     "metadata": {"volume": 12, "year": 2022, "editor": "Dr. Helen Moritz",
                  "articles": ["Autonomous Drones in Urban Spaces",
                               "Swarm Intelligence in Rescue Missions",
                               "Adaptive Control in Humanoid Robots",
                               "Robot Learning from Demonstration"]}},
    {"id": 11, "title": "Ocean Deep - A Documentary",
     "item_type": "multimedia", "publisher_id": 3,
     "metadata": {"format": "DVD", "duration_min": 92, "language": "English",
                  "contributors": {"narrator": "David Stone",
                                   "director": "Lisa Wong",
                                   "editor": "James Patel"}}},
]

items_for_neo4j = [
    {**item, "metadata": json.dumps(item["metadata"])}
    for item in ITEMS
]

session.run("""
    UNWIND $rows AS row
    MERGE (i:Item {id: row.id})
    SET i.title     = row.title,
        i.item_type = row.item_type,
        i.metadata  = row.metadata
    WITH i, row
    MATCH (p:Publisher {id: row.publisher_id})
    MERGE (p)-[:PUBLISHED]->(i)
""", rows=items_for_neo4j)
```

We pass the metadata as a JSON string so it's stored as a single string property. All three item types use the same `metadata` property name -- the structure varies but the storage pattern is uniform. We also create uniqueness constraints on `id` for `Author`, `Publisher` and `Item`, which keeps the `MERGE` statements safe to re-run. The same statement links each item to its publisher.

The `AUTHORED` relationships come from the metadata itself. Books carry an `author_id` key, so we parse it with APOC during the load and use it to find the author:

```python
session.run("""
    MATCH (i:Item)
    WHERE i.item_type = 'book'
    WITH i, apoc.convert.fromJsonMap(i.metadata) AS meta
    WHERE meta.author_id IS NOT NULL
    MATCH (a:Author {id: meta.author_id})
    MERGE (a)-[:AUTHORED]->(i)
""")
```

After this step the relationship, not the JSON key, is what queries should follow.

### APOC: Parsing metadata in Cypher

`apoc.convert.fromJsonMap()` parses the JSON string back into a Cypher map at query time. Once parsed, you access fields with dot notation and use standard Cypher operators on them:

```python
result = session.run("""
    MATCH (i:Item)
    WHERE i.item_type = 'book'
    WITH i, apoc.convert.fromJsonMap(i.metadata) AS meta
    RETURN i.id          AS id,
           i.title       AS title,
           meta.isbn     AS isbn,
           meta.pages    AS pages,
           meta.language AS language
    ORDER BY i.id
""")
```

The `WITH i, apoc.convert.fromJsonMap(i.metadata) AS meta` line is the key pattern. It deserializes the JSON string into a map named `meta`, which then behaves like any Cypher map for the rest of the query.

### Query 1: Books -- flat metadata

Books have flat metadata -- every field is a scalar. `meta.isbn`, `meta.pages` and `meta.language` work as direct property accessors once the JSON is parsed.

### Query 2: Journals -- metadata with a list

Journals have an `articles` list inside the metadata. Cypher's `size()` function counts the elements:

```python
result = session.run("""
    MATCH (i:Item)
    WHERE i.item_type = 'journal'
    WITH i, apoc.convert.fromJsonMap(i.metadata) AS meta
    RETURN i.id                AS id,
           i.title             AS title,
           meta.editor         AS editor,
           meta.volume         AS volume,
           meta.year           AS year,
           size(meta.articles) AS article_count
    ORDER BY article_count DESC
""")
```

### Query 3: Multimedia -- nested map

Multimedia items have a `contributors` map nested inside the metadata. Returning `meta.contributors` gives you the whole nested map as a Cypher map value, which the Python driver returns as a Python dict:

```python
result = session.run("""
    MATCH (i:Item)
    WHERE i.item_type = 'multimedia'
    WITH i, apoc.convert.fromJsonMap(i.metadata) AS meta
    RETURN i.id              AS id,
           i.title           AS title,
           meta.format       AS format,
           meta.duration_min AS duration_min,
           meta.language     AS language,
           meta.contributors AS contributors
    ORDER BY i.id
""")
```

### Query 4: Books with authors -- graph traversal

Graph traversal and metadata access compose naturally. We follow the `AUTHORED` relationship to join books with their authors, then access the book metadata in the same query:

```python
result = session.run("""
    MATCH (a:Author)-[:AUTHORED]->(i:Item)
    WITH a, i, apoc.convert.fromJsonMap(i.metadata) AS meta
    RETURN i.id          AS id,
           i.title       AS title,
           a.name        AS author,
           a.nationality AS nationality,
           meta.pages    AS pages,
           meta.language AS language
    ORDER BY a.name, i.id
""")
```

This is the value proposition of the pattern: graph structure for relationships, JSON strings for variable metadata, APOC to bridge the two.

### Query 5: Search journals by article keyword

Cypher's `ANY()` function iterates over a list and returns true if any element satisfies a predicate. We use it to search for journals containing a keyword in any article title:

```python
result = session.run("""
    MATCH (i:Item)
    WHERE i.item_type = 'journal'
    WITH i, apoc.convert.fromJsonMap(i.metadata) AS meta
    WHERE ANY(article IN meta.articles WHERE article CONTAINS $keyword)
    RETURN i.id        AS id,
           i.title     AS title,
           meta.editor AS editor,
           [article IN meta.articles WHERE article CONTAINS $keyword]
               AS matching_articles
    ORDER BY i.id
""", keyword=KEYWORD)
```

The list comprehension `[article IN meta.articles WHERE article CONTAINS $keyword]` returns only the matching article titles, not the full list. Both `ANY()` and list comprehensions work on deserialized APOC maps just as they work on native Cypher lists. Note that `CONTAINS` is case-sensitive, so a keyword of `AI` doesn't match `ai`.

### Query 6: Adding a field to metadata

To add a key to the stored metadata, parse the JSON string, extend the map using a Cypher map projection, then serialize back:

```python
session.run("""
    MATCH (i:Item {id: 1})
    WITH i, apoc.convert.fromJsonMap(i.metadata) AS meta
    SET i.metadata = apoc.convert.toJson(meta {.*, edition: 'Second'})
""")
```

The `meta {.*, edition: 'Second'}` map projection creates a new map containing all existing keys (`.*`) plus the new `edition` key. `apoc.convert.toJson()` serializes it back to a string. The original `metadata` property is replaced with the updated JSON string.

### Query 7: Removing a field from metadata

To remove a key, use `apoc.map.removeKey()`:

```python
session.run("""
    MATCH (i:Item {id: 1})
    WITH i, apoc.convert.fromJsonMap(i.metadata) AS meta
    SET i.metadata = apoc.convert.toJson(apoc.map.removeKey(meta, 'language'))
""")
```

`apoc.map.removeKey(meta, 'language')` returns a new map without the `language` key. The result is serialized back to JSON and stored. The round-trip -- parse, modify, serialize -- is the standard mutation pattern for JSON string properties in Neo4j.

Queries 6 and 7 change the stored data. Afterward, `The Quantum Garden` has an `edition` key and no `language`, which is why the app shows N/A for its language. Re-running the notebook starts from a clean database and resets it.

### The Streamlit app

The app is a single-screen layout with a sidebar. The sidebar has a type filter (All, Book, Journal, Multimedia), a keyword search input and a bar chart showing the count of items by type. The main area displays matching items as cards, with a type badge, title, publisher and type-specific metadata rendered by a `render_metadata()` function that handles each item type separately:

- Books -- ISBN, pages, language, author name
- Journals -- editor, volume, year, article count, expandable article list
- Multimedia -- format, duration, language, expandable contributors dict

The keyword search runs client-side against the already-loaded item data, searching across titles, author names, metadata fields (language, format, editor, ISBN) and article titles for journals. The search is case-insensitive, unlike the Cypher `CONTAINS` in Query 5.

## What you'd hit in production

**The JSON string round-trip.** Every query that needs to access metadata fields must call `apoc.convert.fromJsonMap()`. For read-heavy workloads this adds a small parsing overhead on every query. For most use cases it's imperceptible, but for very high-throughput queries you'd want to benchmark it.

**Frequently filtered fields.** If you find yourself filtering by a metadata field in every query -- `WHERE meta.language = 'English'` -- that field should be a top-level node property with its own index. The rule is: if you filter by it, promote it; if you just retrieve it, leave it in the JSON string.

**APOC availability.** A subset of APOC Core is pre-installed on Aura and the three functions used in this chapter are part of it. If you're running a self-hosted Neo4j deployment, APOC must be explicitly installed and enabled. Check `CALL apoc.help('convert')` to confirm it's available before relying on it.

**Mutation is a round-trip.** Adding or removing a metadata field requires parsing the JSON string, modifying the map and serializing it back -- two or three APOC function calls per mutation. For bulk updates across many nodes the cost adds up. Because each mutation rewrites the whole string, two concurrent updates to different keys can also overwrite each other. If metadata mutations are frequent, consider whether some fields should be top-level properties instead.

**Nested map depth.** The multimedia `contributors` map is one level deep inside the `metadata` map -- two levels total. You can go deeper, but each additional level of nesting makes the Cypher harder to write and the mutations more complex. Keep nesting shallow where possible.

## Going further

Document-style properties let nodes carry rich, structured metadata without requiring that metadata to have its own place in the graph. The book's edition details, the journal's article list and the multimedia item's contributors all live as JSON strings on the `Item` node, parsed by APOC when needed.

But all the metadata we've worked with so far -- titles, ISBNs, article names -- is symbolic. It carries meaning through its words and structure. Chapter 6 introduces a different way of representing meaning: embedding text and images as high-dimensional vectors, where proximity in the vector space corresponds to semantic similarity. Instead of searching by keyword, you search by content -- and the database finds the nearest neighbors in a space the embedding model learned. That's vector search and it's where we go next.
