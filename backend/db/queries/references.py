import uuid
from datetime import datetime, timezone
from neo4j import Driver


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _find_existing_reference(session, doi: str | None, title: str) -> dict | None:
    """The paper a reference points to, if the library already has it.

    Looks up every spelling of the DOI / arXiv id first (``arXiv:X`` and
    ``10.48550/arXiv.X`` are one paper), then the title ignoring case and
    punctuation. A title match must not carry a different DOI. PDF-backed
    papers win over stubs.
    """
    from services.duplicate_scan import _dois_compatible, doi_variants, normalize_title

    if doi:
        rec = session.run(
            """
            MATCH (ref:Paper) WHERE ref.doi IN $variants
            RETURN ref ORDER BY CASE WHEN ref.drive_file_id IS NULL THEN 1 ELSE 0 END LIMIT 1
            """,
            variants=doi_variants(doi),
        ).single()
        if rec:
            return dict(rec["ref"])
    key = normalize_title(title)
    if len(key.split()) < 3:
        return None
    # Cheap pre-filter on the first word, exact comparison in Python.
    first = key.split()[0]
    rows = session.run(
        """
        MATCH (ref:Paper) WHERE toLower(ref.title) CONTAINS $first
        RETURN ref ORDER BY CASE WHEN ref.drive_file_id IS NULL THEN 1 ELSE 0 END
        """,
        first=first,
    )
    for r in rows:
        cand = dict(r["ref"])
        if normalize_title(cand.get("title")) == key and _dois_compatible(cand, {"doi": doi}):
            return cand
    return None


def create_or_link_reference(driver: Driver, citing_paper_id: str, ref: dict) -> tuple[dict, bool]:
    """
    Link the citing paper to the reference with CITES, creating a stub Paper
    only when no existing paper matches (see _find_existing_reference).
    Returns (reference paper node, whether it was created).
    """
    doi = ref.get("doi") or ref.get("arxiv_id")
    title = (ref.get("title") or "").strip()

    with driver.session() as session:
        existing = _find_existing_reference(session, doi, title)
        if existing:
            record = session.run(
                """
                MATCH (ref:Paper {id: $ref_id}), (citing:Paper {id: $citing_id})
                WHERE ref <> citing
                SET ref.title = CASE WHEN coalesce(ref.title, '') = '' THEN $title ELSE ref.title END,
                    ref.year = coalesce(ref.year, $year),
                    ref.doi = coalesce(ref.doi, $doi)
                MERGE (citing)-[:CITES]->(ref)
                RETURN ref
                """,
                ref_id=existing["id"],
                citing_id=citing_paper_id,
                title=title,
                year=ref.get("year"),
                doi=doi,
            ).single()
            return (dict(record["ref"]) if record else {}), False
        if not doi and not title:
            return {}, False
        now = _now()
        record = session.run(
            """
            MATCH (citing:Paper {id: $citing_id})
            CREATE (ref:Paper {id: $id, title: $title, year: $year, created_at: $now, updated_at: $now})
            SET ref.doi = $doi
            MERGE (citing)-[:CITES]->(ref)
            RETURN ref
            """,
            citing_id=citing_paper_id,
            id=str(uuid.uuid4()),
            title=title,
            year=ref.get("year"),
            doi=doi,
            now=now,
        ).single()
        return (dict(record["ref"]) if record else {}), True


def get_references(driver: Driver, paper_id: str) -> list[dict]:
    """Return papers that this paper cites (outgoing CITES)."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper {id: $id})-[:CITES]->(ref:Paper)
            RETURN ref ORDER BY ref.year DESC
            """,
            id=paper_id,
        )
        return [dict(r["ref"]) for r in result]


def get_cited_by(driver: Driver, paper_id: str) -> list[dict]:
    """Return papers that cite this paper (incoming CITES)."""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (citing:Paper)-[:CITES]->(p:Paper {id: $id})
            RETURN citing ORDER BY citing.year DESC
            """,
            id=paper_id,
        )
        return [dict(r["citing"]) for r in result]
