"""Batch existence check: which of these DOIs / titles are already in the library?

Backs the MCP tool `library_lookup` (tools/library_tools.py). A client about to add cited
papers asks once for the whole list instead of running a ranked search per paper, and gets
back one short line per item: the matching paper(s) or nothing. No summaries, no snippets.

Two Cypher queries per call, whatever the number of items:

1. every visible paper's id, DOI and title (≈0.1 s for 9k papers), normalised and matched in
   Python, because neither the DOI spellings nor the titles can be normalised inside Cypher;
2. the details (year, projects, reference-stub flag, whether there is text) of the matches.

Matching per item: the normalised DOI first, then the normalised title exactly, then the
first ``PREFIX_CHARS`` characters of the normalised title. A paper stored under its bioRxiv
DOI while the query carries the journal DOI misses on DOI and is found by title.
"""
from __future__ import annotations

import html
import re
import unicodedata

from neo4j import Driver

from db.queries.visibility import paper_visibility_clause, project_visibility_clause
from services.duplicate_scan import normalize_doi as _canonical_doi

MAX_ITEMS = 200
PREFIX_CHARS = 45
REF_TAG = "from-references"

_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)")
_ARXIV_URL = re.compile(r"^(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/")
_OLD_ARXIV = re.compile(r"^(?:arxiv:)?([a-z][a-z\-]*(?:\.[a-z]{2})?/\d{7})(?:v\d+)?$")
_TAG = re.compile(r"<[^>]*>")


def doi_key(doi: str | None) -> str | None:
    """Canonical lookup key of a DOI or arXiv identifier.

    Lowercase; ``https://doi.org/``, ``http://dx.doi.org/``, ``doi:`` and arxiv.org URLs
    stripped; trailing ``.`` dropped. ``10.48550/arXiv.2210.02747``, ``arXiv:2210.02747``,
    ``2210.02747`` and ``2210.02747v2`` all become ``arxiv:2210.02747``; old-style ids
    (``cs/0010026``) become ``arxiv:cs/0010026``. bioRxiv version suffixes are dropped.
    Anything else that is not empty is kept as the cleaned lowercase string."""
    if not doi:
        return None
    x = unicodedata.normalize("NFKC", str(doi)).strip().lower()
    x = _DOI_PREFIX.sub("", x)
    if _ARXIV_URL.match(x):
        x = "arxiv:" + _ARXIV_URL.sub("", x)
    x = re.sub(r"\.pdf$", "", x).strip().rstrip(".").strip()
    if not x:
        return None
    canon = _canonical_doi(x)
    if canon:
        return canon
    m = _OLD_ARXIV.fullmatch(x)
    if m:
        return "arxiv:" + m.group(1)
    return x


