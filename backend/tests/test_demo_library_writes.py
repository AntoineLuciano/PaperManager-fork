"""Tests that change the demo library; each one gets a freshly loaded copy (demo_library_fresh)."""
import io
import json
import time
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from starlette.datastructures import UploadFile

from db.connection import get_driver
from main import app


def _client(headers=None):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers or {})


def _graph_summary(driver) -> dict:
    """Everything a snapshot must preserve, independent of internal element ids."""
    with driver.session() as s:
        nodes = sorted(
            (sorted(r["labels"]), r["id"], r["title"])
            for r in s.run("MATCH (n) WHERE NOT n:User RETURN labels(n) AS labels, n.id AS id, "
                           "coalesce(n.title, n.name, n.text, n.content) AS title")
        )
        rels = sorted(
            (r["a"], r["type"], r["b"], sorted(r["props"]))
            for r in s.run("MATCH (a)-[r]->(b) RETURN coalesce(a.id, a.name) AS a, type(r) AS type, "
                           "coalesce(b.id, b.name) AS b, "
                           "[k IN keys(r) | k + '=' + toString(r[k])] AS props")
        )
    return {"nodes": nodes, "rels": rels}


async def test_snapshot_round_trip_restores_the_library(demo_library_fresh):
    """Export the demo library, import it with replace=True, and get the same graph back,
    including relationships to user accounts (project membership, ADDED, WROTE, STARTED)."""
    from routers.export import export_snapshot, import_snapshot

    driver = get_driver()
    before = _graph_summary(driver)
    snapshot = json.loads(export_snapshot(driver=driver).body)
    assert not any("User" in n["labels"] for n in snapshot["nodes"])
    assert all("password_hash" not in n["properties"] for n in snapshot["nodes"])

    with driver.session() as s:  # something the import must remove
        s.run("CREATE (:Paper {id: 'stray', title: 'Not in the snapshot'})").consume()
    upload = UploadFile(filename="snapshot.json", file=io.BytesIO(json.dumps(snapshot).encode()))
    result = await import_snapshot(file=upload, replace=True, current_user="demo_alice", driver=driver)

    assert result["imported"]["nodes"] == len(snapshot["nodes"])
    assert _graph_summary(driver) == before
    with driver.session() as s:
        users = {r["name"]: r["admin"] for r in s.run("MATCH (u:User) RETURN u.name AS name, u.is_admin AS admin")}
    assert users == {"demo_alice": True, "demo_bob": False, "demo_carol": False}


async def test_merge_moves_citations_to_the_keeper(demo_library_fresh, auth_headers):
    p = demo_library_fresh["papers"]
    async with _client(auth_headers("demo_alice")) as c:
        r = await c.post("/merge/execute", json={"keep_id": p["ddpm"], "remove_id": p["ddpm_stub"]})
        assert r.status_code == 200
        groups = (await c.get("/merge/groups")).json()["groups"]
    assert groups == []
    with get_driver().session() as s:
        assert s.run("MATCH (x:Paper {id: $id}) RETURN count(x) AS n", id=p["ddpm_stub"]).single()["n"] == 0
        cites = s.run("MATCH (:Paper {id: $a})-[:CITES]->(:Paper {id: $b}) RETURN count(*) AS n",
                      a=p["rfdiffusion"], b=p["ddpm"]).single()["n"]
    assert cites == 1


async def test_concept_map_build_with_mocked_llm(demo_library_fresh, auth_headers):
    """Building the map extracts concepts for the papers not mapped yet (EDM, AlphaFold 3,
    ESM-2); the LLM extraction is mocked, saving and the map read are real."""
    from services.concept_map import concept_key

    ids = demo_library_fresh
    pid = ids["projects"]["protein_gen"]
    asked: list[str] = []

    def fake_extract(paper, authors, claims, vocabulary):
        asked.append(paper["id"])
        assert "Diffusion Models" in vocabulary  # the project's existing concepts are offered
        name = "Diffusion Models" if paper["id"] != ids["papers"]["esm2"] else "Protein Language Models"
        return {"concepts": [{"key": concept_key(name), "name": name, "kind": "method", "definition": "",
                              "aliases": [], "alias_keys": [], "role": "uses", "in_paper": "mocked"}],
                "relations": []}

    with patch("routers.concept_map.extract_paper_concepts", side_effect=fake_extract):
        async with _client(auth_headers("demo_alice")) as c:
            r = await c.post(f"/projects/{pid}/concept-map/build", json={})
            assert r.status_code == 200
            for _ in range(100):
                status = (await c.get(f"/projects/{pid}/concept-map/status")).json()
                if not status["running"]:
                    break
                time.sleep(0.05)
            body = (await c.get(f"/projects/{pid}/concept-map")).json()

    assert status["done"] == 3 and status["failed"] == 0
    assert set(asked) == {ids["papers"][k] for k in ("edm", "alphafold3", "esm2")}
    diffusion = next(c["id"] for c in body["concepts"] if c["name"] == "Diffusion Models")
    discussing = {d["paper_id"] for d in body["discusses"] if d["concept_id"] == diffusion}
    assert {ids["papers"]["edm"], ids["papers"]["alphafold3"]} <= discussing
    assert "Protein Language Models" in {c["name"] for c in body["concepts"]}
