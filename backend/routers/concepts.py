"""Interactive concepts on a paper's PDF: detect them, generate visualisations."""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.concepts import (
    delete_concepts,
    get_concept,
    list_concepts,
    replace_concepts,
    set_concept_spec,
)
from db.queries.papers import get_paper
from services.auth import get_current_user
from services.concepts import (
    MAX_PAGES,
    ConceptsError,
    concepts_backend,
    detect_concepts,
    generate_spec,
    page_texts_from_pdf,
)
from services.drive import download_pdf

log = logging.getLogger(__name__)
router = APIRouter(tags=["concepts"], dependencies=[Depends(get_current_user)])

# Papers whose detection is running, so a double click doesn't start a second
# full pass on the same subscription.
_detecting: set[str] = set()
_detecting_lock = threading.Lock()


class ConceptsOut(BaseModel):
    concepts: list[dict]
    backend: str


class DetectOut(ConceptsOut):
    pages_total: int
    pages_scanned: int


class RepairBody(BaseModel):
    error: str


def _paper_or_404(paper_id: str) -> dict:
    paper = get_paper(get_driver(), paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper


def _concept_or_404(paper_id: str, concept_id: str) -> dict:
    concept = get_concept(get_driver(), paper_id, concept_id)
    if not concept:
        raise HTTPException(status_code=404, detail="Concept not found")
    return concept


@router.get("/papers/{paper_id}/concepts", response_model=ConceptsOut)
def get_paper_concepts(paper_id: str):
    return ConceptsOut(concepts=list_concepts(get_driver(), paper_id), backend=concepts_backend())


@router.post("/papers/{paper_id}/concepts/detect", response_model=DetectOut)
def detect_paper_concepts(paper_id: str):
    """Scan the PDF page by page and replace the paper's concepts."""
    paper = _paper_or_404(paper_id)
    if not paper.get("drive_file_id"):
        raise HTTPException(status_code=422, detail="No PDF stored for this paper")
    with _detecting_lock:
        if paper_id in _detecting:
            raise HTTPException(status_code=409, detail="Concept detection is already running")
        _detecting.add(paper_id)
    try:
        try:
            pages = page_texts_from_pdf(download_pdf(paper["drive_file_id"]))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not read the PDF: {exc}")
        if not any(pages):
            raise HTTPException(status_code=422, detail="The PDF has no extractable text")
        try:
            found = detect_concepts(pages, paper.get("title", ""))
        except ConceptsError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        stored = replace_concepts(get_driver(), paper_id, found)
        return DetectOut(
            concepts=stored,
            backend=concepts_backend(),
            pages_total=len(pages),
            pages_scanned=min(len(pages), MAX_PAGES),
        )
    finally:
        with _detecting_lock:
            _detecting.discard(paper_id)


@router.post("/papers/{paper_id}/concepts/{concept_id}/viz")
def generate_concept_viz(paper_id: str, concept_id: str, force: bool = False):
    """Return the concept's visualisation, generating it on first request."""
    paper = _paper_or_404(paper_id)
    concept = _concept_or_404(paper_id, concept_id)
    if concept.get("spec") and not force:
        return concept
    try:
        spec = generate_spec(concept, paper.get("title", ""))
    except ConceptsError as exc:
        set_concept_spec(get_driver(), paper_id, concept_id, concept.get("spec"), str(exc))
        raise HTTPException(status_code=502, detail=str(exc))
    return set_concept_spec(get_driver(), paper_id, concept_id, spec)


@router.post("/papers/{paper_id}/concepts/{concept_id}/repair")
def repair_concept_viz(paper_id: str, concept_id: str, body: RepairBody):
    """Regenerate a visualisation that failed to render, given the error."""
    paper = _paper_or_404(paper_id)
    concept = _concept_or_404(paper_id, concept_id)
    if not concept.get("spec"):
        raise HTTPException(status_code=409, detail="Nothing to repair: no visualisation yet")
    previous = {"spec": concept["spec"], "error": body.error}
    try:
        spec = generate_spec(concept, paper.get("title", ""), previous)
    except ConceptsError as exc:
        set_concept_spec(get_driver(), paper_id, concept_id, concept["spec"], str(exc))
        raise HTTPException(status_code=502, detail=str(exc))
    return set_concept_spec(get_driver(), paper_id, concept_id, spec)


@router.delete("/papers/{paper_id}/concepts")
def clear_paper_concepts(paper_id: str):
    return {"deleted": delete_concepts(get_driver(), paper_id)}
