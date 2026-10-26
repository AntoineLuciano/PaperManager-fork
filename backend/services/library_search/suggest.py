"""Type-ahead suggestions: papers (by title), authors, topics, tags and projects.

Two Lucene queries, every token as a required prefix (``tero kar`` -> ``+tero* +kar*``):
``paper_search`` on the title for library papers (reference stubs excluded) and
``entity_name_search`` over Person/Topic/Tag/Project names, the latter ranked by Lucene
score plus a log bonus for how many papers carry the entity.
"""
from __future__ import annotations

import math

from neo4j import Driver

from db.queries.visibility import paper_visibility_clause, project_visibility_clause
from services.library_search.query import lucene_prefix_all, on_fields, tokenize

REF_TAG = "from-references"


def rank_entities(rows: list[dict], per_kind: int) -> dict[str, list[dict]]:
    """Group entity rows ``{kind, id, name, papers, score}`` by kind, best first: Lucene
    score plus ``0.5 * log1p(papers)``, entities without papers last."""
    out: dict[str, list[dict]] = {"authors": [], "topics": [], "tags": [], "projects": []}
    key = {"Person": "authors", "Topic": "topics", "Tag": "tags", "Project": "projects"}
    ranked = sorted(rows, key=lambda r: (-(r["papers"] > 0), -(r["score"] + 0.5 * math.log1p(r["papers"])),
                                         r["name"].lower()))
    for r in ranked:
        k = key.get(r["kind"])
        if k and len(out[k]) < per_kind:
            out[k].append({"id": r["id"], "name": r["name"], "papers": r["papers"]})
    return out


def suggest(driver: Driver, q: str, limit: int = 5) -> dict:
    # Every typed token counts here, stop words included ("on the" -> +on* +the*).
    tokens = tokenize((q or "")[:200])[:8]
    if not tokens:
        return {"query": q, "papers": [], "authors": [], "topics": [], "tags": [], "projects": []}
    lq = lucene_prefix_all(tokens)
    limit = max(1, min(int(limit), 10))
    vis, vis_params = paper_visibility_clause("p")
    pvis, pvis_params = project_visibility_clause("e")
    with driver.session() as s:
        papers = [dict(r) for r in s.run(
            f"""CALL db.index.fulltext.queryNodes('paper_search', $lq) YIELD node AS p, score
                WHERE NOT EXISTS {{ (p)-[:TAGGED]->(:Tag {{name: '{REF_TAG}'}}) }} AND {vis}
                RETURN p.id AS id, p.title AS title, p.year AS year
                ORDER BY score DESC LIMIT $n""",
            lq=on_fields(lq, {"title": 1}), n=limit, **vis_params)]
        rows = [dict(r) for r in s.run(
            f"""CALL db.index.fulltext.queryNodes('entity_name_search', $lq, {{limit: 80}})
                YIELD node AS e, score
                WITH e, score WHERE NOT (e:Tag AND e.name = '{REF_TAG}')
                  AND (NOT e:Project OR {pvis})
                RETURN head([l IN labels(e) WHERE l IN ['Person','Topic','Tag','Project']]) AS kind,
                       e.id AS id, e.name AS name, score,
                       CASE
                         WHEN e:Person THEN COUNT {{ (e)<-[:AUTHORED_BY]-(:Paper) }}
                         WHEN e:Topic THEN COUNT {{ (e)<-[:ABOUT]-(:Paper) }}
                         WHEN e:Tag THEN COUNT {{ (e)<-[:TAGGED]-(:Paper) }}
                         ELSE COUNT {{ (e)<-[:IN_PROJECT]-(:Paper) }}
                       END AS papers""",
            lq=on_fields(lq, {"name": 1}), **pvis_params)]
    return {"query": q, "papers": papers, **rank_entities([r for r in rows if r["name"]], limit)}
