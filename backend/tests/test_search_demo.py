"""Ranked library search and type-ahead against the demo library (real Neo4j, read-only).

Complements test_demo_library.py (title ranking, filters, visibility of GET /search) with
what the 2026-10 search added: author/topic matching, typo tolerance, DOI/arXiv lookup,
snippets and marks, reference stubs, sorting, and /search/suggest.
"""
from httpx import ASGITransport, AsyncClient

from main import app


def _client(headers):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


def _keys(ids, rows):
    by_id = {v: k for k, v in ids["papers"].items()}
    return [by_id.get(r["id"]) for r in rows]


async def _search(headers, **params):
    async with _client(headers) as c:
        r = await c.get("/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_author_and_title_terms_combine(demo_library, auth_headers):
    res = await _search(auth_headers("demo_alice"), q="Karras diffusion")
    assert _keys(demo_library, res["results"])[0] == "edm"
    top = res["results"][0]
    assert "author" in top["matched_fields"] and "title" in top["matched_fields"]
    assert top["matches"]["author"] == ["Tero Karras"]


async def test_typo_and_prefix(demo_library, auth_headers):
    alice = auth_headers("demo_alice")
    typo = await _search(alice, q="scroe based generative")
    assert _keys(demo_library, typo["results"])[0] == "score_sde"
    prefix = await _search(alice, q="Elucidat")
    assert _keys(demo_library, prefix["results"]) == ["edm"]


async def test_doi_and_arxiv_lookup(demo_library, auth_headers):
    alice = auth_headers("demo_alice")
    doi = await _search(alice, q="https://doi.org/10.1038/s41586-024-07487-w")
    assert _keys(demo_library, doi["results"]) == ["alphafold3"]
    assert doi["results"][0]["matched_fields"] == ["doi"]
    arxiv = await _search(alice, q="arXiv:2006.11239")
    assert set(_keys(demo_library, arxiv["results"])) == {"ddpm", "ddpm_stub"}


async def test_snippets_and_title_marks(demo_library, auth_headers):
    res = await _search(auth_headers("demo_alice"), q="EDM parameterisation")
    hit = next(r for r in res["results"] if r["id"] == demo_library["papers"]["alphafold3"])
    note = next(s for s in hit["snippets"] if s["field"] == "note")
    marked = [note["text"][s:e] for s, e in note["marks"]]
    assert "EDM" in marked and "parameterisation" in marked
    flow = await _search(auth_headers("demo_alice"), q="flow matching")
    title = flow["results"][0]["title"]
    assert [title[s:e] for s, e in flow["results"][0]["title_marks"]] == ["Flow", "Matching"]


async def test_reference_stubs_rank_below_and_can_be_excluded(demo_library, auth_headers):
    alice = auth_headers("demo_alice")
    keys = _keys(demo_library, (await _search(alice, q="Denoising Diffusion Probabilistic Models"))["results"])
    assert keys.index("ddpm") < keys.index("ddpm_stub")
    no_refs = await _search(alice, q="Denoising Diffusion Probabilistic Models", include_references="false")
    assert "ddpm_stub" not in _keys(demo_library, no_refs["results"])


async def test_sort_and_paging(demo_library, auth_headers):
    alice = auth_headers("demo_alice")
    by_year = await _search(alice, q="diffusion", sort="year_desc", include_references="false")
    years = [r["year"] for r in by_year["results"]]
    assert years == sorted(years, reverse=True)
    first = await _search(alice, q="diffusion", limit=2)
    second = await _search(alice, q="diffusion", limit=2, skip=2)
    assert first["total"] == second["total"] > 4
    assert not {r["id"] for r in first["results"]} & {r["id"] for r in second["results"]}


async def test_filter_only_reports_total(demo_library, auth_headers):
    res = await _search(auth_headers("demo_alice"), topic="Diffusion Models", limit=2)
    assert res["total"] == 5 and len(res["results"]) == 2


async def test_suggest(demo_library, auth_headers):
    async with _client(auth_headers("demo_alice")) as c:
        r = await c.get("/search/suggest", params={"q": "tero kar"})
        assert r.status_code == 200
        assert [a["name"] for a in r.json()["authors"]] == ["Tero Karras"]
        r = await c.get("/search/suggest", params={"q": "diffus"})
        body = r.json()
        assert "Diffusion Models" in [t["name"] for t in body["topics"]]
        assert demo_library["papers"]["ddpm"] in [p["id"] for p in body["papers"]]
        assert demo_library["papers"]["ddpm_stub"] not in [p["id"] for p in body["papers"]]
        r = await c.get("/search/suggest", params={"q": "generative models for"})
        assert [p["name"] for p in r.json()["projects"]] == ["Generative models for protein design"]


async def test_suggest_respects_visibility(demo_library, auth_headers):
    async with _client(auth_headers("demo_carol")) as c:
        r = await c.get("/search/suggest", params={"q": "generative"})
    body = r.json()
    assert body["projects"] == []
    assert body["papers"] == []  # every generative-modelling paper sits in Alice's project


async def test_case_and_accent_variants_return_the_same_hits(demo_library, auth_headers):
    bob = auth_headers("demo_bob")  # sees every demo paper, the Transformer included

    async def ids(**params):
        return [r["id"] for r in (await _search(bob, **params))["results"]]

    for variants in (["flow matching", "FLOW MATCHING", "Flow Matching"],
                     ["karras", "KARRAS", "Karras"],
                     ["alphafold 3", "AlphaFold 3", "ALPHAFOLD 3"],
                     ["10.1038/S41586-024-07487-W", "10.1038/s41586-024-07487-w"],
                     ["ARXIV:2210.02747", "arxiv:2210.02747"]):
        results = [await ids(q=v) for v in variants]
        assert results[0] and all(r == results[0] for r in results), variants
    # Accents: "Łukasz Kaiser" is an author of the Transformer paper.
    assert _keys(demo_library, (await _search(bob, q="lukasz"))["results"]) == ["transformer"]
    assert await ids(q="Łukasz") == await ids(q="LUKASZ")


async def test_filters_ignore_case(demo_library, auth_headers):
    alice = auth_headers("demo_alice")
    exact = await _search(alice, topic="Diffusion Models")
    lower = await _search(alice, topic="diffusion models")
    assert {r["id"] for r in exact["results"]} == {r["id"] for r in lower["results"]} and exact["total"] == 5
    tag = await _search(alice, tag="FOUNDATIONAL")
    assert set(_keys(demo_library, tag["results"])) == {"ddpm", "score_sde", "alphafold2"}
    venue = await _search(alice, venue="nature", q="protein")
    assert set(_keys(demo_library, venue["results"])) == {"alphafold2", "alphafold3", "rfdiffusion"}


async def test_suggest_ignores_case_and_accents(demo_library, auth_headers):
    async with _client(auth_headers("demo_bob")) as c:
        upper = (await c.get("/search/suggest", params={"q": "TERO KAR"})).json()
        accent = (await c.get("/search/suggest", params={"q": "lukasz"})).json()
    assert [a["name"] for a in upper["authors"]] == ["Tero Karras"]
    assert [a["name"] for a in accent["authors"]] == ["Łukasz Kaiser"]
