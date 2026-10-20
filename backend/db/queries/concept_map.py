"""Project concept map: (Paper)-[:DISCUSSES]->(MapConcept)-[:CONCEPT_LINK]->(MapConcept).

A MapConcept is shared by every paper that discusses it (unlike Concept, which is
one visualised idea on one PDF page). DISCUSSES carries the paper's role for the
concept and a sentence on what the paper does with it; CONCEPT_LINK carries the
relation type, the paper that states it and a short piece of evidence, so one
concept pair can be linked by several papers.
"""
import uuid
from datetime import datetime, timezone

from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_papers_for_mapping(driver: Driver, project_id: str) -> list[dict]:
    """Every paper in the project with what the extractor needs, and whether it is mapped."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper)-[:IN_PROJECT]->(:Project {id: $pid})
            OPTIONAL MATCH (p)-[:AUTHORED_BY]->(a:Person)
            WITH p, collect(a.name) AS authors
            OPTIONAL MATCH (p)-[:HAS_CLAIM]->(c:Claim)
            RETURN p.id AS id, p.title AS title, p.year AS year, p.abstract AS abstract,
                   p.summary AS summary, left(coalesce(p.raw_text, ''), 12000) AS raw_text,
                   p.concept_map_at AS mapped_at, authors, collect(c.text) AS claims
            ORDER BY coalesce(p.year, 0) ASC, p.title ASC
            """,
            pid=project_id,
        )
        return [dict(r) for r in result]


def unmapped_project_papers(driver: Driver, ready_before: str, max_attempts: int = 3) -> dict[str, list[str]]:
    """Project id -> ids of its papers that are ready to map and never were.

    Ready: the summary exists, or the paper is older than *ready_before* (ISO time)
    and so its upload pipeline has finished without one. Papers whose last
    extraction timed out are retried up to *max_attempts* times; other failures
    are left to a manual build.
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper)-[:IN_PROJECT]->(proj:Project)
            WHERE p.concept_map_at IS NULL
              AND (p.concept_map_error IS NULL
                   OR (p.concept_map_error CONTAINS 'Timeout'
                       AND coalesce(p.concept_map_attempts, 1) < $max_attempts))
              AND (coalesce(p.summary, '') <> '' OR coalesce(p.created_at, '') < $ready_before)
              AND (coalesce(p.summary, '') <> '' OR coalesce(p.abstract, '') <> ''
                   OR EXISTS { (p)-[:HAS_CLAIM]->() } OR p.raw_text IS NOT NULL)
            RETURN proj.id AS project_id, collect(p.id) AS paper_ids
            """,
            ready_before=ready_before,
            max_attempts=max_attempts,
        )
        return {r["project_id"]: r["paper_ids"] for r in result}


def project_vocabulary(driver: Driver, project_id: str, limit: int = 250) -> list[str]:
    """Concept names already in the project's map, most-discussed first."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (:Project {id: $pid})<-[:IN_PROJECT]-(:Paper)-[:DISCUSSES]->(c:MapConcept)
            RETURN c.name AS name, count(*) AS n ORDER BY n DESC, name ASC LIMIT $limit
            """,
            pid=project_id,
            limit=limit,
        )
        return [r["name"] for r in result]


def _resolve_concept(tx, concept: dict) -> str:
    """Id of the MapConcept this extracted concept belongs to, creating it if new."""
    keys = [concept["key"], *concept["alias_keys"]]
    rec = tx.run(
        """
        MATCH (c:MapConcept)
        WHERE c.key IN $keys OR any(k IN coalesce(c.alias_keys, []) WHERE k IN $keys)
        RETURN c.id AS id ORDER BY CASE WHEN c.key = $key THEN 0 ELSE 1 END LIMIT 1
        """,
        keys=keys,
        key=concept["key"],
    ).single()
    if rec:
        tx.run(
            """
            MATCH (c:MapConcept {id: $id})
            SET c.alias_keys = [k IN coalesce(c.alias_keys, []) WHERE NOT k IN $new] + $new,
                c.aliases = [a IN coalesce(c.aliases, []) WHERE NOT a IN $aliases] + $aliases,
                c.definition = CASE WHEN coalesce(c.definition, '') = '' THEN $definition ELSE c.definition END,
                c.updated_at = $now
            """,
            id=rec["id"],
            new=[k for k in keys if k],
            aliases=concept["aliases"],
            definition=concept["definition"],
            now=_now(),
        )
        return rec["id"]
    cid = str(uuid.uuid4())
    tx.run(
        """
        CREATE (c:MapConcept {id: $id, key: $key, name: $name, kind: $kind,
                              definition: $definition, aliases: $aliases,
                              alias_keys: $alias_keys, created_at: $now, updated_at: $now})
        """,
        id=cid,
        key=concept["key"],
        name=concept["name"],
        kind=concept["kind"],
        definition=concept["definition"],
        aliases=concept["aliases"],
        alias_keys=concept["alias_keys"],
        now=_now(),
    )
    return cid


