"""Relevance check of the library search against the real library (read-only).

Runs ~25 realistic queries (known titles, author surnames, a DOI, an arXiv id, typos,
all-caps, a pasted abstract sentence, a highlight, a note, a natural-language question)
and reports whether the expected paper is in the top 3 (and top 10). The cases are
written for Niklas's library; on another library most will simply miss.

    docker exec -w /app papermanager-backend-1 python scripts/search_relevance_check.py
    ... --mode lexical            # one mode only (default: lexical and hybrid)
    ... --impl /tmp/old_search.py # score another implementation of search_papers()
                                  # (e.g. `git show <rev>:backend/db/queries/search.py`)

Exit status 0 always; this is a report, not a gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EDM = "Elucidating the Design Space of Diffusion-Based"
AF3 = "biomolecular interactions with AlphaFold 3"
FM = "Flow Matching for Generative Modeling"
SDE = "Score-Based Generative Modeling through Stochastic"

# (query, any of these title substrings counts as the expected paper, what it tests)
CASES: list[tuple[str, list[str], str]] = [
    ("EDM Karras", [EDM], "acronym + author"),
    ("Karras", [EDM, "Applying Guidance in a Limited Interval", "eDiff-I"], "author surname"),
    ("karras edm", [EDM], "lower case"),
    ("elucidating design space diffusion", [EDM], "title words"),
    ("flow matching", [FM], "short title"),
    ("Lipman flow matching", [FM], "author + title"),
    ("AlphaFold 3", [AF3], "title with number"),
    ("ALPHAFOLD 3", [AF3], "all caps"),
    ("alphafold3", [AF3], "joined spelling"),
    ("Boltz-2", ["Boltz-2: Towards Accurate"], "hyphenated name"),
    ("boltz 1", ["Boltz-1: Democratizing"], "name + number"),
    ("antibody antigen docking benchmark", ["An expanded benchmark for antibody-antigen docking"], "title words"),
    ("Deane antibody language", ["Modelling antibody structures at the speed of language"], "author + topic"),
    ("Abramson", [AF3], "first author"),
    ("10.1038/s41586-024-07487-w", [AF3], "DOI"),
    ("https://doi.org/10.1038/S41586-024-07487-W", [AF3], "DOI URL, upper case"),
    ("2210.02747", [FM], "arXiv id"),
    ("scroe based generative modeling", [SDE], "typo"),
    ("difusion models memorize", ["How Diffusion Models Memorize"], "typo"),
    ("OVER-CONDITIONING", ["CONVERTING DIFFUSIONS TO FLOWS"], "all caps, hyphen"),
    ("Kynkaanniemi", ["Applying Guidance in a Limited Interval"], "author without accents"),
    ("Here we describe our AlphaFold 3 model with a substantially updated diffusion-based architecture",
     [AF3], "pasted abstract sentence"),
    ("current cofolding approaches largely memorise ligand poses from their training data",
     ["Have protein-ligand cofolding methods moved beyond memorisation"], "highlight phrase"),
    ("very cool end to end pipline", ["Agent-Guided De Novo Design of Nanobody Binders"], "note text with typo"),
    ("do cofolding models just memorise ligand poses?",
     ["Have protein-ligand cofolding methods moved beyond memorisation"], "natural-language question"),
    ("Fourier transforms as an inductive bias for protein dynamics", ["Spectral Diffusion for Protein Dynamics"],
     "abstract paraphrase"),
]


def _load(impl: str | None):
    if not impl:
        from db.queries.search import search_papers
        return search_papers, True
    spec = importlib.util.spec_from_file_location("search_impl", impl)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.search_papers, False


def _rank(titles: list[str], expected: list[str]) -> int | None:
    for i, t in enumerate(titles):
        if any(e.lower() in (t or "").lower() for e in expected):
            return i + 1
    return None


def run(mode: str | None, impl: str | None, verbose: bool) -> tuple[int, int, int, float]:
    from db.connection import get_driver

    search_papers, new_api = _load(impl)
    driver = get_driver()
    top3 = top10 = 0
    times = []
    for q, expected, what in CASES:
        t0 = time.perf_counter()
        try:
            if new_api:
                res = search_papers(driver, q=q, limit=10, mode=mode, include_references=False)
            else:
                res = search_papers(driver, q=q, limit=20)
            titles = [r.get("title") or "" for r in res["results"]][:10]
            err = None
        except Exception as exc:  # noqa: BLE001 — the old search crashes on some input
            titles, err = [], str(exc).splitlines()[0][:80]
        times.append((time.perf_counter() - t0) * 1000)
        r = _rank(titles, expected)
        top3 += bool(r and r <= 3)
        top10 += bool(r)
        mark = "ok " if r and r <= 3 else ("~  " if r else "MISS")
        line = f"{mark} {('#' + str(r)) if r else '  -':>4}  {q[:58]:58s}  ({what})"
        if err:
            line += f"  ERROR: {err}"
        print(line)
        if verbose and (not r or r > 3):
            for i, t in enumerate(titles[:3], 1):
                print(f"            {i}. {t[:90]}")
    times.sort()
    return top3, top10, len(CASES), times[len(times) // 2]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["lexical", "hybrid", "semantic"], action="append")
    ap.add_argument("--impl", help="path to a module with search_papers(driver, q=..., limit=...)")
    ap.add_argument("--user", default="Niklas")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the top 3 of every miss")
    args = ap.parse_args()

    from services.auth import set_request_user
    set_request_user(args.user)
    if args.impl:
        modes = [None]
    else:
        modes = args.mode or ["lexical", "hybrid"]
        if any(m in ("hybrid", "semantic") for m in modes):
            from services.library_search import semantic
            semantic.ensure_loaded()
    for mode in modes:
        label = args.impl or f"mode={mode}"
        print(f"\n== {label}")
        top3, top10, n, median_ms = run(mode, args.impl, args.verbose)
        print(f"== {label}: top-3 {top3}/{n} ({100 * top3 / n:.0f}%), top-10 {top10}/{n}, "
              f"median {median_ms:.0f} ms per query")


if __name__ == "__main__":
    main()
