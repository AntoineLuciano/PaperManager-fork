"""Search over Paper nodes: ranked text search, or filters only.

With a query the work is done by services.library_search.engine (ranking across titles,
authors, topics, tags, venue, abstracts, notes, highlights, claims and full text; see
.specs/012_search.md). Without one, a plain filtered MATCH ordered by ``sort``.
"""
from __future__ import annotations

from neo4j import Driver

from services.library_search.engine import Filters, filter_clause, search

_ORDER = {
    "date_desc": "p.created_at DESC",
    "date_asc": "p.created_at ASC",
    "year_desc": "p.year DESC, p.created_at DESC",
    "year_asc": "p.year ASC, p.created_at DESC",
    "title_asc": "toLower(p.title) ASC",
}


def search_papers(
    driver: Driver,
    q: str | None = None,
    tag: str | None = None,
    topic: str | None = None,
    project_id: str | None = None,
    person_id: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    reading_status: str | None = None,
    bookmarked: bool | None = None,
    skip: int = 0,
    limit: int = 20,
    *,
    venue: str | None = None,
    include_references: bool = True,
    sort: str = "relevance",
    mode: str = "lexical",
    max_snippets: int = 2,
) -> dict:
    """Return ``{"results": [...], "total": int, ...}``.

    With *q*: ranked hits, each with ``score``, ``matched_in`` (coarse, e.g. "note+paper"),
    ``matched_fields``, ``matches``, ``snippets`` and ``title_marks``; the response adds
    ``mode``, ``relaxed``, ``semantic``, ``failed_sources`` and ``took_ms``. Without *q*:
    the filtered papers (``matched_in`` "filter"), newest first unless *sort* says otherwise.
    """
    filters = Filters(
        tag=tag, topic=topic, project_id=project_id, person_id=person_id, venue=venue,
        year_min=year_min, year_max=year_max, reading_status=reading_status,
        bookmarked=bookmarked, include_references=include_references,
    )
    if q and q.strip():
        return search(driver, q, filters, skip=skip, limit=limit, sort=sort, mode=mode,
                      max_snippets=max_snippets)
    return _filter_search(driver, filters, skip, limit, sort)


def _filter_search(driver: Driver, f: Filters, skip: int, limit: int, sort: str = "date_desc") -> dict:
    """Filter-only search — no text query."""
    where, params = filter_clause(f)
    order = _ORDER.get(sort, _ORDER["date_desc"])
    with driver.session() as session:
        total = session.run(
            f"MATCH (p:Paper) WHERE {where} RETURN count(p) AS c", **params).single()
        result = session.run(
            f"""
            MATCH (p:Paper)
            WHERE {where}
            WITH p ORDER BY {order} SKIP $skip LIMIT $limit
            OPTIONAL MATCH (u:User)-[:ADDED]->(p)
            WITH p, head(collect(u)) AS added_user
            RETURN p, 0.0 AS score, "filter" AS matched_in,
                   added_user.name AS added_by, added_user.color AS added_by_color
            ORDER BY {order}
            """,
            skip=max(0, int(skip)), limit=max(1, min(int(limit), 2000)), **params,
        )
        rows = []
        for r in result:
            d = {k: v for k, v in dict(r["p"]).items() if k not in ("raw_text", "embedding")}
            d["score"] = r["score"]
            d["matched_in"] = r["matched_in"]
            d["added_by"] = r["added_by"]
            d["added_by_color"] = r["added_by_color"]
            rows.append(d)
    count = total["c"] if total is not None else len(rows)
    return {"results": rows, "total": max(count, len(rows))}
