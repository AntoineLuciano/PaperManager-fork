"""Ranked library search over Neo4j: lexical sources, optional semantic blend, snippets.

``search()`` is what ``GET /search`` (via db.queries.search.search_papers) and the MCP tool
``library_search`` call. Per query it runs one Lucene query per source, each already
restricted by the filters and the caller's project visibility, merges the hits per paper,
scores them (services.library_search.ranking), pages, and only then loads display fields,
author names and snippets for the papers on the page. See .specs/012_search.md.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from neo4j import Driver

from db.queries.visibility import paper_visibility_clause, project_visibility_clause
from services.library_search.query import (
    ParsedQuery,
    clean,
    lucene_all,
    lucene_any,
    matchers_for,
    mark,
    needles,
    on_fields,
    parse_query,
    snippet,
)
from services.library_search.ranking import (
    Candidate,
    SORTS,
    legacy_matched_in,
    rank,
    fuse,
    hybrid_weights,
    score_candidates,
    sort_candidates,
)

log = logging.getLogger(__name__)

REF_TAG = "from-references"
_K_PAPER = 1000      # hits read from paper_search (title/abstract/summary)
_K_OTHER = 300       # hits read from every other source
_SNIPPET_ORDER = ["note", "highlight", "abstract", "summary", "claim", "fulltext"]
_RAW_TEXT_MAX = 400_000  # characters of raw_text scanned for a full-text snippet
_WINDOW = 1400           # characters of raw_text sent back around the passage
# Paper properties returned per hit (what PaperOut / the frontend's Paper type carry).
_PAPER_FIELDS = ", ".join("." + f for f in (
    "id", "title", "year", "doi", "arxiv_id", "abstract", "summary", "drive_file_id",
    "citation_count", "metadata_source", "created_at", "updated_at", "venue", "reading_status",
    "rating", "bookmarked", "color", "document_type", "published_date"))
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="search-source")


@dataclass
class Filters:
    tag: str | None = None
    topic: str | None = None
    project_id: str | None = None
    project: str | None = None          # project name or id (MCP tools)
    person_id: str | None = None
    venue: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    reading_status: str | None = None
    bookmarked: bool | None = None
    include_references: bool = True


def filter_clause(f: Filters, var: str = "p") -> tuple[str, dict]:
    """Cypher predicate for the filters plus project visibility, and its parameters."""
    vis, vis_params = paper_visibility_clause(var)
    # Names and values compare case-insensitively: a filter set from "diffusion models"
    # matches the topic "Diffusion Models".
    parts = [
        f"($tag IS NULL OR EXISTS {{ MATCH ({var})-[:TAGGED]->(_t:Tag) WHERE toLower(_t.name) = toLower($tag) }})",
        f"($topic IS NULL OR EXISTS {{ MATCH ({var})-[:ABOUT]->(_tp:Topic) "
        f"WHERE toLower(_tp.name) = toLower($topic) }})",
        f"($pid IS NULL OR EXISTS {{ ({var})-[:IN_PROJECT]->(:Project {{id: $pid}}) }})",
        f"($project IS NULL OR EXISTS {{ MATCH ({var})-[:IN_PROJECT]->(_pr:Project) "
        f"WHERE _pr.id = $project OR toLower(_pr.name) = toLower($project) }})",
        f"($person IS NULL OR EXISTS {{ ({var})-[:AUTHORED_BY|INVOLVES]->(:Person {{id: $person}}) }})",
        f"($venue IS NULL OR toLower({var}.venue) = toLower($venue))",
        f"($year_min IS NULL OR {var}.year >= $year_min)",
        f"($year_max IS NULL OR {var}.year <= $year_max)",
        f"($status IS NULL OR toLower({var}.reading_status) = toLower($status))",
        f"($bookmarked IS NULL OR {var}.bookmarked = $bookmarked)",
        f"($refs OR NOT EXISTS {{ ({var})-[:TAGGED]->(:Tag {{name: '{REF_TAG}'}}) }})",
        vis,
    ]
    params = {
        "tag": f.tag, "topic": f.topic, "pid": f.project_id, "project": f.project or None,
        "person": f.person_id, "venue": f.venue, "year_min": f.year_min, "year_max": f.year_max,
        "status": f.reading_status, "bookmarked": f.bookmarked, "refs": bool(f.include_references),
        **vis_params,
    }
    return " AND ".join(parts), params


_COMMON = (f"p.id AS id, p.title AS title, p.year AS year, p.created_at AS created_at, "
           f"EXISTS {{ (p)-[:TAGGED]->(:Tag {{name: '{REF_TAG}'}}) }} AS ref, "
           f"COUNT {{ (p)<-[:CITES]-() }} AS cited")


def _sources(pq: ParsedQuery, where: str) -> list[tuple[str, str, dict]]:
    """(source name, Cypher, extra params) for every lexical source of a parsed query."""
    any_q = lucene_any(pq)
    out = [
        ("paper", f"""/*search:paper*/
            CALL db.index.fulltext.queryNodes('paper_search', $lq) YIELD node AS p, score
            WHERE {where}
            RETURN {_COMMON}, score, p.abstract AS abstract, p.summary AS summary
            LIMIT {_K_PAPER}""",
         {"lq": on_fields(any_q, {"title": 4, "abstract": 1, "summary": 0.7})}),
        ("entity", f"""/*search:entity*/
            CALL db.index.fulltext.queryNodes('entity_name_search', $lq) YIELD node AS e, score
            WITH e, score WHERE NOT e:Project AND NOT (e:Tag AND e.name = '{REF_TAG}')
            WITH e, score ORDER BY score DESC LIMIT 200
            MATCH (p:Paper)-[r:AUTHORED_BY|ABOUT|TAGGED]->(e)
            WHERE {where}
            RETURN {_COMMON}, score, type(r) AS rel, e.name AS name
            LIMIT 5000""",
         {"lq": on_fields(any_q, {"name": 1})}),
        ("venue", f"""/*search:venue*/
            CALL db.index.fulltext.queryNodes('paper_text_search', $lq) YIELD node AS p, score
            WHERE {where}
            RETURN {_COMMON}, score, p.venue AS venue
            LIMIT {_K_OTHER}""",
         {"lq": on_fields(any_q, {"venue": 1})}),
        ("fulltext", f"""/*search:fulltext*/
            CALL db.index.fulltext.queryNodes('paper_text_search', $lq) YIELD node AS p, score
            WHERE {where}
            RETURN {_COMMON}, score
            LIMIT {_K_OTHER}""",
         {"lq": on_fields(lucene_all(pq), {"raw_text": 1})}),
        ("note", f"""/*search:note*/
            CALL db.index.fulltext.queryNodes('note_search', $lq) YIELD node AS n, score
            MATCH (p:Paper)-[:HAS_NOTE]->(n)
            WHERE {where}
            RETURN {_COMMON}, score, n.content AS text
            LIMIT {_K_OTHER}""",
         {"lq": any_q}),
        ("highlight", f"""/*search:highlight*/
            CALL db.index.fulltext.queryNodes('annotation_search', $lq) YIELD node AS a, score
            MATCH (p:Paper)-[:HAS_ANNOTATION]->(a)
            WHERE {where}
            RETURN {_COMMON}, score, a.highlighted_text AS text, a.note AS comment,
                   a.page_number AS page
            LIMIT {_K_OTHER}""",
         {"lq": any_q}),
        ("claim", f"""/*search:claim*/
            CALL db.index.fulltext.queryNodes('claim_search', $lq) YIELD node AS c, score
            MATCH (p:Paper)-[:HAS_CLAIM]->(c)
            WHERE {where}
            RETURN {_COMMON}, score, c.text AS text
            LIMIT {_K_OTHER}""",
         {"lq": any_q}),
    ]
    return out


_REL_FIELD = {"AUTHORED_BY": "author", "ABOUT": "topic", "TAGGED": "tag"}


def _candidate(cands: dict[str, Candidate], r) -> Candidate:
    c = cands.get(r["id"])
    if c is None:
        c = cands[r["id"]] = Candidate(id=r["id"], title=r["title"] or "", year=r["year"],
                                       created_at=_iso(r["created_at"]), ref=bool(r["ref"]),
                                       cited=int(r.get("cited") or 0))
    return c


def _iso(v) -> str | None:
    if v is None:
        return None
    return v if isinstance(v, str) else str(v)


def _run(driver: Driver, cypher: str, params: dict) -> list:
    with driver.session() as s:
        return list(s.run(cypher, **params))


def _collect(rows, source: str, cands: dict[str, Candidate]) -> None:
    for r in rows:
        c = _candidate(cands, r)
        score = r["score"]
        if source == "paper":
            c.add("paper", score)
            for f in ("abstract", "summary"):
                if r[f]:
                    c.add("paper", score, f, r[f], cap=1)
        elif source == "entity":
            fld = _REL_FIELD.get(r["rel"], "tag")
            c.add(fld, score, fld, r["name"], cap=6)
        elif source == "venue":
            c.add("venue", score, "venue", r["venue"], cap=1)
        elif source == "fulltext":
            c.add("fulltext", score)
        elif source == "highlight":
            text = r["text"] or ""
            if r["comment"]:
                text = f"{text} — {r['comment']}" if text else r["comment"]
            c.add("highlight", score, "highlight", text)
            if r["page"] is not None and r["page"] not in c.pages:
                c.pages.append(r["page"])
        else:  # note, claim
            c.add(source, score, source, r["text"])


def _identifier_hits(session, ident: dict, where: str, params: dict,
                     cands: dict[str, Candidate]) -> None:
    if "doi" in ident:
        doi = ident["doi"]
        arxiv = None
        if doi.startswith("10.48550/arxiv."):
            arxiv = doi.split("arxiv.", 1)[1]
    else:
        arxiv = ident["arxiv"]
        doi = f"10.48550/arxiv.{arxiv}"
    rows = session.run(
        f"""/*search:identifier*/
        MATCH (p:Paper)
        WHERE (toLower(p.doi) IN $dois OR ($arxiv IS NOT NULL AND toLower(p.arxiv_id) = $arxiv))
          AND {where}
        RETURN {_COMMON}, 1.0 AS score""",
        dois=[doi] + ([f"arxiv:{arxiv}", arxiv] if arxiv else []), arxiv=arxiv, **params)
    for r in rows:
        _candidate(cands, r).add("identifier", 1.0)


def lexical_candidates(driver: Driver, pq: ParsedQuery, f: Filters) -> tuple[list[Candidate], list[str]]:
    """Every paper any lexical source returns, merged per paper. Also returns the names of
    sources that failed (an index still populating, say) so callers can report them."""
    where, params = filter_clause(f)
    cands: dict[str, Candidate] = {}
    failed: list[str] = []
    if pq.identifier:
        try:
            with driver.session() as s:
                _identifier_hits(s, pq.identifier, where, params, cands)
        except Exception as exc:  # noqa: BLE001
            log.warning("search source identifier failed: %s", exc)
            failed.append("identifier")
        if cands:
            return list(cands.values()), failed
    if not pq.units:
        return [], failed
    # The sources are independent: run them on separate sessions in parallel, then merge
    # in a fixed order so ties break the same way every time.
    sources = _sources(pq, where)
    futures = [(_POOL.submit(_run, driver, cypher, {**params, **extra}), source)
               for source, cypher, extra in sources]
    for fut, source in futures:
        try:
            _collect(fut.result(), source, cands)
        except Exception as exc:  # noqa: BLE001 — one broken source must not fail the search
            log.warning("search source %s failed: %s", source, exc)
            failed.append(source)
    return list(cands.values()), failed


def _semantic_candidates(driver: Driver, q: str, where: str, params: dict,
                         k: int = 200) -> tuple[list[Candidate], float | None]:
    """Nearest papers by embedding that pass the filters, best first and cut at the
    similarity floors, plus the best raw similarity (``None`` without an index)."""
    from services.library_search import semantic

    hits = semantic.query(q, k=k)
    if not hits:
        return [], None
    sims = dict(hits)
    with driver.session() as s:
        rows = s.run(
            f"""/*search:semantic*/
            MATCH (p:Paper) WHERE p.id IN $ids AND {where}
            RETURN {_COMMON}""", ids=list(sims), **params)
        out = []
        for r in rows:
            c = Candidate(id=r["id"], title=r["title"] or "", year=r["year"],
                          created_at=_iso(r["created_at"]), ref=bool(r["ref"]),
                          cited=int(r.get("cited") or 0))
            c.semantic = sims[r["id"]]
            out.append(c)
    out.sort(key=lambda c: -(c.semantic or 0))
    return semantic.cut(out), hits[0][1]


def _hydrate(driver: Driver, page: list[Candidate], pq: ParsedQuery, max_snippets: int) -> list[dict]:
    """Display fields, authors and snippets for the papers on the page, in page order."""
    if not page:
        return []
    ids = [c.id for c in page]
    proj_vis, proj_params = project_visibility_clause("pr")
    with driver.session() as s:
        rows = {r["id"]: r for r in s.run(
            f"""MATCH (p:Paper) WHERE p.id IN $ids
                OPTIONAL MATCH (u:User)-[:ADDED]->(p)
                WITH p, head(collect(u)) AS added_user
                RETURN p.id AS id, p {{{_PAPER_FIELDS}}} AS p,
                       added_user.name AS added_by, added_user.color AS added_by_color,
                       [(p)-[:AUTHORED_BY]->(a:Person) | a.name][..12] AS authors,
                       size(coalesce(p.raw_text, '')) AS text_chars,
                       EXISTS {{ (p)-[:HAS_NOTE]->() }} AS has_note,
                       COUNT {{ (p)-[:HAS_ANNOTATION]->() }} AS highlight_count,
                       [(p)-[:IN_PROJECT]->(pr:Project) WHERE {proj_vis} | pr.name] AS projects""",
            ids=ids, **proj_params)}
        need_text = [c.id for c in page if "fulltext" in c.fields
                     and sum(1 for f in _SNIPPET_ORDER[:-1] if c.texts.get(f)) < max_snippets]
        raw = {}
        if need_text and pq.units:
            # Locate the passage in Neo4j (first occurrence of the most specific needle,
            # found with split() as Cypher has no indexOf) and ship only ~1.4 kB of it.
            raw = {r["id"]: (r["t"], r["cut_before"], r["cut_after"]) for r in s.run(
                f"""MATCH (p:Paper) WHERE p.id IN $ids
                    WITH p, toLower(substring(coalesce(p.raw_text, ''), 0, {_RAW_TEXT_MAX})) AS low
                    WITH p, low, [n IN $needles | size(split(low, n)[0])] AS pos
                    WITH p, low, [x IN pos WHERE x < size(low)] AS found
                    WITH p, low, CASE WHEN size(found) = 0 THEN 0 ELSE found[0] END AS at
                    WITH p, low, CASE WHEN at > {_WINDOW // 2} THEN at - {_WINDOW // 2} ELSE 0 END AS a
                    RETURN p.id AS id, substring(p.raw_text, a, {_WINDOW}) AS t,
                           a > 0 AS cut_before, a + {_WINDOW} < size(low) AS cut_after""",
                ids=need_text, needles=needles(pq))}

    matchers = matchers_for(pq)
    out = []
    for c in page:
        r = rows.get(c.id)
        if r is None:
            continue
        paper = {k: v for k, v in dict(r["p"]).items() if v is not None}
        if "created_at" in paper:
            paper["created_at"] = _iso(paper["created_at"])
        if "updated_at" in paper:
            paper["updated_at"] = _iso(paper["updated_at"])
        snippets = []
        if matchers:
            for fld in _SNIPPET_ORDER:
                if len(snippets) >= max_snippets:
                    break
                if fld == "fulltext":
                    t, before, after = raw.get(c.id, ("", False, False))
                    texts = [(t, before, after)]
                else:
                    texts = [(t, False, False) for t in c.texts.get(fld, [])]
                for t, before, after in texts:
                    sn = snippet(t, matchers, cut_before=before, cut_after=after)
                    if sn:
                        sn["field"] = fld
                        if fld == "highlight" and c.pages:
                            sn["page"] = c.pages[0]
                        snippets.append(sn)
                        break
        if not snippets and "semantic" in c.fields:
            # A meaning-only hit: show where the abstract mentions a query word, else its start.
            fld = "abstract" if paper.get("abstract") else "summary"
            body = paper.get(fld) or ""
            sn = snippet(body, matchers) if matchers else None
            if sn is None and body:
                text = clean(body)
                sn = {"text": text[:240] + ("…" if len(text) > 240 else ""), "marks": []}
            if sn:
                snippets.append({**sn, "field": fld})
        matches = {f: c.texts[f] for f in ("author", "topic", "tag", "venue") if c.texts.get(f)}
        paper.update(
            score=round(c.score, 4),
            matched_in=legacy_matched_in(c.fields),
            matched_fields=c.fields,
            matches=matches,
            snippets=snippets,
            title_marks=mark(paper.get("title") or "", matchers) if matchers else [],
            authors=r["authors"],
            added_by=r["added_by"],
            added_by_color=r["added_by_color"],
            is_reference=c.ref,
            text_chars=r["text_chars"],
            has_note=bool(r["has_note"]),
            highlight_count=r["highlight_count"],
            projects=r["projects"],
        )
        if c.semantic is not None:
            paper["similarity"] = round(float(c.semantic), 4)
        out.append(paper)
    return out


MODES = {"lexical", "semantic", "hybrid"}


def search(driver: Driver, q: str, filters: Filters | None = None, *, skip: int = 0,
           limit: int = 20, sort: str = "relevance", mode: str = "lexical",
           max_snippets: int = 2) -> dict:
    """Ranked search. Returns ``{"results", "total", "mode", "relaxed", "semantic",
    "failed_sources", "took_ms"}``; ``mode`` is the mode actually used (hybrid falls back
    to lexical while the embedding index is not ready)."""
    t0 = time.perf_counter()
    f = filters or Filters()
    pq = parse_query(q)
    mode = mode if mode in MODES else "lexical"
    sort = sort if sort in SORTS else "relevance"
    skip, limit = max(0, int(skip)), max(1, min(int(limit), 2000))

    sem_hits: list[Candidate] = []
    top_sim = None
    sem_status = None
    sem_future = None
    if mode in ("semantic", "hybrid") and pq.raw and not pq.identifier:
        from services.library_search import semantic

        sem_status = semantic.status()
        where, params = filter_clause(f)  # here: the request user lives in this thread
        sem_future = _POOL.submit(_semantic_candidates, driver, pq.raw, where, params)

    lexical: list[Candidate] = []
    failed: list[str] = []
    relaxed = False
    if mode != "semantic":
        lexical, failed = lexical_candidates(driver, pq, f)
    if sem_future is not None:
        try:
            sem_hits, top_sim = sem_future.result()
        except Exception as exc:  # noqa: BLE001 — semantic search is optional
            log.warning("semantic search failed: %s", exc)
            sem_status = {**(sem_status or {}), "state": "error", "error": str(exc)[:200]}
    if mode == "semantic" and not sem_hits:
        # No index yet, or nothing similar enough: answer lexically rather than with nothing.
        lexical, failed = lexical_candidates(driver, pq, f)
    score_candidates(lexical, pq)
    lexical, relaxed = rank(lexical)

    if mode == "semantic" and sem_hits:
        used, ranked = "semantic", sem_hits
        for c in ranked:
            c.score, c.fields = c.semantic or 0.0, ["semantic"]
    elif mode == "hybrid" and sem_hits:
        used = "hybrid"
        ranked = fuse(lexical, sem_hits, hybrid_weights(len(pq.units), relaxed, top_sim))
    else:
        used, ranked = "lexical", lexical
    if sem_status is not None and top_sim is not None:
        sem_status["top_similarity"] = round(top_sim, 4)

    ranked = sort_candidates(ranked, sort)
    page = ranked[skip: skip + limit]
    results = _hydrate(driver, page, pq, max_snippets)
    return {
        "results": results,
        "total": len(ranked),
        "mode": used,
        "relaxed": relaxed,
        "semantic": sem_status,
        "failed_sources": failed,
        "took_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
