"""Find duplicate Paper nodes and decide which one to keep.

Pure functions over plain dicts (one per Paper, see ``SCAN_QUERY``), so the rules can be tested
without a database. ``routers/merge.py`` and ``scripts/merge_duplicates.py`` call ``scan()``.

Two papers are linked when

- **doi**: their normalised DOIs are equal (``arXiv:2206.00364``, ``2206.00364`` and
  ``10.48550/arXiv.2206.00364`` are one DOI; bioRxiv ``v2`` suffixes and stray ``doi:`` tails
  are dropped) *and* their titles agree (similarity ≥ 0.6) or one side is a citation stub whose
  "title" is really an author list or a figure caption. A DOI match with clearly different real
  titles is not a duplicate but a wrong DOI on one of them — reported in ``doi_conflicts``.
- **title**: identical normalised titles of at least four words (generic titles such as
  "Supplementary information" excluded).
- **near-title**: SequenceMatcher ≥ 0.97 on the titles with spaces removed and the same
  numbers, or one title a prefix of the other (≥ 35 characters and ≥ half its length) when the
  short one is a library entry's — a truncated PDF extraction; among citation stubs a shorter
  title is as often an earlier, different paper.

Title links of any kind require compatible DOIs: missing, equal, or a preprint DOI next to a
journal DOI. Two different arXiv ids, or two different journal DOIs, are two papers.

Links form groups (union–find). In each group the keeper is the entry with most to lose:
PDF, then notes/highlights, project membership, text, abstract, citations, age.
"""
from __future__ import annotations

import difflib
import itertools
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

SCAN_QUERY = """
MATCH (p:Paper)
OPTIONAL MATCH (p)-[:IN_PROJECT]->(pr:Project)
WITH p, collect(DISTINCT pr.name) AS projects
OPTIONAL MATCH (p)-[:TAGGED]->(t:Tag)
WITH p, projects, collect(DISTINCT t.name) AS tags
RETURN p.id AS id, p.title AS title, p.doi AS doi, p.year AS year, p.created_at AS created_at,
       p.drive_file_id AS drive_file_id, coalesce(size(p.raw_text), 0) AS text_chars,
       p.abstract IS NOT NULL AS has_abstract,
       COUNT { (p)-[:HAS_NOTE]->() } AS notes, COUNT { (p)-[:HAS_ANNOTATION]->() } AS annotations,
       COUNT { ()-[:CITES]->(p) } AS cited_by, COUNT { (p)-[:CITES]->() } AS cites,
       projects, tags
"""

PREPRINT_PREFIXES = ("10.1101/", "10.64898/", "10.48550/", "arxiv:", "10.2139/ssrn", "10.21203/rs")
GENERIC_TITLE = re.compile(
    r"^(supplementary|supporting information|figure|table|erratum|correction|corrigendum|"
    r"reply to|response to|editorial|front matter|back matter|author correction|"
    r"this paper is included in|proceedings of the|what are the)\b")
ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?$")

CLASSES = ("pdf_duplicates", "library_duplicates", "paper_with_stubs", "stubs_only")


# ── normalisation ───────────────────────────────────────────────────────────

def normalize_doi(doi: str | None) -> str | None:
    """Canonical form of a DOI or arXiv identifier, or None if it is not one."""
    if not doi:
        return None
    x = unicodedata.normalize("NFKC", str(doi)).strip().lower()
    x = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", x)
    x = re.sub(r"(doi:|\.pdf|/full|/abstract)$", "", x).strip(" ./")
    m = re.search(r"(?:arxiv[:.]\s*|10\.48550/arxiv\.)(\d{4}\.\d{4,5})", x)
    if m:
        return "arxiv:" + m.group(1)
    m = ARXIV_ID.fullmatch(x)
    if m:
        return "arxiv:" + m.group(1)
    if x.startswith(("10.1101/", "10.64898/")):
        x = re.sub(r"v\d+$", "", x)
    return x if x.startswith("10.") else None


def doi_variants(doi: str | None) -> list[str]:
    """Spellings under which the same identifier may be stored (for exact-match lookups)."""
    n = normalize_doi(doi)
    if not n:
        return [doi] if doi else []
    if n.startswith("arxiv:"):
        i = n.split(":", 1)[1]
        return sorted({doi, i, f"arXiv:{i}", f"arxiv:{i}", f"10.48550/arXiv.{i}", f"10.48550/arxiv.{i}"})
    return sorted({doi, n, n.upper(), f"https://doi.org/{n}"})


