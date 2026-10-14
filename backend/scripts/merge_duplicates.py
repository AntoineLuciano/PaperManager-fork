#!/usr/bin/env python
"""Find and merge duplicate papers from the command line.

Run inside the backend container (the API need not be up; this talks to Neo4j directly):

    docker exec -w /app papermanager-backend-1 python scripts/merge_duplicates.py scan
    docker exec -w /app papermanager-backend-1 python scripts/merge_duplicates.py merge \\
        --classes pdf_duplicates,library_duplicates,paper_with_stubs            # dry run
    docker exec -w /app papermanager-backend-1 python scripts/merge_duplicates.py merge \\
        --classes pdf_duplicates,library_duplicates,paper_with_stubs --apply
    docker exec -w /app papermanager-backend-1 python scripts/merge_duplicates.py fix-dois [--apply]

Classes (services/duplicate_scan.py): pdf_duplicates (two or more PDFs of one paper),
library_duplicates (two or more of the user's own entries), paper_with_stubs (one library paper
plus citation stubs), stubs_only (citation stubs among themselves).

``merge --apply`` first writes ``scripts/merge_logs/merge_backup_<time>.json`` — every affected node with its
properties, relationships and child nodes — then merges group by group and finally checks that
every neighbour of every removed node now hangs on the keeper. Results go to
``scripts/merge_logs/merge_<time>.jsonl``. ``--exclude`` skips groups containing the given id prefixes.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.connection import get_driver  # noqa: E402
from services.duplicate_scan import (  # noqa: E402
    CLASSES, SCAN_QUERY, normalize_doi, normalize_title, scan, shares_title_words, title_similarity,
    wrong_doi_suspects,
)
from services.paper_merge import OWNED_CHILDREN, merge_papers  # noqa: E402

LOGS = Path(__file__).resolve().parent / "merge_logs"   # gitignored; visible on the host via the /app mount
STAMP = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def say(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def load(driver) -> list[dict]:
    with driver.session() as s:
        return s.run(SCAN_QUERY).data()


def short(p: dict) -> str:
    flags = [f for f, on in (("PDF", p.get("drive_file_id")), ("note", p.get("notes")),
                             ("proj", p.get("projects"))) if on]
    return f"{p['id'][:8]} [{','.join(flags) or 'stub'}] {(p.get('title') or '')[:70]!r} doi={p.get('doi')}"


# ── scan ────────────────────────────────────────────────────────────────────

def cmd_scan(args, driver) -> None:
    r = scan(load(driver))
    counts = {c: [g for g in r.groups if g.klass == c] for c in CLASSES}
    say(f"{r.total} papers, {len(r.groups)} duplicate groups, "
        f"{sum(len(g.members) for g in r.groups)} nodes involved")
    for c, gs in counts.items():
        say(f"  {c:20s} {len(gs):4d} groups, {sum(len(g.remove) for g in gs):4d} to remove")
    sus = wrong_doi_suspects(r)
    say(f"  wrong-DOI suspects   {len(sus):4d}")
    if args.show:
        for c in args.show.split(","):
            for g in counts[c]:
                print(f"\n[{c}] {', '.join(g.reasons)}\n  keep   {short(g.keep)}")
                for p in g.remove:
                    print(f"  remove {short(p)}")
        for s, o in sus:
            print(f"\n[wrong DOI] {short(s)}\n  DOI belongs to {short(o)}")
    if args.json:
        out = {"total": r.total, "groups": [{"class": g.klass, "reasons": g.reasons, "keep": g.keep,
                                              "remove": g.remove} for g in r.groups],
               "wrong_doi_suspects": [{"paper": s, "owner": o} for s, o in sus]}
        Path(args.json).write_text(json.dumps(out, indent=1, default=str))
        say(f"wrote {args.json}")


# ── merge ───────────────────────────────────────────────────────────────────

NEIGHBOURS = """
UNWIND $ids AS pid
MATCH (p:Paper {id: pid})-[r]-(x)
RETURN pid, type(r) AS type, startNode(r) = p AS out, x.id AS other, labels(x) AS labels,
       properties(r) AS rel_props,
       CASE WHEN type(r) IN $child_types THEN properties(x) END AS child
