"""Concept visualisations for Knowledge Chat answers.

The per-paper concept pipeline (``services/concepts.py``) finds the ideas on a
PDF page that a picture would explain and writes a spec for each. Here the same
code runs on the text of a chat answer: every ``## `` section of the answer
plays the part of a page, so each concept knows the section it belongs to and
the chat renders its card at the end of that section. Model routing is the
pipeline's own (Claude Code on the subscription when allowed, else the API key).

The splitter must agree with ``frontend/src/components/kchat/sections.ts``:
section 0 is the text before the first ``## `` heading (possibly empty), every
later section starts with its heading line, and headings inside fenced code
blocks do not split.
"""
from __future__ import annotations

import contextvars
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from services.concepts import ConceptsError, detect_concepts, generate_spec, normalise

log = logging.getLogger(__name__)

MAX_CONCEPTS = 4          # cards per answer; detection may find more
SPEC_CONCURRENCY = 3

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^##\s")
# Concept / structure blocks the model wrote itself are rendered as they are;
# the detector should neither read their JSON nor make a second card for them.
_OWN_BLOCK = re.compile(r"^\s{0,3}(`{3,})(concept|structure)\b.*?^\s{0,3}\1\s*$", re.S | re.M)


def split_sections(text: str) -> list[str]:
    """Split markdown at ``## `` headings outside fenced code blocks."""
    sections: list[str] = [""]
    fence: str | None = None
    lines: list[str] = []
    for line in text.split("\n"):
        m = _FENCE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not line.strip()[len(mark):].strip():
                fence = None
        elif fence is None and _HEADING.match(line):
            sections[-1] = "\n".join(lines)
            sections.append("")
            lines = []
        lines.append(line)
    sections[-1] = "\n".join(lines)
    return sections


def _answer_pages(text: str) -> list[str]:
    return [normalise(_OWN_BLOCK.sub(" ", s)) for s in split_sections(text)]


def _pick(concepts: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep at most *limit* concepts, spread over sections and types."""
    picked: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for c in concepts:                       # first pass: one per type
        if len(picked) < limit and c["type"] not in seen_types:
            picked.append(c)
            seen_types.add(c["type"])
    for c in concepts:
        if len(picked) >= limit:
            break
        if c not in picked:
            picked.append(c)
    return sorted(picked, key=lambda c: (c["page"], concepts.index(c)))


def _one(concept: dict[str, Any], title: str) -> dict[str, Any]:
    out = {
        "label": concept["label"],
        "type": concept["type"],
        "section": concept["page"],
        "anchor": concept.get("anchor", ""),
        "context": concept["context"],
        "spec": None,
        "error": None,
    }
    try:
        out["spec"] = generate_spec(concept, title)
    except Exception as exc:  # one failed card must not lose the others
        log.warning("Chat concept spec failed (%s): %s", concept["label"], exc)
        out["error"] = str(exc)[:500]
    return out


def visualise_answer(text: str, title: str = "", limit: int = MAX_CONCEPTS) -> list[dict[str, Any]]:
    """Detect concepts in an answer and generate a spec for each.

    Returns ``[{label, type, section, anchor, context, spec, error}]`` in
    reading order. Raises ``ConceptsError`` when detection itself fails.
    """
    pages = _answer_pages(text)
    if not any(pages):
        return []
    found = _pick(detect_concepts(pages, title), limit)
    if not found:
        return []
    with ThreadPoolExecutor(max_workers=SPEC_CONCURRENCY) as pool:
        futures = [pool.submit(contextvars.copy_context().run, _one, c, title) for c in found]
        return [f.result() for f in futures]


def repair_concept(concept: dict[str, Any], error: str, title: str = "") -> dict[str, Any]:
    """Regenerate one stored concept's spec, telling the model how it failed."""
    if not concept.get("spec"):
        raise ConceptsError("This concept has no visualisation to repair.")
    detected = {"label": concept["label"], "type": concept["type"], "context": concept["context"]}
    spec = generate_spec(detected, title, previous={"spec": concept["spec"], "error": error})
    return {**concept, "spec": spec, "error": None}
