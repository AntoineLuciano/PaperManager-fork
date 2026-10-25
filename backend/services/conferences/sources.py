"""Fetch one conference-year from its public source and bring it into one shape.

Every fetcher returns ``(papers, info)``. A paper is::

    {"title", "abstract", "authors": [{"name", "insts": [raw institution, ...]}],
     "decision", "track", "session", "url", "forum", "native_topic"}

``info`` says how complete the source was (``expected`` papers, ``partial``).
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from config import settings
from services.conferences.catalog import Edition

log = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (PaperManager conference explorer)"}
_LFS = "version https://git-lfs"


def _verify():
    if not settings.ssl_verify:
        return False
    return settings.ssl_ca_bundle or True


def _get_json(url: str, timeout: float = 120.0):
    with httpx.Client(headers=_UA, timeout=timeout, follow_redirects=True, verify=_verify()) as client:
        r = client.get(url)
        r.raise_for_status()
        text = r.text
        if text.startswith(_LFS):
            # Large Paper Copilot files are stored in Git LFS; raw.githubusercontent
            # returns the pointer, media.githubusercontent the file.
            media = url.replace("raw.githubusercontent.com/papercopilot/paperlists/main",
                                "media.githubusercontent.com/media/papercopilot/paperlists/main")
            r = client.get(media)
            r.raise_for_status()
            text = r.text
        return json.loads(text)


def fetch(edition: Edition) -> tuple[list[dict], dict]:
    if edition.source == "miniconf":
        return _miniconf(edition)
    return _papercopilot(edition)


# ── miniconf (official conference sites) ──────────────────────────────────────

_RANK = {"Oral": 3, "Spotlight": 2, "Highlight": 2, "Poster": 1}


def _miniconf_decision(ev: dict) -> str:
    d = (ev.get("decision") or "").lower()
    et = (ev.get("eventtype") or ev.get("event_type") or "").lower()
    if "oral" in d or et == "oral":
        return "Oral"
    if "spotlight" in d:
        return "Spotlight"
    if "highlight" in d:
        return "Highlight"
    return "Poster"


def _title_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def _miniconf(edition: Edition) -> tuple[list[dict], dict]:
    data = _get_json(edition.source_url)
    events = list(data.get("results") or [])
    expected = int(data.get("count") or len(events))
    nxt = data.get("next")
    # Some sites cap the static file at one page and point `next` at their API,
    # which wants a login. Try it; keep what we have if it refuses.
    while nxt and len(events) < expected:
        try:
            page = _get_json(nxt.replace("http://", "https://"), timeout=60)
        except Exception as exc:  # noqa: BLE001
            log.info("miniconf %s: next page refused (%s); keeping %d of %d",
                     edition.key, exc, len(events), expected)
            break
        events.extend(page.get("results") or [])
        nxt = page.get("next")

    host = edition.series.host
    papers: dict[str, dict] = {}
    for ev in events:
        title = (ev.get("name") or "").strip()
        if not title:
            continue
        # Title, not paper_url: a few feeds reuse one OpenReview link across papers.
        key = _title_key(title)
        decision = _miniconf_decision(ev)
        authors = [
            {"name": (a.get("fullname") or "").strip(),
             "insts": [a["institution"]] if (a.get("institution") or "").strip() else []}
            for a in ev.get("authors") or []
        ]
        forum = ev.get("paper_url") or ""
        if not forum:
            for m in ev.get("eventmedia") or []:
                uri = m.get("uri") or ""
                if "openreview.net" in uri or uri.endswith(".pdf"):
                    forum = uri
                    break
        row = {
            "title": title,
            "abstract": (ev.get("abstract") or "").strip(),
            "authors": authors,
            "decision": decision,
            "track": "",
            "session": (ev.get("session") or "").strip(),
            "url": f"https://{host}{ev['virtualsite_url']}" if ev.get("virtualsite_url") else "",
            "forum": forum,
            "native_topic": (ev.get("topic") or "").strip(),
            "keywords": [k for k in (ev.get("keywords") or []) if isinstance(k, str)],
        }
        old = papers.get(key)
        if old is None:
            papers[key] = row
            continue
        # An oral appears twice (its poster and its talk): keep one row, the best decision,
        # and whatever fields the other copy has that this one lacks.
        if _RANK[decision] > _RANK[old["decision"]]:
            old["decision"] = decision
        for f in ("abstract", "url", "forum", "native_topic"):
            if not old[f] and row[f]:
                old[f] = row[f]
        # NeurIPS 2026 shows a paper in several cities: keep every session.
        if row["session"] and row["session"] not in old["session"].split(" · "):
            old["session"] = " · ".join(x for x in (old["session"], row["session"]) if x)
        if not any(a["insts"] for a in old["authors"]) and any(a["insts"] for a in authors):
            old["authors"] = authors
    partial = len(events) < expected
    if partial:
        # The public paper list page still names every paper: add the missing ones as
        # titles (no authors, no abstract) so topic search covers the whole conference.
        for title, url in _miniconf_titles(edition):
            k = _title_key(title)
            if k and k not in papers:
                papers[k] = {"title": title, "abstract": "", "authors": [], "decision": "Poster", "track": "",
                             "session": "", "url": url, "forum": "", "native_topic": "", "keywords": []}
    rows = list(papers.values())
    return rows, {"expected": expected, "partial": partial, "events": len(events)}


_LI = re.compile(r'<li><a href="(/virtual/\d{4}/(?:poster|oral)/\d+)">(.*?)</a></li>')


def _miniconf_titles(edition: Edition) -> list[tuple[str, str]]:
    import html as _html

    host = edition.series.host
    try:
        with httpx.Client(headers=_UA, timeout=60, follow_redirects=True, verify=_verify()) as client:
            r = client.get(f"https://{host}/virtual/{edition.year}/papers.html")
            r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log.info("miniconf %s: paper list page unavailable (%s)", edition.key, exc)
        return []
    return [(_html.unescape(t).strip(), f"https://{host}{u}") for u, t in _LI.findall(r.text) if t.strip()]


# ── Paper Copilot ─────────────────────────────────────────────────────────────

def _split(s: str | None, sep: str) -> list[str]:
    return [p.strip() for p in (s or "").split(sep)]


def _pc_decision(status: str) -> str:
    s = (status or "").strip()
    low = s.lower()
    for word in ("oral", "spotlight", "highlight"):
        if word in low:
            return word.title()
    if low in ("", "poster", "accept", "technical", "main", "long", "short"):
        return "Poster" if low in ("", "poster", "accept") else s.title()
    if low == "finding":
        return "Findings"
    return s[:40].title()


def _papercopilot(edition: Edition) -> tuple[list[dict], dict]:
    data = _get_json(edition.source_url, timeout=300)
    rows: list[dict] = []
    seen: set[str] = set()
    for p in data:
        status = (p.get("status") or "").lower()
        if "reject" in status or "withdraw" in status:
            continue
        title = (p.get("title") or "").strip()
        if not title or _title_key(title) in seen:
            continue
        seen.add(_title_key(title))
        names = [n for n in _split(p.get("author"), ";")]
        norm = _split(p.get("aff_unique_norm"), ";")
        idx = _split(p.get("aff_unique_index"), ";")
        raw = _split(p.get("aff"), ";")
        authors = []
        for i, name in enumerate(names):
            if not name:
                continue
            insts: list[str] = []
            if i < len(idx) and idx[i]:
                for j in idx[i].split("+"):
                    if j.strip().isdigit() and int(j) < len(norm) and norm[int(j)]:
                        insts.append(norm[int(j)])
            if not insts and i < len(raw) and raw[i]:
                insts = [x.strip(" ,") for x in raw[i].split("+") if x.strip(" ,")]
            authors.append({"name": name, "insts": insts})
        site = p.get("site") or ""
        rows.append({
            "title": title,
            "abstract": (p.get("abstract") or "").strip(),
            "authors": authors,
            "decision": _pc_decision(p.get("status") or ""),
            "track": "" if (p.get("track") or "main") == "main" else str(p.get("track")),
            "session": "",
            "url": site,
            "forum": site if "openreview.net" in site else "",
            "native_topic": (p.get("primary_area") or "") if isinstance(p.get("primary_area"), str) else "",
            "keywords": [k.strip() for k in (p.get("keywords") or "").split(";") if k.strip()]
            if isinstance(p.get("keywords"), str) else [],
        })
    return rows, {"expected": len(rows), "partial": False, "events": len(data)}
