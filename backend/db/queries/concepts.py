"""Concept nodes: (Paper)-[:HAS_CONCEPT]->(Concept).

A Concept is one idea on one PDF page that has (or can get) an interactive
visualisation. The generated spec is stored as a JSON string in ``spec_json``.
"""
import json
import uuid
from datetime import datetime, timezone

from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _out(node) -> dict:
    d = dict(node)
    raw = d.pop("spec_json", None)
    d["spec"] = json.loads(raw) if raw else None
    d.setdefault("spec_error", None)  # Neo4j stores no null properties
    return d


def list_concepts(driver: Driver, paper_id: str) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (:Paper {id: $pid})-[:HAS_CONCEPT]->(c:Concept)
            RETURN c ORDER BY c.page ASC, c.position ASC
            """,
            pid=paper_id,
        )
        return [_out(record["c"]) for record in result]


def get_concept(driver: Driver, paper_id: str, concept_id: str) -> dict | None:
    with driver.session() as session:
        record = session.run(
            "MATCH (:Paper {id: $pid})-[:HAS_CONCEPT]->(c:Concept {id: $cid}) RETURN c",
            pid=paper_id,
            cid=concept_id,
        ).single()
        return _out(record["c"]) if record else None


def replace_concepts(driver: Driver, paper_id: str, concepts: list[dict]) -> list[dict]:
    """Delete the paper's concepts and store *concepts* in their place."""
    now = _now()
    rows = [
        {
            "id": str(uuid.uuid4()),
            "position": i,
            "page": c["page"],
            "label": c["label"],
            "type": c["type"],
            "anchor": c["anchor"],
            "anchor_found": c["anchor_found"],
            "context": c["context"],
        }
        for i, c in enumerate(concepts)
    ]
    with driver.session() as session:
        session.execute_write(_replace_tx, paper_id, rows, now)
    return list_concepts(driver, paper_id)


def _replace_tx(tx, paper_id: str, rows: list[dict], now: str) -> None:
    tx.run(
        """
        MATCH (:Paper {id: $pid})-[:HAS_CONCEPT]->(c:Concept)
        DETACH DELETE c
        """,
        pid=paper_id,
    )
    tx.run(
        """
        MATCH (p:Paper {id: $pid})
        UNWIND $rows AS row
        CREATE (c:Concept)
        SET c = row, c.created_at = $now, c.updated_at = $now
        CREATE (p)-[:HAS_CONCEPT]->(c)
        """,
        pid=paper_id,
        rows=rows,
        now=now,
    )


def set_concept_spec(
    driver: Driver,
    paper_id: str,
    concept_id: str,
    spec: dict | None,
    error: str | None = None,
) -> dict | None:
    """Store a generated spec (or clear it) and the last generation error."""
    with driver.session() as session:
        record = session.run(
            """
            MATCH (:Paper {id: $pid})-[:HAS_CONCEPT]->(c:Concept {id: $cid})
            SET c.spec_json = $spec_json, c.spec_error = $error, c.updated_at = $now
            RETURN c
            """,
            pid=paper_id,
            cid=concept_id,
            spec_json=json.dumps(spec) if spec is not None else None,
            error=error,
            now=_now(),
        ).single()
        return _out(record["c"]) if record else None


def delete_concepts(driver: Driver, paper_id: str) -> int:
    with driver.session() as session:
        record = session.run(
            """
            MATCH (:Paper {id: $pid})-[:HAS_CONCEPT]->(c:Concept)
            DETACH DELETE c
            RETURN count(c) AS deleted
            """,
            pid=paper_id,
        ).single()
        return record["deleted"]
