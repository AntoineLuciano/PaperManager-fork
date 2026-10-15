"""Interactive concepts on a paper's PDF: detect them, generate visualisations."""
from __future__ import annotations

import contextvars
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

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

# "Generate all": one background job per paper, keyed by paper id. A newer job
# (after a re-scan) supersedes an older one, which then stops at its next item.
# _inflight holds the concept ids a model call is running for, so the job and an
# on-demand /viz request never generate the same concept twice.
GENERATE_CONCURRENCY = 3
INFLIGHT_WAIT_S = 300
_jobs: dict[str, dict] = {}
_inflight: set[str] = set()
_jobs_lock = threading.Lock()


class GenerationOut(BaseModel):
    total: int
    done: int
    failed: int
    running: bool


class ConceptsOut(BaseModel):
    concepts: list[dict]
    backend: str
    generation: GenerationOut | None = None


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


def _claim(concept_id: str) -> bool:
    """Mark a concept as being generated; False if something else already is."""
    with _jobs_lock:
        if concept_id in _inflight:
            return False
        _inflight.add(concept_id)
        return True


def _release(concept_id: str) -> None:
    with _jobs_lock:
        _inflight.discard(concept_id)


def _generation_status(paper_id: str) -> GenerationOut | None:
    with _jobs_lock:
        job = _jobs.get(paper_id)
        if not job:
            return None
        return GenerationOut(total=job["total"], done=job["done"], failed=job["failed"], running=job["running"])


def _generate_one(paper_id: str, concept_id: str, title: str, job: dict) -> None:
    def current() -> bool:
        with _jobs_lock:
            return _jobs.get(paper_id) is job

    ok = True
    if current() and _claim(concept_id):
        try:
            concept = get_concept(get_driver(), paper_id, concept_id)
            if concept and not concept.get("spec"):
                try:
                    spec = generate_spec(concept, title)
                    set_concept_spec(get_driver(), paper_id, concept_id, spec)
                except ConceptsError as exc:
                    ok = False
                    set_concept_spec(get_driver(), paper_id, concept_id, None, str(exc))
        except Exception:  # noqa: BLE001 — one concept must not stop the job
            log.exception("Generating concept %s failed", concept_id)
            ok = False
        finally:
            _release(concept_id)
    with _jobs_lock:
        job["done"] += 1
        job["failed"] += 0 if ok else 1


def _run_generation(paper_id: str, concept_ids: list[str], title: str, job: dict) -> None:
    try:
        with ThreadPoolExecutor(max_workers=GENERATE_CONCURRENCY) as pool:
            # Each call runs in a copy of the request context: the request user
            # decides whether Claude Code may be used.
            futures = [
                pool.submit(contextvars.copy_context().run, _generate_one, paper_id, cid, title, job)
                for cid in concept_ids
            ]
            for f in futures:
                f.result()
    finally:
        with _jobs_lock:
            job["running"] = False


def start_generation(paper_id: str, concepts: list[dict], title: str) -> GenerationOut | None:
    """Generate every concept without a spec in a background thread.

    Returns the job's status, or that of the job already running for this paper
    if it covers the same concepts.
    """
    missing = [c["id"] for c in concepts if not c.get("spec")]
    with _jobs_lock:
        running = _jobs.get(paper_id)
        if running and running["running"] and running["ids"] == missing:
            pass
        elif not missing:
            _jobs.pop(paper_id, None)
            return None
        else:
            job = {"id": str(uuid.uuid4()), "ids": missing, "total": len(missing),
                   "done": 0, "failed": 0, "running": True}
            _jobs[paper_id] = job
            ctx = contextvars.copy_context()
            threading.Thread(
                target=ctx.run, args=(_run_generation, paper_id, missing, title, job),
                name=f"concepts-generate-{paper_id}", daemon=True,
            ).start()
    return _generation_status(paper_id)


@router.get("/papers/{paper_id}/concepts", response_model=ConceptsOut)
def get_paper_concepts(paper_id: str):
    return ConceptsOut(
        concepts=list_concepts(get_driver(), paper_id),
        backend=concepts_backend(),
        generation=_generation_status(paper_id),
    )


@router.post("/papers/{paper_id}/concepts/generate", response_model=ConceptsOut)
def generate_all_concepts(paper_id: str):
    """Start generating every visualisation that does not exist yet."""
    paper = _paper_or_404(paper_id)
    concepts = list_concepts(get_driver(), paper_id)
    return ConceptsOut(
        concepts=concepts,
        backend=concepts_backend(),
        generation=start_generation(paper_id, concepts, paper.get("title", "")),
    )


@router.post("/papers/{paper_id}/concepts/detect", response_model=DetectOut)
def detect_paper_concepts(paper_id: str, generate: bool = False):
    """Scan the PDF page by page and replace the paper's concepts.

    With ``generate=true`` every visualisation is then generated in the background.
    """
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
        with _jobs_lock:
            _jobs.pop(paper_id, None)  # an older job's concepts are gone
        generation = start_generation(paper_id, stored, paper.get("title", "")) if generate else None
        return DetectOut(
            concepts=stored,
            backend=concepts_backend(),
            generation=generation,
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
    if not _claim(concept_id):
        # The background job is generating this one: wait for its result.
        deadline = time.monotonic() + INFLIGHT_WAIT_S
        while concept_id in _inflight and time.monotonic() < deadline:
            time.sleep(0.5)
        concept = _concept_or_404(paper_id, concept_id)
        if concept.get("spec") and not force:
            return concept
        if not _claim(concept_id):
            raise HTTPException(status_code=409, detail="This visualisation is still being generated")
    try:
        spec = generate_spec(concept, paper.get("title", ""))
    except ConceptsError as exc:
        set_concept_spec(get_driver(), paper_id, concept_id, concept.get("spec"), str(exc))
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        _release(concept_id)
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
    with _jobs_lock:
        _jobs.pop(paper_id, None)
    return {"deleted": delete_concepts(get_driver(), paper_id)}
