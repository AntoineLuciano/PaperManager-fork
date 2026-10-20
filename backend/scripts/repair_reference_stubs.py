#!/usr/bin/env python
"""Repair citation stubs so duplicate scans and the graph can join them up.

Run inside the backend container:

    docker exec -w /app papermanager-backend-1 python scripts/repair_reference_stubs.py          # dry run
    docker exec -w /app papermanager-backend-1 python scripts/repair_reference_stubs.py --apply

1. Drop the ``from-references`` tag from papers that have a PDF (reference import used to tag
   whatever node a reference matched, and merges carry stub tags onto keepers).
2. Strip a leading year from stub titles ("2023. Segment anything").
3. Stubs whose title is parser junk (author list, DOI/URL text, venue fragment) but which carry a
   DOI or arXiv id: replace the title (and fill year/venue) from Semantic Scholar or CrossRef.

The old title is kept in ``title_raw``. Afterwards rerun ``merge_duplicates.py scan``: the repaired
stubs now match their papers by title.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.connection import get_driver  # noqa: E402
from services.duplicate_scan import normalize_doi  # noqa: E402
from services.metadata_lookup import lookup_crossref, lookup_semantic_scholar  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"
YEAR_PREFIX = re.compile(r"^\(?(19|20)\d\d[a-z]?\)?[.:,]\s+")
AUTHOR_LIST = re.compile(r"^([A-Z][\w'’-]+,? (?:[A-Z]\.? ?){1,3}[,.;]|[A-Z]\. ?(?:[A-Z]\. ?)?[A-Z][\w'’-]+,)")


def is_junk(title: str) -> bool:
    """Narrow rule: only titles that cannot be a paper title."""
    t = (title or "").strip()
    if not t:
        return True
    low = t.lower()
    return bool(
        AUTHOR_LIST.match(t)
        or "\n" in t
        or "doi:" in low or "doi.org" in low or "http" in low
        or low.startswith(("in:", "in proceedings", "proceedings of", "pmid"))
    )


def lookup_arxiv(arxiv_id: str) -> dict | None:
    """Title and year from the arXiv API (no key, no Semantic Scholar rate limit)."""
    try:
        r = httpx.get("https://export.arxiv.org/api/query", params={"id_list": arxiv_id}, timeout=15)
        entry = ET.fromstring(r.text).find(f"{ATOM}entry")
        title = entry.findtext(f"{ATOM}title") if entry is not None else None
        if not title or title.strip().lower() == "error":
            return None
        published = entry.findtext(f"{ATOM}published") or ""
        return {"title": " ".join(title.split()), "year": int(published[:4]) if published[:4].isdigit() else None}
    except Exception:  # noqa: BLE001 — fall back to Semantic Scholar
        return None


def lookup(doi: str) -> dict | None:
    n = normalize_doi(doi)
    if not n:
        return None
    if n.startswith("arxiv:"):
        return lookup_arxiv(n.split(":", 1)[1]) or lookup_semantic_scholar(f"arXiv:{n.split(':', 1)[1]}")
    return lookup_crossref(n) or lookup_semantic_scholar(n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    driver = get_driver()

    with driver.session() as s:
        n = s.run(
            "MATCH (p:Paper)-[r:TAGGED]->(:Tag {name: 'from-references'}) "
            "WHERE p.drive_file_id IS NOT NULL RETURN count(r) AS n"
        ).single()["n"]
        print(f"1. from-references tag on {n} PDF papers")
        if args.apply:
            s.run(
                "MATCH (p:Paper)-[r:TAGGED]->(:Tag {name: 'from-references'}) "
                "WHERE p.drive_file_id IS NOT NULL DELETE r"
            )
        stubs = s.run(
            "MATCH (p:Paper) WHERE p.drive_file_id IS NULL "
            "RETURN p.id AS id, p.title AS title, p.doi AS doi, p.year AS year, p.venue AS venue"
        ).data()

    fixes: list[tuple[str, dict]] = []
    for p in stubs:
        t = p["title"] or ""
        if YEAR_PREFIX.match(t) and not is_junk(t):
            fixes.append((p["id"], {"title": YEAR_PREFIX.sub("", t).strip(), "title_raw": t}))
    print(f"2. {len(fixes)} year-prefixed titles, e.g. {[f[1]['title'] for f in fixes[:3]]}")

    junk = [p for p in stubs if p["doi"] and is_junk(p["title"])]
    print(f"3. {len(junk)} junk-titled stubs with a DOI")
    resolved = 0
    for i, p in enumerate(junk):
        meta = lookup(p["doi"])
        time.sleep(3)  # arXiv asks for 3 s between calls; also keeps S2 under its limit
        if not meta or not meta.get("title") or is_junk(meta["title"]):
            continue
        resolved += 1
        upd = {"title": meta["title"].strip(), "title_raw": p["title"]}
        if not p["year"] and meta.get("year"):
            upd["year"] = meta["year"]
        if not p["venue"] and meta.get("venue"):
            upd["venue"] = meta["venue"]
        fixes.append((p["id"], upd))
        if i < 8 or i % 25 == 0:
            print(f"   [{i + 1}/{len(junk)}] {p['title'][:60]!r} -> {upd['title'][:60]!r}", flush=True)
    print(f"   resolved {resolved} of {len(junk)}")

    if args.apply and fixes:
        with driver.session() as s:
            s.run(
                "UNWIND $rows AS row MATCH (p:Paper {id: row.id}) SET p += row.props",
                rows=[{"id": pid, "props": props} for pid, props in fixes],
            )
    print(f"{'applied' if args.apply else 'dry run'}: {len(fixes)} title fixes")


if __name__ == "__main__":
    main()
