"""Library search: ranked lexical search, type-ahead suggestions and an embedding index.

- ``query``    parsing, Lucene query building, match marking and snippets (pure)
- ``ranking``  per-source weights, coverage filter, rank fusion (pure)
- ``engine``   the Neo4j side: one Lucene query per source, paging, hydration
- ``suggest``  type-ahead over titles and Person/Topic/Tag/Project names
- ``semantic`` bge-small embeddings of title + abstract on disk, background sync

Spec: .specs/012_search.md.
"""
