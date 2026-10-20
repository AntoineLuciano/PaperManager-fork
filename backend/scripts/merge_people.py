#!/usr/bin/env python
"""Find and merge duplicate Person nodes.

    docker exec -w /app papermanager-backend-1 python scripts/merge_people.py            # list groups
    docker exec -w /app papermanager-backend-1 python scripts/merge_people.py --apply

Two names are one person when they agree after
  - stripping accents, punctuation and case ("Alán Aspuru-Guzik" = "Al'an Aspuru-Guzik"), or
  - additionally dropping middle initials, when both first names are spelled out
    ("Nele P. Quast" = "Nele Quast"; "B. E. Correia" is left alone: an initial alone is too weak).
The keeper is the node with an S2 id / tracking / most relationships; it adopts the others'
missing properties and every relationship (MERGE, so nothing doubles). ``--exclude`` takes
id prefixes whose groups are skipped. A JSON backup of every affected node is written first.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.connection import get_driver  # noqa: E402

LOGS = Path(__file__).resolve().parent / "merge_logs"
_TYPE_RE = re.compile(r"^[A-Z_]+$")


def _ascii(name: str) -> str:
    t = unicodedata.normalize("NFKD", name or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[’'`´]", "", t)
    return re.sub(r"[^a-z]+", " ", t).strip()


def exact_key(name: str) -> str:
    return _ascii(name).replace(" ", "")


def loose_key(name: str) -> str | None:
    """First + last name without middle initials; None if the first name is only an initial."""
    words = _ascii(name).split()
    if len(words) < 2 or len(words[0]) < 2:
        return None
    middle = words[1:-1]
    if any(len(w) > 1 for w in middle):  # a spelled-out middle name: keep it in the key
        return None
    return f"{words[0]} {words[-1]}"


def keep_score(p: dict) -> tuple:
    clean = not re.search(r"[´’`]", p["name"] or "")  # "Jim´enez" is a PDF-extraction artefact
    return (bool(p.get("s2_author_id")), bool(p.get("tracked")), clean, p["degree"], len(p["name"] or ""))


def groups(people: list[dict]) -> list[list[dict]]:
    parent = {p["id"]: p["id"] for p in people}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for keyf in (exact_key, loose_key):
        buckets: dict[str, list[dict]] = defaultdict(list)
        for p in people:
            k = keyf(p["name"])
            if k:
                buckets[k].append(p)
        for ps in buckets.values():
            for q in ps[1:]:
                parent[find(q["id"])] = find(ps[0]["id"])
    out: dict[str, list[dict]] = defaultdict(list)
    for p in people:
        out[find(p["id"])].append(p)
    return [sorted(g, key=keep_score, reverse=True) for g in out.values() if len(g) > 1]


def merge(tx, keep_id: str, remove_id: str) -> int:
    rec = tx.run("MATCH (k:Person {id: $k}), (r:Person {id: $r}) RETURN properties(k) AS k, properties(r) AS r",
                 k=keep_id, r=remove_id).single()
    keep, rem = dict(rec["k"]), dict(rec["r"])
    fill = {k: v for k, v in rem.items() if k not in ("id", "name") and v not in (None, "", []) and keep.get(k) in (None, "", [])}
    if fill:
        tx.run("MATCH (k:Person {id: $k}) SET k += $p", k=keep_id, p=fill)
    moved = 0
    for direction in ("OUT", "IN"):
        any_pat = "(r:Person {id: $r})-[rel]->(x)" if direction == "OUT" else "(x)-[rel]->(r:Person {id: $r})"
        for t in [x["t"] for x in tx.run(f"MATCH {any_pat} RETURN DISTINCT type(rel) AS t", r=remove_id).data()]:
            if not _TYPE_RE.match(t):
                raise ValueError(f"unexpected relationship type {t!r}")
            pat = any_pat.replace("[rel]", f"[rel:{t}]")
            new = f"(k)-[nr:{t}]->(x)" if direction == "OUT" else f"(x)-[nr:{t}]->(k)"
            moved += tx.run(f"""
                MATCH {pat}, (k:Person {{id: $k}})
                WHERE x.id IS NULL OR (x.id <> $k AND x.id <> $r)
                MERGE {new} ON CREATE SET nr = properties(rel)
                DELETE rel RETURN count(rel) AS n
            """, r=remove_id, k=keep_id).single()["n"]
    tx.run("MATCH (r:Person {id: $r}) DETACH DELETE r", r=remove_id)
    return moved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--exclude", default="")
    args = ap.parse_args()
    excl = [e for e in args.exclude.split(",") if e]
    driver = get_driver()
    with driver.session() as s:
        people = s.run("MATCH (p:Person) RETURN p.id AS id, p.name AS name, p.s2_author_id AS s2_author_id, "
                       "p.tracked AS tracked, COUNT { (p)--() } AS degree").data()
    gs = [g for g in groups(people) if not any(p["id"].startswith(e) for p in g for e in excl)]
    print(f"{len(people)} people, {len(gs)} duplicate groups")
    for g in gs:
        print(f"  keep {g[0]['id'][:8]} {g[0]['name']!r} ({g[0]['degree']})  <- "
              + ", ".join(f"{p['id'][:8]} {p['name']!r} ({p['degree']})" for p in g[1:]))
    if not args.apply or not gs:
        return
    LOGS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ids = [p["id"] for g in gs for p in g]
    with driver.session() as s:
        backup = s.run("""
            MATCH (p:Person) WHERE p.id IN $ids
            OPTIONAL MATCH (p)-[r]-(x)
            RETURN properties(p) AS person,
                   collect({type: type(r), out: startNode(r) = p, other: x.id, props: properties(r)}) AS rels
        """, ids=ids).data()
        (LOGS / f"people_backup_{stamp}.json").write_text(json.dumps(backup, default=str, indent=1))
        print(f"backup: {LOGS / f'people_backup_{stamp}.json'}")
        for g in gs:
            for p in g[1:]:
                n = s.execute_write(merge, g[0]["id"], p["id"])
                print(f"  merged {p['name']!r} -> {g[0]['name']!r} ({n} rels)")


if __name__ == "__main__":
    main()
