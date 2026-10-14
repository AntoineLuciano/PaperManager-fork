"""Import one paper, with PDF, through the normal upload pipeline.

Shared by `scripts/import_to_project.py` (manifest of many papers) and the MCP
`upload_pdf` tool (one paper). Both run inside the backend container and talk to
the API on localhost, so an import is exactly a drag-and-drop upload: Docling
text, Drive, AI summary, embedding, topics, claims, references, figures.

An entry is a dict with one source key — `arxiv`, `biorxiv` (+ optional
`server`), `doi`, `pdf_url` or `pdf_path` — see `import_entry`.

Progress goes to stderr: the MCP server speaks JSON-RPC on stdout.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from config import settings
from db.queries.projects import add_paper_to_project
from services.auth import create_access_token

API = "http://localhost:8000"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
SUMMARY_FAILED = "_Summary could not be generated"
RATE_LIMIT_MARKERS = (b"error code: 1015", b"Too Many Requests", b"Just a moment")


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", file=sys.stderr, flush=True)


def api_headers() -> dict:
    token = create_access_token({"sub": settings.default_user_name}, timedelta(hours=12))
    return {"Authorization": f"Bearer {token}", "X-User-Name": settings.default_user_name}


# ── Database helpers ───────────────────────────────────────────────────────────

def project_id_for(driver, name_or_id: str) -> str | None:
    with driver.session() as s:
        rec = s.run(
            "MATCH (p:Project) WHERE p.id = $v OR p.name = $v RETURN p.id AS id LIMIT 1",
            v=name_or_id,
        ).single()
    return rec["id"] if rec else None


def doi_candidates(entry: dict) -> list[str]:
    """Lower-cased forms under which the library stores this paper's `doi`.

    PDF uploads of arXiv papers store `arXiv:<id>`, Semantic Scholar lookups
    `10.48550/arXiv.<id>`, reference stubs sometimes the bare id.
    """
    if entry.get("arxiv"):
        a = entry["arxiv"].lower()
        return [a, f"arxiv:{a}", f"10.48550/arxiv.{a}"]
    d = entry.get("biorxiv") or entry.get("doi")
    return [d.lower()] if d else []


def find_complete(driver, entry: dict) -> dict | None:
    """A paper matching this entry that already has a PDF and extracted text."""
    dois = doi_candidates(entry)
    if not dois:
        return None
    with driver.session() as s:
        rec = s.run(
            """
            MATCH (p:Paper) WHERE toLower(p.doi) IN $dois
              AND p.drive_file_id IS NOT NULL AND size(coalesce(p.raw_text, '')) > 0
            RETURN p.id AS id, p.title AS title, p.summary AS summary LIMIT 1
            """,
            dois=dois,
        ).single()
    return dict(rec) if rec else None


def find_any(driver, entry: dict) -> dict | None:
    dois = doi_candidates(entry)
    if not dois:
        return None
    with driver.session() as s:
        rec = s.run(
            "MATCH (p:Paper) WHERE toLower(p.doi) IN $dois RETURN p.id AS id, p.title AS title LIMIT 1",
            dois=dois,
        ).single()
    return dict(rec) if rec else None


def get_summary(driver, paper_id: str) -> str:
    with driver.session() as s:
        rec = s.run("MATCH (p:Paper {id: $id}) RETURN p.summary AS s", id=paper_id).single()
    return (rec and rec["s"]) or ""


# ── PDF download ───────────────────────────────────────────────────────────────

def pdf_urls(entry: dict) -> list[str]:
    if entry.get("pdf_url"):
        return [entry["pdf_url"]]
    if entry.get("arxiv"):
        return [f"https://arxiv.org/pdf/{entry['arxiv']}"]
    if entry.get("biorxiv"):
        doi = entry["biorxiv"]
        host = entry.get("server", "biorxiv")
        return [f"https://www.{host}.org/content/{doi}{v}.full.pdf" for v in ("v1", "v2", "v3", "v4", "")]
    return []


def fetch_pdf(client: httpx.Client, entry: dict, attempts: int, backoff: float) -> tuple[bytes | None, str]:
    if entry.get("pdf_path"):
        path = Path(entry["pdf_path"])
        if not path.is_file():
            return None, f"no such file in the backend container: {path}"
        data = path.read_bytes()
        return (data, "local") if data[:5] == b"%PDF-" else (None, "local file is not a PDF")

    urls = pdf_urls(entry)
    if not urls and entry.get("doi"):
        try:
            from services.bulk_resolver import download_pdf_for_paper
            data = download_pdf_for_paper({"doi": entry["doi"]})
            if data and data[:5] == b"%PDF-":
                return data, "unpaywall"
        except Exception as e:  # noqa: BLE001
            return None, f"unpaywall failed: {e}"
        return None, "no open-access PDF found"

    reason = "no URL"
    for attempt in range(attempts):
        rate_limited = False
        for url in urls:
            try:
                r = client.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=120)
            except httpx.HTTPError as e:
                reason = f"{url}: {e}"
                continue
            if r.content[:5] == b"%PDF-":
                return r.content, url
            if r.status_code in (403, 429) or any(m in r.content[:2000] for m in RATE_LIMIT_MARKERS):
                rate_limited = True
                reason = f"rate limited ({r.status_code}) at {url}"
                break
            reason = f"{url}: HTTP {r.status_code}, not a PDF"
        if not rate_limited:
            break
        wait = backoff * (2 ** attempt)
        log(f"   {reason}; retry {attempt + 1}/{attempts - 1} in {wait:.0f}s")
        if attempt < attempts - 1:
            time.sleep(wait)
    return None, reason


# ── API calls ──────────────────────────────────────────────────────────────────

def upload_pdf(client: httpx.Client, headers: dict, data: bytes, name: str, project_id: str) -> dict:
    r = client.post(
        f"{API}/papers/upload",
        files={"file": (name, data, "application/pdf")},
        data={"project_id": project_id} if project_id else {},
        headers=headers,
        timeout=1800,
    )
    if r.status_code == 409:
        detail = json.loads(r.json()["detail"])
        return {"id": detail["existing_id"], "title": detail.get("existing_title"), "status": "already-in-library"}
    r.raise_for_status()
    p = r.json()
    return {"id": p["id"], "title": p.get("title"), "status": "uploaded"}


def metadata_only(client: httpx.Client, headers: dict, entry: dict, project_id: str) -> dict:
    doi = entry.get("biorxiv") or entry.get("doi")
    url = f"https://doi.org/{doi}" if doi else f"https://arxiv.org/abs/{entry['arxiv']}"
    r = client.post(f"{API}/papers/from-url-full", json={"url": url, "project_id": project_id},
                    headers=headers, timeout=900)
    r.raise_for_status()
    p = r.json()
    return {"id": p["id"], "title": p.get("title"), "status": "metadata-only"}


def regenerate_summary(client: httpx.Client, headers: dict, driver, paper_id: str) -> str:
    if not get_summary(driver, paper_id).startswith(SUMMARY_FAILED):
        return "ok"
    for _ in range(2):
        try:
            r = client.post(f"{API}/papers/{paper_id}/regenerate-summary", headers=headers, timeout=900)
            if r.status_code < 300 and not get_summary(driver, paper_id).startswith(SUMMARY_FAILED):
                return "regenerated"
        except httpx.HTTPError:
            pass
        time.sleep(10)
    return "failed"


# ── One entry ──────────────────────────────────────────────────────────────────

def label(entry: dict) -> str:
    for k in ("arxiv", "biorxiv", "doi", "pdf_url", "pdf_path"):
        if entry.get(k):
            return f"{k}:{entry[k]}"
    return json.dumps(entry)


def pdf_name(entry: dict) -> str:
    if entry.get("pdf_path"):
        return Path(entry["pdf_path"]).name
    return (entry.get("arxiv") or entry.get("biorxiv") or "paper").replace("/", "_") + ".pdf"


def import_entry(
    client: httpx.Client,
    headers: dict,
    driver,
    entry: dict,
    project_id: str,
    *,
    attempts: int = 4,
    backoff: float = 120,
    metadata_fallback: bool = True,
    dry_run: bool = False,
) -> dict:
    """Import one entry and link it to the project (if given); never raises.

    1. A paper with this DOI / arXiv id that already has a PDF and full text is
       only linked to the project.
    2. Otherwise the PDF is fetched (arXiv, bioRxiv/medRxiv with version
       suffixes, Unpaywall for other DOIs, the given URL or path), retrying with
       backoff on rate limits, and sent through POST /papers/upload. A 409
       (already in library) resolves to the existing paper.
    3. Without a PDF the paper is added metadata-only via /papers/from-url-full
       (unless it already exists or `metadata_fallback` is off).
    4. The paper is linked to the project, and a failed AI summary is regenerated.
    """
    t0 = time.time()
    res: dict = {"entry": entry, "at": datetime.now(timezone.utc).isoformat()}
    try:
        done = find_complete(driver, entry)
        if done:
            res.update(id=done["id"], title=done["title"], status="already-complete")
        elif dry_run:
            res.update(status="would-import")
        else:
            data, source = fetch_pdf(client, entry, attempts, backoff)
            res["pdf_source"] = source
            if data:
                res.update(upload_pdf(client, headers, data, pdf_name(entry), project_id))
            elif not metadata_fallback or not doi_candidates(entry):
                res.update(status="no-pdf")
            else:
                existing = find_any(driver, entry)
                if existing:
                    res.update(id=existing["id"], title=existing["title"], status="no-pdf-kept-existing")
                else:
                    res.update(metadata_only(client, headers, entry, project_id))
        if res.get("id") and not dry_run:
            if project_id:
                add_paper_to_project(driver, paper_id=res["id"], project_id=project_id)
                res["linked"] = True
            res["summary"] = regenerate_summary(client, headers, driver, res["id"])
    except Exception as e:  # noqa: BLE001
        res.update(status="error", error=repr(e)[:500])
    res["seconds"] = round(time.time() - t0)
    return res