"""


def backup(driver, ids: list[str], path: Path) -> dict:
    child_types = [*OWNED_CHILDREN, "HAS_NOTE", "HAS_ANNOTATION"]
    with driver.session() as s:
        nodes = {r["id"]: r["props"] for r in
                 s.run("UNWIND $ids AS pid MATCH (p:Paper {id: pid}) RETURN pid AS id, properties(p) AS props",
                       ids=ids).data()}
        rels = s.run(NEIGHBOURS, ids=ids, child_types=child_types).data()
    data = {"created": STAMP, "nodes": nodes, "relationships": rels}
    path.write_text(json.dumps(data, default=str))
    return data


def verify(driver, group_ids: list[str], keep_id: str, before: dict, remap: dict[str, str] | None = None) -> list[str]:
    """Every (type, direction, neighbour) of a removed node must now exist on the keeper,
    except links inside the group, PDF-derived children (moved or deleted by rule) and notes
    (moved or merged)."""
    members = set(group_ids)
    skip = {*OWNED_CHILDREN, "HAS_NOTE"}
    remap = remap or {}
    want = {(r["type"], r["out"], remap.get(r["other"], r["other"])) for r in before["relationships"]
            if r["pid"] in members and r["pid"] != keep_id and r["type"] not in skip and r["other"] is not None
            and remap.get(r["other"], r["other"]) not in members}
    with driver.session() as s:
        have = {(r["type"], r["out"], r["other"]) for r in s.run(NEIGHBOURS, ids=[keep_id], child_types=[]).data()}
        gone = s.run("UNWIND $ids AS i MATCH (p:Paper {id: i}) RETURN collect(i) AS left",
                     ids=[i for i in group_ids if i != keep_id]).single()["left"]
    problems = [f"missing on keeper: {t} {'->' if o else '<-'} {x}" for t, o, x in sorted(want - have)]
    problems += [f"not deleted: {i}" for i in gone]
    return problems


def cmd_merge(args, driver) -> None:
    classes = args.classes.split(",")
    bad = set(classes) - set(CLASSES)
    if bad:
        sys.exit(f"unknown classes {sorted(bad)}; choose from {CLASSES}")
    excl = [e for e in (args.exclude or "").split(",") if e]
    r = scan(load(driver))
    groups = [g for g in r.groups if g.klass in classes
              and not any(p["id"].startswith(e) for e in excl for p in g.members)]
    if args.limit:
        groups = groups[: args.limit]
    say(f"{len(groups)} groups, {sum(len(g.remove) for g in groups)} papers to merge away "
        f"({'APPLY' if args.apply else 'dry run'})")
    if not groups:
        return

    before = None
    if args.apply:
        LOGS.mkdir(exist_ok=True)
        bpath = LOGS / f"merge_backup_{STAMP}.json"
        before = backup(driver, sorted({p["id"] for g in groups for p in g.members}), bpath)
        say(f"backup: {bpath} ({len(before['nodes'])} nodes, {len(before['relationships'])} relationships)")
    remap = {p["id"]: g.keep["id"] for g in groups for p in g.remove}   # removed id -> its keeper
    out = (LOGS / f"merge_{STAMP}.jsonl") if args.apply else None
    totals = {"groups": 0, "removed": 0, "moved": 0, "problems": 0, "trashed": 0}
    for i, g in enumerate(groups, 1):
        try:
            rep = merge_papers(driver, g.keep["id"], [p["id"] for p in g.remove],
                               dry_run=not args.apply, trash_drive_files=not args.keep_drive_files)
        except Exception as exc:
            say(f"[{i}/{len(groups)}] FAILED {short(g.keep)}: {exc}")
            totals["problems"] += 1
            continue
        problems = verify(driver, [p["id"] for p in g.members], g.keep["id"], before, remap) if args.apply else []
        totals["groups"] += 1
        totals["removed"] += len(rep.removed)
        totals["moved"] += rep.relationships_moved
        totals["problems"] += len(problems)
        totals["trashed"] += len(rep.drive_trashed)
        extra = []
        if rep.title_replaced:
            extra.append("title←full")
        if rep.notes_merged:
            extra.append(f"{rep.notes_merged} note merged")
        if rep.children_deleted:
            extra.append("dropped " + ",".join(f"{v} {k}" for k, v in rep.children_deleted.items()))
        if rep.drive_trash:
            extra.append(f"{len(rep.drive_trash)} Drive file(s) to trash")
        say(f"[{i}/{len(groups)}] {g.klass}: keep {short(g.keep)} ← {len(rep.removed)} | "
            f"{rep.relationships_moved} rels {' | '.join(extra)}")
        for w in rep.warnings + problems:
            say(f"      ! {w}")
        if out:
            with out.open("a") as f:
                f.write(json.dumps({"class": g.klass, "reasons": g.reasons, "keep": g.keep["id"],
                                    "remove": [p["id"] for p in g.remove], "report": rep.as_dict(),
                                    "problems": problems}, default=str) + "\n")
    say(f"done: {totals}")
    if out:
        say(f"log: {out}")


# ── repair ──────────────────────────────────────────────────────────────────

def cmd_repair(args, driver) -> None:
    """Make every keeper of a merge log carry exactly the relationships its group had in the
    backup (PDF-derived children and notes excepted: those were moved or merged by rule)."""
    backup_ = json.loads(Path(args.backup).read_text())
    groups = [json.loads(l) for l in Path(args.log).read_text().splitlines() if l.strip()]
    skip = {*OWNED_CHILDREN, "HAS_NOTE"}
    rows_by_pid: dict[str, list[dict]] = {}
    for r in backup_["relationships"]:
        rows_by_pid.setdefault(r["pid"], []).append(r)
    remap = {rid: g["keep"] for g in groups for rid in g["remove"]}   # removed id -> its keeper
    total_add = total_del = 0
    for g in groups:
        k, members = g["keep"], {g["keep"], *g["remove"]}
        expected: dict[tuple, dict] = {}
        for pid in members:
            for r in rows_by_pid.get(pid, []):
                other = remap.get(r["other"], r["other"])
                if r["type"] in skip or other in members:
                    continue
                expected.setdefault((r["type"], r["out"], other), {**r, "other": other})
        with driver.session() as ses:
            current = {(r["type"], r["out"], r["other"]): r for r in
                       ses.run(NEIGHBOURS, ids=[k], child_types=[]).data() if r["type"] not in skip}
        add = [expected[key] for key in expected.keys() - current.keys()]
        delete = [current[key] for key in current.keys() - expected.keys()]
        total_add += len(add)
        total_del += len(delete)
        if add or delete:
            say(f"{k[:8]} +{len(add)} -{len(delete)}  "
                f"add {sorted(collections.Counter(r['type'] for r in add).items())} "
                f"del {sorted(collections.Counter(r['type'] for r in delete).items())}")
        if not args.apply or not (add or delete):
            continue
        with driver.session() as ses:
            tx = ses.begin_transaction()
            try:
                by = collections.defaultdict(list)
                for r in add:
                    by[(r["type"], r["out"], r["labels"][0])].append({"other": r["other"], "props": r["rel_props"] or {}})
                for (t, out, label), rows in by.items():
                    assert re.fullmatch(r"[A-Z][A-Z0-9_]*", t) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", label)
                    rel = f"(k)-[nr:{t}]->(x)" if out else f"(x)-[nr:{t}]->(k)"
                    tx.run(f"UNWIND $rows AS row MATCH (k:Paper {{id: $k}}), (x:{label} {{id: row.other}}) "
                           f"MERGE {rel} SET nr += row.props", rows=rows, k=k)
                byd = collections.defaultdict(list)
                for r in delete:
                    byd[(r["type"], r["out"])].append(r["other"])
                for (t, out), others in byd.items():
                    assert re.fullmatch(r"[A-Z][A-Z0-9_]*", t)
                    pat = f"(k:Paper {{id: $k}})-[r:{t}]->(x)" if out else f"(x)-[r:{t}]->(k:Paper {{id: $k}})"
                    tx.run(f"MATCH {pat} WHERE x.id IN $others DELETE r", k=k, others=others)
                tx.commit()
            except Exception:
                tx.rollback()
                raise
    say(f"{'repaired' if args.apply else 'would repair'}: +{total_add} relationships, -{total_del} wrong ones, "
        f"{len(groups)} keepers")


# ── fix-dois ────────────────────────────────────────────────────────────────

def _lookup_identifier(title: str) -> tuple[str | None, str | None]:
    """(identifier, matched title) from Semantic Scholar, falling back to arXiv."""
    for attempt in range(3):
        try:
            r = httpx.get("https://api.semanticscholar.org/graph/v1/paper/search",
                          params={"query": title, "fields": "title,externalIds", "limit": 5}, timeout=20)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            for d in (r.json().get("data") or []) if r.status_code == 200 else []:
                if title_similarity(title, d.get("title") or "") >= 0.9:
                    ext = d.get("externalIds") or {}
                    if ext.get("DOI"):
                        return ext["DOI"], d["title"]
                    if ext.get("ArXiv"):
                        return f"arXiv:{ext['ArXiv']}", d["title"]
            break
        except httpx.HTTPError:
            time.sleep(3)
    try:
        r = httpx.get("https://export.arxiv.org/api/query",
                      params={"search_query": f'ti:"{title}"', "max_results": 5}, timeout=30)
        for entry in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
            t = re.sub(r"\s+", " ", re.search(r"<title>(.*?)</title>", entry, re.S).group(1)).strip()
            aid = re.search(r"<id>https?://arxiv.org/abs/([^<v]+)", entry)
            if aid and title_similarity(title, t) >= 0.9:
                return f"arXiv:{aid.group(1)}", t
    except Exception:
        pass
    return None, None


def _arxiv_titles(ids: list[str]) -> dict[str, str]:
    """arXiv id -> title, 50 ids per request."""
    out: dict[str, str] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = httpx.get("https://export.arxiv.org/api/query",
                      params={"id_list": ",".join(chunk), "max_results": len(chunk)}, timeout=60)
        for entry in re.findall(r"<entry>(.*?)</entry>", r.text, re.S):
            aid = re.search(r"<id>https?://arxiv.org/abs/([0-9.]+)", entry)
            t = re.search(r"<title>(.*?)</title>", entry, re.S)
            if aid and t:
                out[aid.group(1)] = re.sub(r"\s+", " ", t.group(1)).strip()
        time.sleep(3)
    return out


def arxiv_mismatches(papers: list[dict]) -> list[tuple[dict, dict]]:
    """Uploads whose arXiv id resolves to a different title on arXiv."""
    ups = {normalize_doi(p.get("doi")).split(":", 1)[1]: p for p in papers
           if p.get("drive_file_id") and (normalize_doi(p.get("doi")) or "").startswith("arxiv:")}
    titles = _arxiv_titles(sorted(ups))
    bad = []
    for aid, p in ups.items():
        t = titles.get(aid)
        a, b = normalize_title(p["title"]), normalize_title(t or "")
        if t and (a.startswith(b) or b.startswith(a)):
            continue
        if t and title_similarity(p["title"], t) < 0.5 and not shares_title_words(p["title"], t, 3):
            bad.append((p, {"id": f"arXiv:{aid}", "title": t, "doi": f"arXiv:{aid}"}))
    return bad


def cmd_fix_dois(args, driver) -> None:
    papers = load(driver)
    sus = wrong_doi_suspects(scan(papers))
    if args.verify_arxiv:
        known = {s["id"] for s, _ in sus}
        extra = [(s, o) for s, o in arxiv_mismatches(papers) if s["id"] not in known]
        say(f"arXiv check: {len(extra)} further uploads whose arXiv id names another paper")
        sus += extra
    say(f"{len(sus)} uploaded papers carry another paper's DOI ({'APPLY' if args.apply else 'dry run'})")
    log = (LOGS / f"fix_dois_{STAMP}.jsonl") if args.apply else None
    for s, owner in sus:
        if not s.get("id") or s["id"].startswith("arXiv:"):
            continue
        if len(normalize_title(s["title"]).split()) < 4:
            say(f"SKIP {short(s)}: the title itself looks like a page header — fix the title by hand first")
            continue
        with driver.session() as ses:
            head = ses.run("MATCH (p:Paper {id: $id}) RETURN left(coalesce(p.raw_text, ''), 3000) AS h",
                           id=s["id"]).single()["h"]
        h = normalize_title(head)
        if normalize_title(owner["title"])[:40] in h and normalize_title(s["title"])[:40] not in h:
            say(f"SKIP {short(s)}: the PDF text starts with the DOI owner's title — the title may be the wrong field")
            continue
        new, matched = _lookup_identifier(s["title"])
        if new and normalize_doi(new) == normalize_doi(s.get("doi")):
            new = None
        action = f"set doi={new} (matched {matched!r})" if new else "clear doi (no match found)"
        say(f"{short(s)}\n      DOI belongs to {owner['title'][:70]!r} → {action}")
        if args.apply:
            with driver.session() as ses:
                ses.run("MATCH (p:Paper {id: $id}) SET p.doi = $doi, p.updated_at = $now",
                        id=s["id"], doi=new, now=datetime.now(timezone.utc).isoformat())
            with log.open("a") as f:
                f.write(json.dumps({"id": s["id"], "title": s["title"], "old_doi": s.get("doi"),
                                    "new_doi": new, "doi_owner": owner["id"]}) + "\n")
        time.sleep(1.5)
    if log:
        say(f"log: {log}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan", help="report duplicate groups")
    p.add_argument("--show", help=f"print the groups of these classes ({','.join(CLASSES)})")
    p.add_argument("--json", help="write the full scan to this file")
    p = sub.add_parser("merge", help="merge duplicate groups (dry run unless --apply)")
    p.add_argument("--classes", required=True, help=f"comma-separated: {','.join(CLASSES)}")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--exclude", help="comma-separated id prefixes whose groups are skipped")
    p.add_argument("--limit", type=int, help="only the first N groups")
    p.add_argument("--keep-drive-files", action="store_true", help="do not move duplicate PDFs to the Drive trash")
    p = sub.add_parser("fix-dois", help="replace DOIs that belong to a cited paper")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--verify-arxiv", action="store_true",
                   help="also check every uploaded paper's arXiv id against the title arXiv gives for it")
    p = sub.add_parser("repair", help="restore keepers' relationships from a merge backup")
    p.add_argument("--backup", required=True)
    p.add_argument("--log", required=True, help="the merge_<time>.jsonl of that run")
    p.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    driver = get_driver()
    {"scan": cmd_scan, "merge": cmd_merge, "fix-dois": cmd_fix_dois, "repair": cmd_repair}[args.cmd](args, driver)


if __name__ == "__main__":
    main()
