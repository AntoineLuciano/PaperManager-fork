"""Delete a paper and everything that only exists for it.

``deletion_preview`` counts what would go; ``delete_paper_completely`` does it. Used by
``DELETE /papers/{id}`` and the MCP ``delete_paper`` tool, so both remove the same things:

- figure images (Drive trash) and Figure nodes,
- the paper's Note, Claims, Tables, Chapters and Annotations (PDF highlights),
- the PDF itself (Drive trash, recoverable for 30 days),
- the Paper node with all its relationships (authors, tags, topics, projects, citations).

People, tags, topics and projects are shared nodes and stay.
"""
from __future__ import annotations

import logging

from neo4j import Driver

from db.queries.figures import delete_figures_for_paper, list_figures
from db.queries.papers import delete_paper, get_paper

log = logging.getLogger(__name__)

OWNED = "HAS_NOTE|HAS_CLAIM|HAS_TABLE|HAS_CHAPTER|HAS_ANNOTATION"

_PREVIEW = f"""
MATCH (p:Paper {{id: $id}})
OPTIONAL MATCH (p)-[:{OWNED}|HAS_FIGURE]->(c)
WITH p, [l IN collect(labels(c)[0]) WHERE l IS NOT NULL] AS owned
OPTIONAL MATCH (p)-[r]-()
RETURN owned, collect(DISTINCT type(r)) AS rel_types, count(DISTINCT r) AS rels
"""


def deletion_preview(driver: Driver, paper_id: str) -> dict | None:
    """What deleting ``paper_id`` would remove, or None if there is no such paper."""
    paper = get_paper(driver, paper_id)
    if not paper:
        return None
    with driver.session() as session:
        rec = session.run(_PREVIEW, id=paper_id).single()
    owned: dict[str, int] = {}
    for label in rec["owned"]:
        owned[label] = owned.get(label, 0) + 1
    return {
        "id": paper_id,
        "title": paper.get("title"),
        "has_pdf": bool(paper.get("drive_file_id")),
        "text_chars": len(paper.get("raw_text") or ""),
        "owned_nodes": owned,                     # e.g. {"Note": 1, "Annotation": 4, "Claim": 9}
        "relationships": rec["rels"],
        "relationship_types": sorted(t for t in rec["rel_types"] if t),
    }


def delete_paper_completely(driver: Driver, paper_id: str) -> bool:
    """Delete the paper and its owned nodes; Drive files go to the trash (best-effort)."""
    from services.drive import delete_file

    paper = get_paper(driver, paper_id)
    if not paper:
        return False

    figs = list_figures(driver, paper_id)
    for fig in figs:
        if fig.get("drive_file_id"):
            try:
                delete_file(fig["drive_file_id"])
            except Exception as exc:
                log.warning("Figure Drive delete failed (non-fatal) | %s", exc)
    if figs:
        delete_figures_for_paper(driver, paper_id)
        log.info("Figures deleted | count=%d | paper_id=%s", len(figs), paper_id)

    with driver.session() as session:
        session.run(f"MATCH (p:Paper {{id: $id}})-[:{OWNED}]->(c) DETACH DELETE c", id=paper_id)

    if paper.get("drive_file_id"):
        try:
            delete_file(paper["drive_file_id"])
            log.info("Drive file deleted | file_id=%s", paper["drive_file_id"])
        except Exception as exc:
            log.warning("Drive delete failed (non-fatal) | %s", exc)

    delete_paper(driver, paper_id)
    log.info("Paper deleted | id=%s | title=%.60s", paper_id, paper.get("title"))
    return True
