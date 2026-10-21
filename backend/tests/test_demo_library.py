"""Read-only tests against the demo library (tests/fixtures/demo_library.json).

The graph is loaded once for this module (demo_library fixture); nothing here writes to it.
Tests that change the graph are in test_demo_library_writes.py.

Who sees what (db/queries/visibility.py): demo_alice is a member of "Generative models for
protein design", demo_bob of that and of his private "Sequence models reading group" (which
holds the Transformer paper), demo_carol of neither, so she sees only papers outside projects.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from db.connection import get_driver
from main import app


def _client(headers=None):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers or {})


def _keys(ids, rows):
    """Map result rows back to demo keys (rows from outside the demo library map to None)."""
    by_id = {v: k for k, v in ids["papers"].items()}
    return [by_id.get(r["id"]) for r in rows]


# ── The loaded graph ──────────────────────────────────────────────────────────

def test_demo_library_shape(demo_library):
    spec = demo_library["spec"]
    with get_driver().session() as s:
        counts = {r["label"]: r["n"] for r in s.run(
            "MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS n")}
        rels = {r["type"]: r["n"] for r in s.run(
            "MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n")}
    # 11 papers in the JSON plus the U-Net reference stub
    assert counts["Paper"] == len(spec["papers"]) + len(spec["external_references"]) == 12
    assert counts["Project"] == 2
    assert counts["User"] == 3
    assert counts["Claim"] == len(spec["claims"])
    assert counts["Note"] == len(spec["notes"])
    assert counts["Conversation"] == 1 and counts["Message"] == 2
    assert rels["CITES"] == len(spec["citations"]) + 1
    assert rels["MEMBER_OF"] == 3
    assert rels["IN_PROJECT"] == 9
    assert {"DISCUSSES", "CONCEPT_LINK", "AUTHORED_BY", "ABOUT", "TAGGED", "MENTIONS", "HAS_CLAIM"} <= set(rels)


def test_note_mentions_link_people_and_topics(demo_library):
    with get_driver().session() as s:
        rows = s.run(
            "MATCH (n:Note {id: $id})-[:MENTIONS]->(x) RETURN labels(x)[0] AS label, x.name AS name",
            id=demo_library["notes"]["ddpm"],
        ).data()
    assert {(r["label"], r["name"]) for r in rows} == {
        ("Person", "Yang Song"), ("Topic", "Diffusion Models"), ("Topic", "Generative Modeling"),
    }


# ── Search: ranking, filters, visibility ──────────────────────────────────────

async def _search(headers, **params):
    async with _client(headers) as c:
        r = await c.get("/search", params=params)
    assert r.status_code == 200
    return r.json()["results"]


async def test_search_ranks_title_match_first(demo_library, auth_headers):
    alice = auth_headers("demo_alice")
    assert _keys(demo_library, await _search(alice, q="flow matching"))[0] == "flow_matching"
    top_two = _keys(demo_library, await _search(alice, q="AlphaFold"))[:2]
    assert set(top_two) == {"alphafold2", "alphafold3"}


async def test_search_filters(demo_library, auth_headers):
    alice = auth_headers("demo_alice")
    keys = lambda rows: set(_keys(demo_library, rows))  # noqa: E731

    assert keys(await _search(alice, topic="Protein Structure Prediction")) == {"alphafold2", "alphafold3", "esm2"}
    assert keys(await _search(alice, tag="protein", year_min=2023)) == {"alphafold3", "rfdiffusion", "esm2"}
    assert keys(await _search(alice, reading_status="reading")) == {"score_sde", "alphafold3"}
    assert keys(await _search(alice, project_id=demo_library["projects"]["protein_gen"], limit=50)) == {
        "ddpm", "score_sde", "edm", "flow_matching", "alphafold2", "alphafold3", "rfdiffusion", "esm2",
    }
    assert keys(await _search(alice, q="diffusion", year_max=2021)) == {"ddpm", "ddpm_stub", "score_sde"}
    # The Transformer paper is bookmarked too, but it sits in Bob's private project.
    assert keys(await _search(alice, bookmarked="true")) == {"ddpm", "flow_matching", "rfdiffusion"}
    assert "transformer" in keys(await _search(auth_headers("demo_bob"), bookmarked="true"))


async def test_search_matches_notes(demo_library, auth_headers):
    rows = await _search(auth_headers("demo_alice"), q="RoseTTAFold")
    hit = next(r for r in rows if r["id"] == demo_library["papers"]["rfdiffusion"])
    assert hit["matched_in"] == "note+paper"


async def test_search_hides_project_papers_from_non_members(demo_library, auth_headers):
    rows = await _search(auth_headers("demo_carol"), q="diffusion")
    assert set(_keys(demo_library, rows)) == {"ddpm_stub"}


# ── Project concept map ───────────────────────────────────────────────────────

async def test_concept_map_endpoint(demo_library, auth_headers):
    ids = demo_library
    pid = ids["projects"]["protein_gen"]
    async with _client(auth_headers("demo_alice")) as c:
        r = await c.get(f"/projects/{pid}/concept-map")
    assert r.status_code == 200
    body = r.json()
    assert len(body["papers"]) == 8
    concepts = {c["name"]: c for c in body["concepts"]}
    assert set(concepts) == {"Diffusion Models", "Denoising Score Matching", "Score Function",
                             "Flow Matching", "Protein Design", "Protein Structure Prediction"}
    diffusion = concepts["Diffusion Models"]["id"]
    discussing = {d["paper_id"] for d in body["discusses"] if d["concept_id"] == diffusion}
    assert discussing == {ids["papers"][k] for k in ("ddpm", "score_sde", "flow_matching", "rfdiffusion")}
    link = next(l for l in body["concept_links"]
                if l["source"] == concepts["Flow Matching"]["id"] and l["target"] == diffusion)
    assert link["type"] == "alternative_to"
    assert [s["paper_id"] for s in link["support"]] == [ids["papers"]["flow_matching"]]
    cites = {(c["source"], c["target"]) for c in body["citations"]}
    p = ids["papers"]
    assert {(p["edm"], p["ddpm"]), (p["alphafold3"], p["alphafold2"]), (p["rfdiffusion"], p["alphafold2"])} <= cites
    # Citations leaving the project (DDPM -> Transformer) are not part of its map.
    assert (p["ddpm"], p["transformer"]) not in cites


async def test_concept_map_is_members_only(demo_library, auth_headers):
    pid = demo_library["projects"]["protein_gen"]
    async with _client(auth_headers("demo_carol")) as c:
        assert (await c.get(f"/projects/{pid}/concept-map")).status_code == 404
    async with _client() as c:
        assert (await c.get(f"/projects/{pid}/concept-map")).status_code == 401


# ── Graph endpoint ────────────────────────────────────────────────────────────

async def test_graph_paper_neighbourhood(demo_library, auth_headers):
    p = demo_library["papers"]
    async with _client(auth_headers("demo_alice")) as c:
        r = await c.get("/graph", params={"mode": "paper", "id": p["ddpm"]})
    assert r.status_code == 200
    graph = r.json()
    labels = {n["label"] for n in graph["nodes"]}
    assert {"Denoising Diffusion Probabilistic Models", "Jonathan Ho", "Pieter Abbeel",
            "Diffusion Models", "foundational", "Generative models for protein design"} <= labels
    links = {(l["source"], l["type"], l["target"]) for l in graph["links"]}
    assert (p["score_sde"], "CITES", p["ddpm"]) in links
    assert (p["ddpm"], "CITES", p["unet"]) in links
    # Alice is not in the reading group, so the cited Transformer paper stays hidden.
    assert p["transformer"] not in {n["id"] for n in graph["nodes"]}


async def test_graph_respects_visibility(demo_library, auth_headers):
    p = demo_library["papers"]
    async with _client(auth_headers("demo_carol")) as c:
        hidden = (await c.get("/graph", params={"mode": "paper", "id": p["ddpm"]})).json()
        overview = (await c.get("/graph", params={"mode": "papers"})).json()
    assert hidden == {"nodes": [], "links": []}
    seen = {n["id"] for n in overview["nodes"] if n["type"] == "paper"}
    assert seen == {p["gnn_survey"], p["ddpm_stub"], p["unet"]}


# ── Duplicate scan ────────────────────────────────────────────────────────────

async def test_merge_scan_finds_the_stub_duplicate(demo_library, auth_headers):
    p = demo_library["papers"]
    async with _client(auth_headers("demo_alice")) as c:
        r = await c.get("/merge/groups")
    assert r.status_code == 200
    groups = r.json()["groups"]
    assert len(groups) == 1
    group = groups[0]
    assert group["keep"]["id"] == p["ddpm"]
    assert [x["id"] for x in group["remove"]] == [p["ddpm_stub"]]
    assert "doi" in group["reasons"]


async def test_merge_dry_run_changes_nothing(demo_library, auth_headers):
    p = demo_library["papers"]
    async with _client(auth_headers("demo_alice")) as c:
        r = await c.post("/merge/execute", json={"keep_id": p["ddpm"], "remove_id": p["ddpm_stub"], "dry_run": True})
    assert r.status_code == 200
    assert r.json()["relationships_moved"] >= 1
    with get_driver().session() as s:
        assert s.run("MATCH (x:Paper {id: $id}) RETURN count(x) AS n", id=p["ddpm_stub"]).single()["n"] == 1


async def test_merge_is_admin_only(demo_library, auth_headers):
    async with _client(auth_headers("demo_bob")) as c:
        assert (await c.get("/merge/groups")).status_code == 403


# ── Knowledge chat: @mention context ──────────────────────────────────────────

@pytest.mark.parametrize("mention,expected", [
    (("topic", "Protein-Design"), {"rfdiffusion"}),
    (("tag", "protein"), {"alphafold2", "alphafold3", "rfdiffusion", "esm2"}),
    (("project", "generative models"), {"ddpm", "score_sde", "edm", "flow_matching",
                                        "alphafold2", "alphafold3", "rfdiffusion", "esm2"}),
    (("person", "Yang Song"), {"score_sde"}),
    (("paper", "flow matching"), {"flow_matching"}),
])
def test_knowledge_chat_mention_context(demo_library, mention, expected):
    """The papers an @mention puts into the knowledge-chat context (no LLM involved)."""
    from routers.knowledge_chat import _fetch_papers_for_mention

    with get_driver().session() as session:
        papers, _, _ = _fetch_papers_for_mention(session, *mention)
    assert set(_keys(demo_library, papers)) == expected
