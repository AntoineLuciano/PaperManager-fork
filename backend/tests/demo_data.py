"""Load the demo library (tests/fixtures/demo_library.json) into a Neo4j database.

Used by the ``demo_library`` test fixtures (tests/conftest.py) and by scripts/seed_demo.py.
Everything goes through the app's own query functions (create_paper, upsert_note +
set_mentions, create_claims, save_paper_concepts, add_message, ...), so the graph has the
same shape the app itself writes. The loader only adds; it never deletes anything.
"""
from __future__ import annotations

import json
from pathlib import Path

from neo4j import Driver

DEMO_LIBRARY_PATH = Path(__file__).parent / "fixtures" / "demo_library.json"


def demo_spec() -> dict:
    """The demo library as written in the JSON file."""
    return json.loads(DEMO_LIBRARY_PATH.read_text(encoding="utf-8"))


def _concept_extraction(spec: dict) -> dict:
    """The JSON's concept map entry in the form services/concept_map.py hands to save_paper_concepts."""
    from services.concept_map import concept_key

    concepts = []
    for c in spec["concepts"]:
        key = concept_key(c["name"])
        concepts.append({
            "key": key,
            "name": c["name"],
            "kind": c["kind"],
            "definition": c.get("definition", ""),
            "aliases": c.get("aliases", []),
            "alias_keys": sorted({concept_key(a) for a in c.get("aliases", [])} - {key, ""}),
            "role": c["role"],
            "in_paper": c.get("in_paper", ""),
        })
    relations = [
        {"source": concept_key(r["source"]), "target": concept_key(r["target"]),
         "type": r["type"], "evidence": r.get("evidence", "")}
        for r in spec["relations"]
    ]
    return {"concepts": concepts, "relations": relations}


def load_demo_library(driver: Driver, spec: dict | None = None) -> dict:
    """Write the demo library and return the ids it created, keyed like the JSON:

    ``{"papers": {key: id}, "people": {name: id}, "projects": {key: id}, "notes": {paper_key: id},
    "claims": {paper_key: [id, ...]}, "concepts": {name: id}, "conversations": {key: id},
    "users": [name, ...], "spec": <the JSON>}``
    """
    from db.queries.claims import create_claims
    from db.queries.concept_map import save_paper_concepts
    from db.queries.conversations import add_message, create_conversation
    from db.queries.notes import set_mentions, upsert_note
    from db.queries.papers import create_paper, update_paper
    from db.queries.people import get_or_create_person, link_author
    from db.queries.projects import add_paper_to_project, add_project_member, create_project
    from db.queries.references import create_or_link_reference
    from db.queries.tags import tag_paper
    from db.queries.topics import link_paper_topic
    from db.queries.users import (
        get_or_create_user,
        link_conversation_started_by,
        link_note_written_by,
        link_paper_added_by,
        set_user_admin,
    )
    from services.note_parser import parse_mentions

    spec = spec or demo_spec()
    ids: dict = {"papers": {}, "people": {}, "projects": {}, "notes": {}, "claims": {},
                 "concepts": {}, "conversations": {}, "users": [], "spec": spec}

    for user in spec["users"]:
        get_or_create_user(driver, user["name"])
        set_user_admin(driver, user["name"], bool(user.get("is_admin")))
        with driver.session() as session:
            session.run("MATCH (u:User {name: $name}) SET u.color = $color",
                        name=user["name"], color=user.get("color")).consume()
        ids["users"].append(user["name"])

    for p in spec["papers"]:
        paper = create_paper(driver, {k: p.get(k) for k in (
            "title", "year", "doi", "abstract", "summary", "venue", "document_type", "metadata_source")})
        pid = ids["papers"][p["key"]] = paper["id"]
        extra = {k: p[k] for k in ("reading_status", "bookmarked") if k in p}
        if extra:
            update_paper(driver, pid, extra)
        for name in p.get("authors", []):
            person = get_or_create_person(driver, name)
            ids["people"][name] = person["id"]
            link_author(driver, pid, person["id"])
        for topic in p.get("topics", []):
            link_paper_topic(driver, pid, topic)
        for tag in p.get("tags", []):
            tag_paper(driver, pid, tag)
        if p.get("added_by"):
            link_paper_added_by(driver, pid, p["added_by"])

    with driver.session() as session:
        for c in spec["citations"]:
            session.run(
                "MATCH (a:Paper {id: $a}), (b:Paper {id: $b}) MERGE (a)-[:CITES]->(b)",
                a=ids["papers"][c["from"]], b=ids["papers"][c["to"]],
            ).consume()
    for ref in spec.get("external_references", []):
        node, _ = create_or_link_reference(driver, ids["papers"][ref["cited_by"]], ref)
        ids["papers"][ref["key"]] = node["id"]
        tag_paper(driver, node["id"], "from-references")

    for proj in spec["projects"]:
        project = create_project(driver, {"name": proj["name"], "description": proj.get("description")})
        ids["projects"][proj["key"]] = project["id"]
        for m in proj["members"]:
            add_project_member(driver, project["id"], m["user"], role=m["role"])
        for key in proj["papers"]:
            add_paper_to_project(driver, ids["papers"][key], project["id"])

    for n in spec["notes"]:
        note = upsert_note(driver, ids["papers"][n["paper"]], n["content"])
        mentions = parse_mentions(n["content"])
        set_mentions(driver, note["id"], mentions["people"], mentions["topics"])
        if n.get("author"):
            link_note_written_by(driver, note["id"], n["author"])
        ids["notes"][n["paper"]] = note["id"]

    for c in spec["claims"]:
        created = create_claims(driver, ids["papers"][c["paper"]], [{"text": c["text"], "type": c["type"]}])
        ids["claims"].setdefault(c["paper"], []).extend(x["id"] for x in created)

    for cm in spec["concept_maps"]:
        save_paper_concepts(driver, ids["papers"][cm["paper"]], _concept_extraction(cm))
    with driver.session() as session:
        ids["concepts"] = {r["name"]: r["id"] for r in session.run(
            "MATCH (p:Paper)-[:DISCUSSES]->(c:MapConcept) WHERE p.id IN $pids "
            "RETURN DISTINCT c.name AS name, c.id AS id",
            pids=list(ids["papers"].values()),
        )}

    for conv in spec["conversations"]:
        c = create_conversation(driver, conv["title"])
        ids["conversations"][conv["key"]] = c["id"]
        if conv.get("started_by"):
            link_conversation_started_by(driver, c["id"], conv["started_by"])
        for msg in conv["messages"]:
            add_message(driver, c["id"], msg["role"], msg["content"],
                        [ids["papers"][k] for k in msg.get("papers", [])], max(1, len(msg["content"]) // 4))

    return ids
