"""Merge duplicate Paper nodes into one, without losing anything attached to them.

``merge_papers(driver, keep_id, remove_ids, dry_run=...)`` runs every step for one group in a
single transaction. With ``dry_run=True`` the transaction is rolled back, so the report shows
exactly what an apply would do. Drive files are only touched after a successful commit.

Per removed paper:

1. **Properties** — every property the keeper lacks (or has empty) is copied over: DOI, year,
   abstract, summary, venue, text and the PDF (``drive_file_id``) itself if the keeper has none.
   A keeper title that is a truncated prefix of the other title is replaced by the full one.
   ``created_at`` becomes the earlier of the two; rating is the maximum, bookmarked is OR-ed.
2. **Note** — moved if the keeper has none; otherwise its text is appended to the keeper's note
   under a dated separator and its @/# mentions are carried over.
3. **PDF-derived children** (claims, figures, tables, chapters) — moved when the keeper adopts
   the removed paper's PDF or has none of that kind; otherwise deleted with the duplicate.
4. **Every other relationship, in both directions** — moved to the keeper, discovered at run
   time rather than listed, so a relationship type added later is never silently dropped.
   Existing keeper relationships are not doubled, and links between the two papers are dropped.
5. The duplicate node is deleted. After commit, its PDF and the images of deleted figures are
   moved to the Drive trash (recoverable for 30 days) unless the keeper adopted them.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neo4j import Driver

log = logging.getLogger(__name__)

OWNED_CHILDREN = {"HAS_CLAIM": "Claim", "HAS_FIGURE": "Figure", "HAS_TABLE": "Table", "HAS_CHAPTER": "Chapter"}
NEVER_COPY = {"id", "created_at", "updated_at", "title"}
_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass
class MergeReport:
    keep_id: str
    removed: list[str] = field(default_factory=list)
    moved: dict[str, int] = field(default_factory=dict)        # "OUT:TAGGED" -> n
    properties_filled: dict[str, list[str]] = field(default_factory=dict)
    title_replaced: str | None = None
    notes_merged: int = 0
    children_deleted: dict[str, int] = field(default_factory=dict)
    drive_trash: list[str] = field(default_factory=list)
    drive_trashed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = True

    @property
    def relationships_moved(self) -> int:
        return sum(self.moved.values())

    def as_dict(self) -> dict:
        return {
            "keep_id": self.keep_id, "removed": self.removed, "dry_run": self.dry_run,
            "relationships_moved": self.relationships_moved, "moved": self.moved,
            "properties_filled": self.properties_filled, "title_replaced": self.title_replaced,
            "notes_merged": self.notes_merged, "children_deleted": self.children_deleted,
            "drive_trash": self.drive_trash, "drive_trashed": self.drive_trashed,
            "warnings": self.warnings,
        }


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v)


def _norm(t: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())).strip()


def _bump(report: MergeReport, key: str, n: int) -> None:
    if n:
        report.moved[key] = report.moved.get(key, 0) + n


def _merge_one(tx, keep_id: str, remove_id: str, report: MergeReport) -> None:
    rec = tx.run("MATCH (k:Paper {id: $k}), (r:Paper {id: $r}) RETURN properties(k) AS k, properties(r) AS r",
                 k=keep_id, r=remove_id).single()
    if rec is None:
        raise LookupError(f"paper not found: keep={keep_id} or remove={remove_id}")
    keep, rem = dict(rec["k"]), dict(rec["r"])

    # 1. properties
    adopt_pdf = _empty(keep.get("drive_file_id")) and not _empty(rem.get("drive_file_id"))
    fill = {k: v for k, v in rem.items() if k not in NEVER_COPY and not _empty(v) and _empty(keep.get(k))}
    if adopt_pdf:   # text, summary etc. belong to that PDF; take them together
        for k in ("raw_text", "summary", "metadata_source"):
            if not _empty(rem.get(k)):
                fill[k] = rem[k]
    kt, rt = _norm(keep.get("title")), _norm(rem.get("title"))
    if kt and rt.startswith(kt) and len(rt) > len(kt) + 3:
        fill["title"] = rem["title"]
        report.title_replaced = rem["title"]
    if rem.get("created_at") and keep.get("created_at") and rem["created_at"] < keep["created_at"]:
        fill["created_at"] = rem["created_at"]
    if rem.get("rating") and (keep.get("rating") or 0) < rem["rating"]:
        fill["rating"] = rem["rating"]
    if rem.get("bookmarked") and not keep.get("bookmarked"):
        fill["bookmarked"] = True
    if fill:
        tx.run("MATCH (k:Paper {id: $k}) SET k += $props", k=keep_id, props=fill)
        report.properties_filled[remove_id] = sorted(fill)
    if not _empty(rem.get("drive_file_id")) and not adopt_pdf and rem["drive_file_id"] != keep.get("drive_file_id"):
        report.drive_trash.append(rem["drive_file_id"])

    # 2. note
    notes = tx.run("""
        MATCH (r:Paper {id: $r})-[:HAS_NOTE]->(rn:Note)
        OPTIONAL MATCH (k:Paper {id: $k})-[:HAS_NOTE]->(kn:Note)
        RETURN rn.id AS rn, rn.content AS content, kn.id AS kn
    """, r=remove_id, k=keep_id).data()
    for n in notes:
        if n["kn"] is None:
            tx.run("""
                MATCH (r:Paper {id: $r})-[rel:HAS_NOTE]->(rn:Note {id: $rn}), (k:Paper {id: $k})
                CREATE (k)-[:HAS_NOTE]->(rn) DELETE rel
            """, r=remove_id, rn=n["rn"], k=keep_id)
            _bump(report, "OUT:HAS_NOTE", 1)
        else:
            sep = (f"\n\n---\n*Merged from duplicate entry “{rem.get('title', '')}” ({remove_id}) on "
                   f"{datetime.now(timezone.utc):%Y-%m-%d}.*\n\n")
            tx.run("""
                MATCH (kn:Note {id: $kn}), (rn:Note {id: $rn})
                SET kn.content = coalesce(kn.content, '') + $sep + coalesce(rn.content, ''),
                    kn.updated_at = $now
                WITH kn, rn
                OPTIONAL MATCH (rn)-[m:MENTIONS]->(x)
                FOREACH (_ IN CASE WHEN x IS NULL THEN [] ELSE [1] END | MERGE (kn)-[:MENTIONS]->(x))
                WITH DISTINCT rn
                DETACH DELETE rn
            """, kn=n["kn"], rn=n["rn"], sep=sep, now=datetime.now(timezone.utc).isoformat())
            report.notes_merged += 1

    # 3. PDF-derived children
    for rtype, label in OWNED_CHILDREN.items():
        have = tx.run(f"MATCH (:Paper {{id: $k}})-[:{rtype}]->(c) RETURN count(c) AS n", k=keep_id).single()["n"]
        if adopt_pdf or have == 0:
            n = tx.run(f"""
                MATCH (r:Paper {{id: $r}})-[rel:{rtype}]->(c:{label}), (k:Paper {{id: $k}})
                CREATE (k)-[:{rtype}]->(c) DELETE rel RETURN count(c) AS n
            """, r=remove_id, k=keep_id).single()["n"]
            _bump(report, f"OUT:{rtype}", n)
        else:
            rows = tx.run(f"""
                MATCH (:Paper {{id: $r}})-[:{rtype}]->(c:{label})
                WITH c, c.drive_file_id AS f DETACH DELETE c RETURN f
            """, r=remove_id).data()
            if rows:
                report.children_deleted[label] = report.children_deleted.get(label, 0) + len(rows)
                report.drive_trash.extend(r["f"] for r in rows if r["f"])

    # 4. every remaining relationship, both directions
    if not adopt_pdf and not _empty(rem.get("drive_file_id")):
        n_ann = tx.run("MATCH (:Paper {id: $r})-[:HAS_ANNOTATION]->(a) RETURN count(a) AS n", r=remove_id).single()["n"]
        if n_ann and keep.get("raw_text") and rem.get("raw_text") and len(keep["raw_text"]) != len(rem["raw_text"]):
            report.warnings.append(f"{n_ann} highlights moved from a different PDF ({remove_id}); positions may not match")
    for direction in ("OUT", "IN"):
        any_pat = "(r:Paper {id: $r})-[rel]->(x)" if direction == "OUT" else "(x)-[rel]->(r:Paper {id: $r})"
        types = [t["t"] for t in tx.run(f"MATCH {any_pat} RETURN DISTINCT type(rel) AS t", r=remove_id).data()]
        for t in types:
            if not _TYPE_RE.match(t):
                raise ValueError(f"unexpected relationship type {t!r}")
            pat = any_pat.replace("[rel]", f"[rel:{t}]")
            new = "(k)-[nr:%s]->(x)" % t if direction == "OUT" else "(x)-[nr:%s]->(k)" % t
            n = tx.run(f"""
                MATCH {pat}, (k:Paper {{id: $k}})
                WHERE x.id IS NULL OR (x.id <> $k AND x.id <> $r)
                MERGE {new}
                ON CREATE SET nr = properties(rel)
                DELETE rel
                RETURN count(rel) AS n
            """, r=remove_id, k=keep_id).single()["n"]
            _bump(report, f"{direction}:{t}", n)

    # 5. delete the duplicate
    tx.run("MATCH (r:Paper {id: $r}) DETACH DELETE r", r=remove_id)
    report.removed.append(remove_id)


def merge_papers(driver: Driver, keep_id: str, remove_ids: list[str], *, dry_run: bool = True,
                 trash_drive_files: bool = True) -> MergeReport:
    remove_ids = [r for r in dict.fromkeys(remove_ids) if r and r != keep_id]
    report = MergeReport(keep_id=keep_id, dry_run=dry_run)
    with driver.session() as session:
        tx = session.begin_transaction()
        try:
            for rid in remove_ids:
                _merge_one(tx, keep_id, rid, report)
            tx.run("MATCH (k:Paper {id: $k}) SET k.updated_at = $now", k=keep_id,
                   now=datetime.now(timezone.utc).isoformat())
            if dry_run:
                tx.rollback()
            else:
                tx.commit()
        except Exception:
            if not tx.closed():
                tx.rollback()
            raise
        finally:
            if not tx.closed():
                tx.close()

    if not dry_run and trash_drive_files and report.drive_trash:
        from services.drive import delete_file
        for fid in dict.fromkeys(report.drive_trash):
            try:
                delete_file(fid)
                report.drive_trashed.append(fid)
            except Exception as exc:  # Drive is best-effort: the graph is already consistent
                report.warnings.append(f"Drive trash failed for {fid}: {exc}")
    log.info("Merge %s | keep=%s removed=%d moved=%d", "dry-run" if dry_run else "applied",
             keep_id, len(report.removed), report.relationships_moved)
    return report
