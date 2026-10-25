"""Conference explorer: the accepted papers of NeurIPS, ICML, ICLR, CVPR, ACL, ... by
institution and by topic. Data and maths live in services/conferences/."""
from __future__ import annotations

import logging
import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from db.connection import get_driver
from db.queries.visibility import paper_visibility_clause
from services.auth import get_current_user, get_request_user
from services.conferences import catalog, store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/conferences", tags=["conferences"])


def _edition(key: str) -> catalog.Edition:
    ed = catalog.resolve(key)
    if ed is None:
        raise HTTPException(status_code=404, detail=f"Unknown conference '{key}'")
    return ed


def _dataset(key: str) -> store.Dataset:
    ed = _edition(key)
    ds = store.load(ed.key)
    if ds is None:
        st = store.status(ed.key)
        raise HTTPException(status_code=409, detail={"message": f"{ed.name} is not loaded yet.", "status": st})
    return ds


# ── library match (title -> paper id), per user, cached briefly ──────────────

_lib_cache: dict[str, tuple[float, dict[str, str]]] = {}
_lib_lock = threading.Lock()
_LIB_TTL = 120.0


def _title_key(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def library_titles() -> dict[str, str]:
    user = get_request_user() or ""
    with _lib_lock:
        hit = _lib_cache.get(user)
        if hit and time.time() - hit[0] < _LIB_TTL:
            return hit[1]
    vis, params = paper_visibility_clause("p")
    out: dict[str, str] = {}
    try:
        with get_driver().session() as s:
            for rec in s.run(f"MATCH (p:Paper) WHERE p.title IS NOT NULL AND {vis} RETURN p.id AS id, p.title AS t",
                             **params):
                k = _title_key(rec["t"])
                if len(k) >= 12:
                    out.setdefault(k, rec["id"])
    except Exception as exc:  # noqa: BLE001 — the explorer works without the library match
        log.warning("conference library match unavailable: %s", exc)
    with _lib_lock:
        _lib_cache[user] = (time.time(), out)
    return out


def _forget_library_cache() -> None:
    with _lib_lock:
        _lib_cache.clear()


# ── endpoints ─────────────────────────────────────────────────────────────────

# API paths never equal a page path (/conferences, /conferences/<key>): the browser would
# answer the API call from the cached page HTML.
@router.get("/catalog")
def list_conferences():
    """Every known conference-year with its build state."""
    from services.conferences import areas

    return {"conferences": store.catalog_rows(), "areas": areas.public(),
            "defaults": store.default_keys()}


@router.get("/{key}/status")
def conference_status(key: str):
    ed = _edition(key)
    return {"key": ed.key, "name": ed.name, **store.status(ed.key)}


@router.post("/{key}/build")
def build_conference(key: str, _user: str = Depends(get_current_user)):
    """Queue a download + index of this conference (also used to refresh it)."""
    ed = _edition(key)
    return {"key": ed.key, "name": ed.name, **store.request_build(ed.key)}


@router.get("/{key}/overview")
def conference_overview(key: str):
    ds = _dataset(key)
    return {**store.overview(ds), "status": store.status(ds.key)}


@router.get("/{key}/institutions")
def conference_institutions(
    key: str,
    q: str = "",
    sector: str = Query("", pattern="^(A|I)?$"),
    area: int = -1,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    ds = _dataset(key)
    return store.search_institutions(ds, q=q, sector=sector, area=area, offset=offset, limit=limit)


@router.get("/{key}/institutions/{slug}")
def conference_institution(key: str, slug: str):
    ds = _dataset(key)
    out = store.institution_detail(ds, slug, library=library_titles())
    if out is None:
        raise HTTPException(status_code=404, detail="Institution not found at this conference")
    return out


class TopicBody(BaseModel):
    query: str
    k: int = 100


@router.post("/{key}/topic")
def conference_topic(key: str, body: TopicBody):
    if not body.query.strip():
        raise HTTPException(status_code=422, detail="Empty query")
    ds = _dataset(key)
    return store.topic(ds, body.query[:4000], k=body.k, library=library_titles())


@router.get("/{key}/papers/{pid}")
def conference_paper(key: str, pid: str):
    ds = _dataset(key)
    out = store.paper_detail(ds, pid, library=library_titles())
    if out is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return out


class AddBody(BaseModel):
    project_id: str | None = None


@router.post("/{key}/papers/{pid}/add")
def add_conference_paper(key: str, pid: str, body: AddBody, user: str = Depends(get_current_user)):
    """Put a conference paper into the library (metadata only: title, abstract, authors
    with their institutions, venue, year, link). Returns the existing paper when the
    library already has one with the same title."""
    from db.queries.papers import create_paper
    from db.queries.people import get_or_create_person_with_affiliation, link_author
    from db.queries.projects import add_paper_to_project
    from db.queries.tags import tag_paper
    from db.queries.users import link_paper_added_by

    ds = _dataset(key)
    j = ds.by_pid.get(pid)
    if j is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    p = ds.papers[j]
    existing = library_titles().get(_title_key(p["t"]))
    driver = get_driver()
    if existing:
        paper_id, created = existing, False
    else:
        paper = create_paper(driver, {
            "title": p["t"], "year": ds.raw["year"], "abstract": p["a"] or None,
            "venue": ds.raw["name"], "metadata_source": "conference",
            "document_type": "paper",
        })
        paper_id, created = paper["id"], True
        for name, ids in zip(p["au"], p["ai"]):
            if not name:
                continue
            aff = "; ".join(ds.insts[i]["n"] for i in ids) or None
            try:
                person = get_or_create_person_with_affiliation(driver, name, aff)
                link_author(driver, paper_id, person["id"])
            except Exception as exc:  # noqa: BLE001
                log.warning("conference add: author %s failed: %s", name, exc)
        try:
            link_paper_added_by(driver, paper_id, user)
            tag_paper(driver, paper_id, "from-conference")
        except Exception as exc:  # noqa: BLE001
            log.warning("conference add: attribution/tag failed: %s", exc)
    if body.project_id:
        try:
            add_paper_to_project(driver, paper_id=paper_id, project_id=body.project_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("conference add: project link failed: %s", exc)
    _forget_library_cache()
    return {"paper_id": paper_id, "created": created}
