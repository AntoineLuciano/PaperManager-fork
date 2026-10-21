"""Merge Manager — find duplicate papers and merge them.

POST /merge/scan       candidate pairs (keeper vs each duplicate), the shape MergeManager.tsx reads
GET  /merge/groups     the full duplicate groups, classified, plus suspected wrong DOIs
POST /merge/execute    merge one or more papers into a keeper (``dry_run`` to preview)

Detection rules: services/duplicate_scan.py. What a merge moves: services/paper_merge.py.
Detection is deterministic (DOI and title rules), so the former ``model`` parameter of /scan is
accepted for compatibility and ignored.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator

from db.connection import get_driver
from services.duplicate_scan import CLASSES, SCAN_QUERY, scan, title_similarity, wrong_doi_suspects
from services.auth import require_admin
from services.paper_merge import merge_papers

log = logging.getLogger(__name__)

router = APIRouter(prefix="/merge", tags=["merge"], dependencies=[Depends(require_admin)])


# ── Schemas ────────────────────────────────────────────────────────────────

class DuplicatePair(BaseModel):
    paper_a: dict          # the keeper
    paper_b: dict          # the duplicate
    similarity: float      # title similarity 0–1
    reason: str            # which rule linked them, and the group class


class ScanResult(BaseModel):
    pairs: list[DuplicatePair]
    total_papers: int


class MergeExecuteRequest(BaseModel):
    keep_id: str
    remove_id: str | None = None
    remove_ids: list[str] | None = None
    dry_run: bool = False
    trash_drive_files: bool = True

    @model_validator(mode="after")
    def _one_target(self):
        if not self.remove_id and not self.remove_ids:
            raise ValueError("give remove_id or remove_ids")
        return self

    @property
    def targets(self) -> list[str]:
        return [*(self.remove_ids or []), *([self.remove_id] if self.remove_id else [])]


class MergeExecuteResult(BaseModel):
    kept_id: str
    removed_id: str | None
    relationships_moved: int
    report: dict


# ── Helpers ────────────────────────────────────────────────────────────────

def _slim(p: dict) -> dict:
    """The fields the frontend shows, plus what decides which one is kept."""
    keys = ("id", "title", "year", "doi", "drive_file_id", "text_chars", "notes", "annotations",
            "projects", "cited_by", "cites")
    return {k: p.get(k) for k in keys}


def load_papers() -> list[dict]:
    with get_driver().session() as session:
        return session.run(SCAN_QUERY).data()


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/scan", response_model=ScanResult)
def scan_duplicates(model: str = "none"):
    """Candidate duplicate pairs: each group's keeper against each of its duplicates."""
    result = scan(load_papers())
    pairs = [
        DuplicatePair(
            paper_a=_slim(g.keep), paper_b=_slim(p),
            similarity=round(title_similarity(g.keep["title"], p["title"]), 3),
            reason=f"{', '.join(g.reasons)} · {g.klass.replace('_', ' ')}",
        )
        for g in result.groups for p in g.remove
    ]
    log.info("Merge scan: %d papers, %d groups, %d pairs", result.total, len(result.groups), len(pairs))
    return ScanResult(pairs=pairs, total_papers=result.total)


@router.get("/groups")
def duplicate_groups(classes: str | None = Query(None, description=f"comma-separated subset of {CLASSES}")):
    wanted = set((classes or ",".join(CLASSES)).split(","))
    unknown = wanted - set(CLASSES)
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown classes: {sorted(unknown)}")
    result = scan(load_papers())
    return {
        "total_papers": result.total,
        "groups": [
            {"class": g.klass, "reasons": g.reasons, "keep": _slim(g.keep), "remove": [_slim(p) for p in g.remove]}
            for g in result.groups if g.klass in wanted
        ],
        "wrong_doi_suspects": [
            {"paper": _slim(s), "doi_belongs_to": _slim(o)} for s, o in wrong_doi_suspects(result)
        ],
    }


@router.post("/execute", response_model=MergeExecuteResult)
def execute_merge(body: MergeExecuteRequest):
    """Merge ``remove_id``/``remove_ids`` into ``keep_id``. Nothing is lost; see paper_merge.py."""
    if body.keep_id in body.targets:
        raise HTTPException(status_code=400, detail="keep_id and remove_id must differ")
    try:
        report = merge_papers(get_driver(), body.keep_id, body.targets,
                              dry_run=body.dry_run, trash_drive_files=body.trash_drive_files)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return MergeExecuteResult(
        kept_id=body.keep_id,
        removed_id=body.remove_id or (body.targets[0] if len(body.targets) == 1 else None),
        relationships_moved=report.relationships_moved,
        report=report.as_dict(),
    )
