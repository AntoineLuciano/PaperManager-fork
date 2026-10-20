"""Quick tour of a paper: generate it in the background, serve the cached one."""
from __future__ import annotations

import contextvars
import json
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from db.connection import get_driver
from db.queries.papers import get_paper
from services.auth import get_current_user
from services.concepts import page_texts_from_pdf
from services.drive import download_pdf
from services.paper_tour import SUBSCRIPTION_HINT, TourError, build_tour, tour_available

log = logging.getLogger(__name__)
router = APIRouter(prefix="/papers", tags=["tour"], dependencies=[Depends(get_current_user)])

# Papers whose tour is being generated → error of the last failed run (None while running).
_running: set[str] = set()
_errors: dict[str, str] = {}
_lock = threading.Lock()


def _paper_concepts(paper_id: str) -> list[dict]:
    with get_driver().session() as session:
        return session.run(
            """
            MATCH (:Paper {id: $pid})-[d:DISCUSSES]->(c:MapConcept)
            RETURN c.name AS name, c.definition AS definition, d.role AS role, d.in_paper AS in_paper
            """,
            pid=paper_id,
        ).data()


def _stored_tour(paper_id: str) -> dict | None:
    with get_driver().session() as session:
        rec = session.run(
            "MATCH (p:Paper {id: $pid}) RETURN p.tour_json AS t, p.tour_at AS at", pid=paper_id
        ).single()
    if not rec or not rec["t"]:
        return None
    return {**json.loads(rec["t"]), "generated_at": rec["at"]}


def _status(paper_id: str) -> dict:
    with _lock:
        running = paper_id in _running
        error = _errors.get(paper_id)
    return {
        "tour": _stored_tour(paper_id),
        "running": running,
        "error": error,
        "available": tour_available(),
        "hint": None if tour_available() else SUBSCRIPTION_HINT,
    }


def _generate(paper: dict) -> None:
    pid = paper["id"]
    error = None
    try:
        pages = page_texts_from_pdf(download_pdf(paper["drive_file_id"]))
        tour = build_tour(paper, _paper_concepts(pid), pages)
        with get_driver().session() as session:
            session.run(
                "MATCH (p:Paper {id: $pid}) SET p.tour_json = $t, p.tour_at = $at",
                pid=pid, t=json.dumps(tour), at=datetime.now(timezone.utc).isoformat(),
            )
    except TourError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001
        log.exception("Tour for %s failed", pid)
        error = f"{type(exc).__name__}: {exc}"
    with _lock:
        _running.discard(pid)
        if error:
            _errors[pid] = error
        else:
            _errors.pop(pid, None)


@router.get("/{paper_id}/tour")
def get_tour(paper_id: str):
    if not get_paper(get_driver(), paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    return _status(paper_id)


@router.post("/{paper_id}/tour")
def start_tour(paper_id: str):
    """Generate (or regenerate) the tour in the background; poll GET for the result."""
    paper = get_paper(get_driver(), paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    if not paper.get("drive_file_id"):
        raise HTTPException(status_code=422, detail="The tour needs the paper's PDF")
    if not tour_available():
        raise HTTPException(status_code=503, detail=SUBSCRIPTION_HINT)
    with _lock:
        if paper_id not in _running:
            _running.add(paper_id)
            _errors.pop(paper_id, None)
            # The copied context carries the request user, who must be allowed Claude Code.
            ctx = contextvars.copy_context()
            threading.Thread(target=ctx.run, args=(_generate, paper),
                             name=f"tour-{paper_id}", daemon=True).start()
    return _status(paper_id)