def save_paper_concepts(driver: Driver, paper_id: str, extraction: dict) -> int:
    """Replace the paper's concepts and relations with *extraction*; return the concept count."""

    def work(tx):
        tx.run("MATCH (:Paper {id: $pid})-[d:DISCUSSES]->(:MapConcept) DELETE d", pid=paper_id)
        tx.run("MATCH (:MapConcept)-[l:CONCEPT_LINK {paper_id: $pid}]->(:MapConcept) DELETE l", pid=paper_id)
        ids: dict[str, str] = {}
        for c in extraction["concepts"]:
            cid = _resolve_concept(tx, c)
            ids[c["key"]] = cid
            tx.run(
                """
                MATCH (p:Paper {id: $pid}), (c:MapConcept {id: $cid})
                MERGE (p)-[d:DISCUSSES]->(c)
                SET d.role = $role, d.in_paper = $in_paper
                """,
                pid=paper_id, cid=cid, role=c["role"], in_paper=c["in_paper"],
            )
        for r in extraction["relations"]:
            src, tgt = ids.get(r["source"]), ids.get(r["target"])
            if not src or not tgt or src == tgt:
                continue
            tx.run(
                """
                MATCH (a:MapConcept {id: $src}), (b:MapConcept {id: $tgt})
                MERGE (a)-[l:CONCEPT_LINK {paper_id: $pid, type: $type}]->(b)
                SET l.evidence = $evidence
                """,
                src=src, tgt=tgt, pid=paper_id, type=r["type"], evidence=r["evidence"],
            )
        tx.run(
            "MATCH (p:Paper {id: $pid}) SET p.concept_map_at = $now REMOVE p.concept_map_error, p.concept_map_attempts",
            pid=paper_id, now=_now(),
        )
        tx.run("MATCH (c:MapConcept) WHERE NOT (c)<-[:DISCUSSES]-() DETACH DELETE c")
        return len(ids)

    with driver.session() as session:
        return session.execute_write(work)


def set_mapping_error(driver: Driver, paper_id: str, error: str) -> None:
    with driver.session() as session:
        session.run(
            """
            MATCH (p:Paper {id: $pid})
            SET p.concept_map_error = $err,
                p.concept_map_attempts = coalesce(p.concept_map_attempts, 0) + 1
            """,
            pid=paper_id, err=error[:500],
        )


def get_project_map(driver: Driver, project_id: str) -> dict:
    """Papers, concepts and every edge between them for one project."""
    with driver.session() as session:
        papers = [dict(r) for r in session.run(
            """
            MATCH (p:Paper)-[:IN_PROJECT]->(:Project {id: $pid})
            OPTIONAL MATCH (p)-[:AUTHORED_BY]->(a:Person)
            WITH p, collect({id: a.id, name: a.name}) AS authors
            RETURN p.id AS id, p.title AS title, p.year AS year, p.venue AS venue,
                   p.citation_count AS citation_count, p.reading_status AS reading_status,
                   p.document_type AS document_type, p.concept_map_at AS mapped_at,
                   p.concept_map_error AS map_error,
                   [x IN authors WHERE x.id IS NOT NULL] AS authors
            """,
            pid=project_id,
        )]
        discusses = [dict(r) for r in session.run(
            """
            MATCH (p:Paper)-[:IN_PROJECT]->(:Project {id: $pid})
            MATCH (p)-[d:DISCUSSES]->(c:MapConcept)
            RETURN p.id AS paper_id, c.id AS concept_id, d.role AS role, d.in_paper AS in_paper
            """,
            pid=project_id,
        )]
        concept_ids = sorted({d["concept_id"] for d in discusses})
        concepts = [dict(r) for r in session.run(
            """
            MATCH (c:MapConcept) WHERE c.id IN $ids
            RETURN c.id AS id, c.name AS name, c.kind AS kind, c.definition AS definition,
                   coalesce(c.aliases, []) AS aliases
            """,
            ids=concept_ids,
        )]
        links = [dict(r) for r in session.run(
            """
            MATCH (a:MapConcept)-[l:CONCEPT_LINK]->(b:MapConcept)
            WHERE a.id IN $ids AND b.id IN $ids
              AND EXISTS { MATCH (:Paper {id: l.paper_id})-[:IN_PROJECT]->(:Project {id: $pid}) }
            RETURN a.id AS source, b.id AS target, l.type AS type,
                   collect({paper_id: l.paper_id, evidence: l.evidence}) AS support
            """,
            ids=concept_ids,
            pid=project_id,
        )]
        citations = [dict(r) for r in session.run(
            """
            MATCH (a:Paper)-[:IN_PROJECT]->(:Project {id: $pid})
            MATCH (a)-[:CITES]->(b:Paper)-[:IN_PROJECT]->(:Project {id: $pid})
            WHERE a <> b
            RETURN DISTINCT a.id AS source, b.id AS target
            """,
            pid=project_id,
        )]
    return {
        "papers": papers,
        "concepts": concepts,
        "discusses": discusses,
        "concept_links": links,
        "citations": citations,
    }
