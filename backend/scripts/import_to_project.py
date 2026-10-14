"""Import a list of papers into a project, with PDF, through the normal upload pipeline.

Run inside the backend container so the app modules, Drive credentials and the
running API are all reachable:

    docker exec -w /app papermanager-backend-1 \
        python scripts/import_to_project.py scripts/imports/<manifest>.json

Manifest (JSON, kept in scripts/imports/ as the record of what was imported):

    {
      "project": "MasterThesis",
      "papers": [
        {"arxiv": "2210.02747", "note": "MIT 6.S184 ref [25]"},
        {"biorxiv": "10.64898/2026.01.23.701250"},
        {"doi": "10.1103/zfn9-18y7"},
        {"pdf_url": "https://example.org/paper.pdf"},
        {"pdf_path": "/tmp/paper.pdf"}
      ]
    }

Per entry:
  1. If a paper with this DOI / arXiv id already has a PDF and full text, it is
     only linked to the project.
  2. Otherwise the PDF is downloaded (arXiv, bioRxiv/medRxiv with version
     suffixes, Unpaywall for other DOIs, or the given URL/path), retrying with
     backoff on rate limits (HTTP 403/429, Cloudflare 1015).
  3. The PDF goes through POST /papers/upload — the same pipeline as a
     drag-and-drop upload: Docling text, Drive, AI summary, embedding, topics,
     claims, references, figures. A 409 (already in library) resolves to the
     existing paper; a text-less stub is enriched in place.
  4. If no PDF can be obtained, the paper is added metadata-only via
     POST /papers/from-url-full (unless it already exists).
  5. The paper is linked to the project, and a failed AI summary is regenerated.

Re-running a manifest is safe: complete papers are skipped, so a later run picks
up only what failed (e.g. after a bioRxiv rate limit has cleared). Each run
appends one JSON line per entry to <manifest>.results.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from config import settings  # noqa: E402
from db.connection import get_driver  # noqa: E402
from services.auth import set_request_user  # noqa: E402
from services.pdf_import import api_headers, import_entry, label, log, project_id_for  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--attempts", type=int, default=4, help="download attempts on rate limit (default 4)")
    ap.add_argument("--backoff", type=float, default=120, help="first rate-limit wait in s, doubles (default 120)")
    ap.add_argument("--no-metadata-fallback", action="store_true",
                    help="leave papers without a PDF out instead of adding them metadata-only")
    ap.add_argument("--dry-run", action="store_true", help="only report what each entry would do")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    set_request_user(settings.default_user_name)
    driver = get_driver()
    project_id = project_id_for(driver, manifest["project"])
    if not project_id:
        sys.exit(f"Project not found: {manifest['project']}")
    headers = api_headers()
    results_path = args.manifest.with_suffix(".results.jsonl")
    entries = manifest["papers"]
    log(f"{len(entries)} entries -> project {manifest['project']} ({project_id})")

    counts: dict[str, int] = {}
    with httpx.Client() as client:
        for i, entry in enumerate(entries, 1):
            log(f"[{i}/{len(entries)}] {label(entry)}")
            res = import_entry(
                client, headers, driver, entry, project_id,
                attempts=args.attempts, backoff=args.backoff,
                metadata_fallback=not args.no_metadata_fallback, dry_run=args.dry_run,
            )
            counts[res["status"]] = counts.get(res["status"], 0) + 1
            log(f"   -> {res['status']} | {(res.get('title') or '')[:70]} | {res.get('pdf_source', '')} | {res['seconds']}s")
            if not args.dry_run:
                with results_path.open("a") as fh:
                    fh.write(json.dumps(res) + "\n")
    log(f"done: {counts}")


if __name__ == "__main__":
    main()