def normalize_title(title: str | None) -> str:
    t = unicodedata.normalize("NFKC", title or "").lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_similarity(a: str, b: str) -> float:
    a, b = normalize_title(a), normalize_title(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def is_truncation(a: str, b: str) -> bool:
    """True if one normalised title is a long-enough prefix of the other."""
    s, l = sorted((normalize_title(a), normalize_title(b)), key=len)
    return len(s) >= 35 and len(s) >= 0.5 * len(l) and l.startswith(s) and s != l


def looks_like_garbage_title(title: str | None) -> bool:
    """Reference-parser artefacts: author lists, figure captions, citation strings."""
    t = (title or "").strip()
    if not t:
        return True
    if re.match(r"^([A-Z][a-z]+,? [A-Z]\.|[A-Z]\. ?[A-Z][a-z]+|[A-Z][a-z]+ [A-Z][a-z]+,)", t):
        return True
    return t.count(",") >= 3 or t.lower().startswith(("figure", "table", "fig."))


_STOP = {"with", "from", "using", "towards", "toward", "into", "through", "their", "based", "large", "model", "models"}


def title_words(title: str | None) -> set[str]:
    return {w for w in normalize_title(title).split() if len(w) >= 4 and w not in _STOP}


def shares_title_words(a: str | None, b: str | None, k: int = 2) -> bool:
    return len(title_words(a) & title_words(b)) >= k


def is_preprint(doi_norm: str | None) -> bool:
    return bool(doi_norm) and doi_norm.startswith(PREPRINT_PREFIXES)


# ── model ───────────────────────────────────────────────────────────────────

def is_stub(p: dict) -> bool:
    """A citation stub: created by reference import, nothing of the user's attached."""
    return (not p.get("drive_file_id") and not p.get("projects") and not p.get("notes")
            and not p.get("annotations") and "from-references" in (p.get("tags") or []))


def keep_score(p: dict) -> tuple:
    """Higher is kept. Order: PDF, user content, project, text, abstract, real title, citations, age."""
    return (
        bool(p.get("drive_file_id")),
        (p.get("notes") or 0) + (p.get("annotations") or 0),
        bool(p.get("projects")),
        p.get("text_chars") or 0,
        bool(p.get("has_abstract")),
        not looks_like_garbage_title(p.get("title")),
        (p.get("cites") or 0) + (p.get("cited_by") or 0),
        -_age_key(p.get("created_at")),
    )


def _age_key(created: str | None) -> float:
    # ISO timestamps sort lexically; map to a number so "older" wins ties
    digits = re.sub(r"\D", "", created or "")[:14]
    return float(digits) if digits else 9e13


@dataclass
class Group:
    keep: dict
    remove: list[dict]
    reasons: list[str] = field(default_factory=list)

    @property
    def members(self) -> list[dict]:
        return [self.keep, *self.remove]

    @property
    def klass(self) -> str:
        pdfs = sum(bool(p.get("drive_file_id")) for p in self.members)
        library = sum(not is_stub(p) for p in self.members)
        if pdfs >= 2:
            return "pdf_duplicates"
        if library >= 2:
            return "library_duplicates"
        if library == 1:
            return "paper_with_stubs"
        return "stubs_only"


@dataclass
class ScanResult:
    groups: list[Group]
    doi_conflicts: list[tuple[dict, dict, str]]   # (a, b, normalised doi) with different real titles
    total: int


# ── scan ────────────────────────────────────────────────────────────────────

class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


def _dois_compatible(a: dict, b: dict) -> bool:
    """Missing, equal, or a preprint next to a journal version. Two different arXiv ids, or two
    different journal DOIs, are two papers."""
    da, db = normalize_doi(a.get("doi")), normalize_doi(b.get("doi"))
    return not da or not db or da == db or is_preprint(da) != is_preprint(db)


def _numbers(t: str) -> list[str]:
    """Arabic and Roman numerals: "Round XIII" and "Round XV" are two papers."""
    return re.findall(r"\b(\d+|[ivxlc]{2,}|[ivx])\b", t)


def _squeeze(t: str) -> str:
    return normalize_title(t).replace(" ", "")


def scan(papers: list[dict]) -> ScanResult:
    by_id = {p["id"]: p for p in papers}
    uf = _UnionFind()
    reasons: dict[frozenset, set[str]] = defaultdict(set)
    conflicts: list[tuple[dict, dict, str]] = []

    def link(a: dict, b: dict, why: str) -> None:
        uf.union(a["id"], b["id"])
        reasons[frozenset((a["id"], b["id"]))].add(why)

    # 1. DOI
    by_doi: dict[str, list[dict]] = defaultdict(list)
    for p in papers:
        n = normalize_doi(p.get("doi"))
        if n:
            by_doi[n].append(p)
    for n, ps in by_doi.items():
        garbage = [p for p in ps if looks_like_garbage_title(p["title"]) and is_stub(p)]
        real = [p for p in ps if p not in garbage]
        clash = False
        for a, b in itertools.combinations(real, 2):
            if title_similarity(a["title"], b["title"]) >= 0.6 or is_truncation(a["title"], b["title"]):
                link(a, b, "doi")
            else:
                conflicts.append((a, b, n))
                clash = True
        # A stub whose "title" is an author list carries no title evidence, only the DOI. Attach it
        # to the paper that owns the DOI; when real titles disagree, the owner is the citation
        # stub(s) (reference DOIs are reliable), never an upload whose DOI may be mis-extracted.
        owners = [p for p in real if not p.get("drive_file_id")] if clash else real
        owner_roots = {uf.find(p["id"]) for p in owners}
        if garbage and len(owner_roots) == 1:
            stub_owned = any(not p.get("drive_file_id") for p in owners)
            for g in garbage:
                # an upload alone is weak evidence (its DOI may come from its own reference list):
                # then the stub's text must share title words with it
                if stub_owned or any(shares_title_words(g["title"], p["title"]) for p in owners):
                    link(g, owners[0], "doi")
        elif garbage and not real:
            for g in garbage[1:]:
                link(g, garbage[0], "doi")

    # 2. identical title
    by_title: dict[str, list[dict]] = defaultdict(list)
    for p in papers:
        t = normalize_title(p.get("title"))
        if len(t.split()) >= 4 and not GENERIC_TITLE.match(t) and not looks_like_garbage_title(p.get("title")):
            by_title[t].append(p)
    for t, ps in by_title.items():
        for b in ps[1:]:
            if _dois_compatible(ps[0], b):
                link(ps[0], b, "title")

    # 3. near-identical or truncated titles, blocked on the first three words
    blocks: dict[str, list[str]] = defaultdict(list)
    for t in by_title:
        blocks[" ".join(t.split()[:3])].append(t)
    for ts in blocks.values():
        if not 2 <= len(ts) <= 500:
            continue
        for ta, tb in itertools.combinations(ts, 2):
            trunc = is_truncation(ta, tb)
            if trunc:
                # a cut-off title is an artefact of PDF extraction; among citation stubs a
                # shorter title is as often a different, earlier paper ("DDPM" vs "DDPM on SO(3)")
                short = ta if len(ta) < len(tb) else tb
                if all(is_stub(p) for p in by_title[short]):
                    continue
            else:
                if _numbers(ta) != _numbers(tb):
                    continue
                if difflib.SequenceMatcher(None, _squeeze(ta), _squeeze(tb)).ratio() < 0.97:
                    continue
            a, b = by_title[ta][0], by_title[tb][0]
            if _dois_compatible(a, b):
                link(a, b, "truncated-title" if trunc else "near-title")

    members: dict[str, list[dict]] = defaultdict(list)
    for pid in uf.parent:
        members[uf.find(pid)].append(by_id[pid])
    groups = []
    for ms in members.values():
        if len(ms) < 2:
            continue
        ms = sorted(ms, key=keep_score, reverse=True)
        ids = {p["id"] for p in ms}
        why = sorted(set().union(*(w for k, w in reasons.items() if k <= ids)))
        groups.append(Group(keep=ms[0], remove=ms[1:], reasons=why))
    groups.sort(key=lambda g: (CLASSES.index(g.klass), -len(g.members), g.keep.get("title") or ""))

    # a conflict is only interesting if the two ended up in different groups
    conflicts = [(a, b, n) for a, b, n in conflicts if uf.find(a["id"]) != uf.find(b["id"])]
    return ScanResult(groups=groups, doi_conflicts=conflicts, total=len(papers))


def wrong_doi_suspects(result: ScanResult) -> list[tuple[dict, dict]]:
    """Uploaded PDFs whose DOI belongs to a differently titled paper (usually one they cite).

    Returns (suspect, owner) pairs: the suspect has a PDF, the owner is a citation stub with a
    real title. Metadata extraction picked the DOI out of the suspect's reference list.
    """
    out = []
    for a, b, _ in result.doi_conflicts:
        for s, o in ((a, b), (b, a)):
            if s.get("drive_file_id") and not o.get("drive_file_id") and not looks_like_garbage_title(o["title"]):
                out.append((s, o))
    seen, uniq = set(), []
    for s, o in out:
        if s["id"] not in seen:
            seen.add(s["id"])
            uniq.append((s, o))
    return uniq