def title_key(title: str | None) -> str:
    """Title reduced to ``[a-z0-9]``: HTML entities decoded, markup such as ``<i>``,
    ``<sub>``, ``<scp>`` removed, accents folded, everything else (spaces too) dropped."""
    t = html.unescape(title or "")
    t = _TAG.sub("", t)
    t = unicodedata.normalize("NFKD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def _items(dois: list[str] | None, titles: list[str] | None) -> list[tuple[str, str]]:
    """(doi, title) per query item; two lists are paired by index."""
    dois, titles = list(dois or []), list(titles or [])
    n = max(len(dois), len(titles))
    dois += [""] * (n - len(dois))
    titles += [""] * (n - len(titles))
    return [((d or "").strip(), (t or "").strip()) for d, t in zip(dois, titles)]


def build_index(rows: list[list]) -> tuple[dict, dict, dict]:
    """Maps doi key / title key / title prefix -> paper ids, from [id, doi, title] rows."""
    by_doi: dict[str, list[str]] = {}
    by_title: dict[str, list[str]] = {}
    by_prefix: dict[str, list[str]] = {}
    for pid, doi, title in rows:
        k = doi_key(doi)
        if k:
            by_doi.setdefault(k, []).append(pid)
        t = title_key(title)
        if t:
            by_title.setdefault(t, []).append(pid)
            if len(t) >= PREFIX_CHARS:
                by_prefix.setdefault(t[:PREFIX_CHARS], []).append(pid)
    return by_doi, by_title, by_prefix


def match_item(doi: str, title: str, index: tuple[dict, dict, dict]) -> tuple[str | None, list[str]]:
    """(kind, paper ids) for one item: DOI first, then exact title, then title prefix."""
    by_doi, by_title, by_prefix = index
    k = doi_key(doi)
    if k and k in by_doi:
        return "doi", by_doi[k]
    t = title_key(title)
    if t:
        if t in by_title:
            return "title_exact", by_title[t]
        if len(t) >= PREFIX_CHARS and t[:PREFIX_CHARS] in by_prefix:
            return "title_prefix", by_prefix[t[:PREFIX_CHARS]]
    return None, []


def lookup(driver: Driver, dois: list[str] | None = None, titles: list[str] | None = None,
           project: str = "", url_base: str = "") -> dict:
    """Run the batch check. Returns ``{found, missing, items: [...]}`` (see module doc)."""
    items = _items(dois, titles)
    if not items:
        return {"error": "give dois and/or titles", "found": 0, "missing": 0, "items": []}
    if len(items) > MAX_ITEMS:
        return {"error": f"{len(items)} items; at most {MAX_ITEMS} per call", "found": 0,
                "missing": 0, "items": []}
    project = (project or "").strip()

    vis, vis_params = paper_visibility_clause("p")
    pvis, pvis_params = project_visibility_clause("pr")
    with driver.session() as s:
        rec = s.run(
            f"""MATCH (p:Paper) WHERE {vis}
                WITH collect([p.id, p.doi, p.title]) AS rows
                OPTIONAL MATCH (pr:Project)
                WHERE $project <> '' AND (pr.id = $project OR toLower(pr.name) = toLower($project))
                  AND {pvis}
                RETURN rows, collect(pr.name) AS project_names""",
            project=project, **{**vis_params, **pvis_params}).single()
        index = build_index(rec["rows"])
        matched = [(d, t, *match_item(d, t, index)) for d, t in items]
        ids = sorted({i for *_, kind, pids in matched for i in pids})
        details = {}
        if ids:
            for r in s.run(
                f"""UNWIND $ids AS id MATCH (p:Paper {{id: id}})
                    RETURN p.id AS id, p.title AS title, p.doi AS doi, p.year AS year,
                           [(p)-[:IN_PROJECT]->(pr:Project) WHERE {pvis} | {{id: pr.id, name: pr.name}}] AS projects,
                           EXISTS {{ (p)-[:TAGGED]->(:Tag {{name: $ref}}) }} AS ref,
                           size(coalesce(p.raw_text, '')) > 0 AS has_text""",
                ids=ids, ref=REF_TAG, **pvis_params):
                details[r["id"]] = dict(r)

    def entry(pid: str) -> dict:
        d = details[pid]
        e = {"id": pid, "title": d["title"], "doi": d["doi"], "year": d["year"],
             "projects": sorted(p["name"] for p in d["projects"] if p["name"]),
             "reference_stub": bool(d["ref"]), "has_text": bool(d["has_text"]),
             "url": f"{url_base.rstrip('/')}/paper/{pid}"}
        if project:
            e["in_project"] = any(p["id"] == project or (p["name"] or "").lower() == project.lower()
                                  for p in d["projects"])
        return e

    out, found = [], 0
    for doi, title, kind, pids in matched:
        query = doi if doi and not title else title if title and not doi else {"doi": doi, "title": title}
        es = [entry(p) for p in pids if p in details]
        # Real library entries before citation stubs, papers with text before those without.
        es.sort(key=lambda e: (e["reference_stub"], not e["has_text"]))
        row: dict = {"query": query, "kind": kind if es else None,
                     "match": None if not es else es[0] if len(es) == 1 else es}
        if len(es) > 1:
            row["duplicates"] = len(es)
        found += bool(es)
        out.append(row)

    res = {"found": found, "missing": len(out) - found}
    if project:
        res["project"] = project
        if not rec["project_names"]:
            res["project_error"] = f"no project named or with id '{project}'"
    res["items"] = out
    return res
