# Introduction

## Neo4j Beyond the Graph

Ask a developer what Neo4j is and you'll almost always get the same answer: a graph database. That answer is correct, but it's also incomplete, and the gap between what most people know about Neo4j and what Neo4j can actually do is the reason this book exists.

Neo4j started as a graph database and graph traversal remains its core strength. If you need to find the shortest path between two nodes, detect communities in a network or traverse a hierarchy in milliseconds, nothing beats native graph storage. But over the years Neo4j has grown into something considerably broader. It now supports full-text search, native geospatial queries, temporal reasoning, document-style properties, vector similarity search and the combination of graph traversal with vector search that makes it genuinely unique in the database landscape. These aren't bolt-on features or integrations with external systems. They're built in and they work together.

Many Neo4j users don't know this. They connect to an Aura instance, model their domain as nodes and relationships, write some Cypher and move on. That's a perfectly valid use of the product. But it's a fraction of what's available and the chapters that follow are an attempt to close that gap.

## What This Book Is About

Each chapter focuses on one Neo4j capability and one use case chosen to showcase it. We start with the native graph model -- the foundation everything else builds on -- and work outward from there. By the end you'll have seen Neo4j handle transport networks, research literature, air quality data, financial time series, library inventories, image similarity and fraud detection, each using a different capability or combination of capabilities.

The progression is deliberate. We begin with what Neo4j is best known for and add capabilities one at a time, so each chapter extends your mental model rather than replacing it. By chapter 7, when we combine graph traversal with vector search to detect fraud rings, you'll be drawing on everything that came before.

| Chapter | Capability | Use Case |
| --- | --- | --- |
| 1 | Native Graph | London Underground routing |
| 2 | Full-Text Search | Research paper discovery |
| 3 | Geospatial | Air quality along the Pyrenees corridor |
| 4 | Temporal | S&P 500 stock price analysis |
| 5 | Document-Style Properties | Library inventory management |
| 6 | Vector Search | Fashion image similarity |
| 7 | Graph + Vector | Fraud ring detection |

## Who This Book Is For

This book is written for developers and data engineers who already have some familiarity with Neo4j -- you've run a Cypher query, you understand the node-relationship model -- but haven't explored the capabilities beyond the graph. It assumes you're comfortable with Python and Jupyter notebooks. It doesn't assume any prior experience with vector search, geospatial indexing or full-text search engines.

If you've been using Neo4j as a graph database and wondering what else it can do, this book is for you. If you're evaluating Neo4j for a use case that isn't purely graph-shaped -- a search problem, a geospatial problem, a time series problem -- this book is for you. If you're building an application that needs several of these capabilities together, particularly the graph-plus-vector combination that closes the book, this book is for you.

## How the Book Is Structured

Each chapter follows the same structure:

- **What is it** -- a characterization of the capability, how it works inside Neo4j and what makes it distinctive
- **When would you reach for it** -- the practical question answered upfront: when does this capability earn its place in your architecture?
- **The use case** -- the specific scenario for that chapter, chosen because it genuinely fits the capability rather than to manufacture a demo
- **The data** -- the dataset used and why it suits the problem
- **Building the application** -- a hands-on walkthrough with code, including gotchas we encountered along the way
- **What you'd hit in production** -- honest notes on limitations, operational considerations and scale
- **Going further** -- what combining this capability with others unlocks and how it connects to later chapters

Every chapter comes with a Jupyter notebook and a Streamlit application. The notebooks are self-contained and independently runnable. All examples run on Neo4j Aura's free tier, which is sufficient for the datasets used throughout the book.

## A Note on the Dataset Choices

Some chapters use real-world data -- London Underground station coordinates, Pyrenees air quality readings from IQAir, S&P 500 price history from Kaggle. Others use synthetic data generated in the notebook itself. In every case the choice was made to give the capability room to show what it can do: a transport network for graph traversal, tightly clustered financial amounts for fraud detection, high-dimensional pixel vectors for image similarity.

Where data comes from an external source it's either publicly available under an open license or generated fresh by running the notebook. Two chapters require free-tier API keys: chapters 1 and 3 use CartoDB basemap tiles for Folium maps and chapter 3 additionally uses the IQAir API for air quality data. Both keys are available on free tiers at [carto.com](https://carto.com/basemaps/apikey/) and [iqair.com](https://www.iqair.com/dashboard/api/).

## A Note on Aura

All examples in this book run against Neo4j Aura, the fully managed cloud service. Aura's free tier provides enough storage and compute for every dataset in the book. The connection pattern is the same throughout: set up to four environment variables -- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` and `NEO4J_DATABASE` -- and every notebook connects without further configuration. Not all chapters use a named database; check the prerequisites section of each chapter for the exact variables required.

If you prefer to run Neo4j locally, everything works identically against Neo4j Desktop. The only adjustment is the connection URI and credentials.

## Code and Notebooks

All notebooks, Streamlit applications and source code are available at:

[beyond-the-graph.github.io](https://beyond-the-graph.github.io)

Each notebook is self-contained with its own `requirements.txt`. A single combined `requirements.txt` at the repo root installs all dependencies for all chapters at once -- useful if you plan to work through the book from start to finish. You'll need Python 3.12, a virtual environment and classic Jupyter installed locally.
