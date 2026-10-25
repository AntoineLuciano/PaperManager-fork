"""Conference explorer: browse the accepted papers of the major ML / CV / NLP conferences
by institution and by topic.

A conference-year (``neurips2026``) is fetched from its public source once, normalised
(institutions, research areas, embeddings) and kept on disk under the data directory.
Nothing here touches Neo4j except the optional library match and "add to library".

Modules:
    catalog       which conference-years exist and where their data comes from
    sources       fetchers for the miniconf feeds and Paper Copilot's paper lists
    institutions  institution name normalisation and academia / industry split
    areas         the fixed research-area taxonomy and zero-shot assignment
    embedder      BAAI/bge-small-en-v1.5 on CPU (titles + abstracts, queries)
    store         build pipeline, on-disk dataset, background worker, queries
"""
