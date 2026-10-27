"""library_lookup (services/library_lookup.py, MCP tool in tools/library_tools.py).

The first block is pure (normalisers and matching); the second hits Neo4j like
test_mcp_tools.py and removes what it creates.
"""
import json

import pytest

from db.connection import get_driver
from db.queries.papers import create_paper, delete_paper
from services.auth import reset_request_user, set_request_user
from services.library_lookup import build_index, doi_key, match_item, title_key
from tools import library_tools as lt


# ── normalisers ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "10.48550/arXiv.2210.02747", "arXiv:2210.02747", "2210.02747", "2210.02747v2",
    "arxiv:2210.02747v3", "https://arxiv.org/abs/2210.02747v1", "https://doi.org/10.48550/ARXIV.2210.02747",
])
def test_doi_key_arxiv_forms_are_one_id(raw):
    assert doi_key(raw) == "arxiv:2210.02747"


@pytest.mark.parametrize("raw", [
    "10.1038/nchem.1821", "10.1038/NCHEM.1821", "https://doi.org/10.1038/nchem.1821",
    "http://dx.doi.org/10.1038/nchem.1821", "doi:10.1038/nchem.1821", "DOI: 10.1038/nchem.1821.",
    " 10.1038/nchem.1821 ",
])
def test_doi_key_prefixes_case_and_trailing_dot(raw):
    assert doi_key(raw) == "10.1038/nchem.1821"


def test_doi_key_biorxiv_version_old_arxiv_and_empty():
    assert doi_key("10.1101/2024.12.05.626885v2") == "10.1101/2024.12.05.626885"
    assert doi_key("cs/0010026") == doi_key("arXiv:cs/0010026v1") == "arxiv:cs/0010026"
    assert doi_key("") is None and doi_key(None) is None and doi_key(" . ") is None


def test_title_key_strips_markup_entities_accents_and_punctuation():
    assert title_key("Structure of <i>E. coli</i> Protein<sub>2</sub>") == "structureofecoliprotein2"
    assert title_key("<scp>AlphaFold</scp>&amp;Friends: Réseau") == "alphafoldfriendsreseau"
    assert title_key("  Highly accurate protein-structure prediction!  ") == "highlyaccurateproteinstructureprediction"
    assert title_key(None) == "" and title_key("") == ""


# ── matching (pure) ───────────────────────────────────────────────────────────

LONG = "Scalable emulation of protein equilibrium ensembles with generative deep learning"
ROWS = [
    ["a", "10.1038/nchem.1821", "Some chemistry paper"],
    ["b", "10.1101/2024.12.05.626885", LONG],
    ["c", "arXiv:2210.02747", "Flow Matching for Generative Modeling"],
    ["d", None, "Flow matching for generative modeling."],
    ["e", None, "Highly accurate protein structure prediction with AlphaFold"],
]


def test_match_doi_first_then_title():
    idx = build_index(ROWS)
    assert match_item("https://doi.org/10.1038/NCHEM.1821", "", idx) == ("doi", ["a"])
    assert match_item("10.48550/arXiv.2210.02747v2", "", idx) == ("doi", ["c"])
    # journal DOI misses, the title finds the bioRxiv-stored paper
    assert match_item("10.1126/science.adv9817", LONG, idx) == ("title_exact", ["b"])
    # same normalised title on two papers: both returned
    assert match_item("", "FLOW MATCHING FOR GENERATIVE MODELING", idx) == ("title_exact", ["c", "d"])
    assert match_item("10.9999/does-not-exist", "", idx) == (None, [])


def test_match_title_prefix_needs_45_shared_characters():
    idx = build_index(ROWS)
    longer = LONG + ": supplementary analysis and extended benchmarks"
    assert match_item("", longer, idx) == ("title_prefix", ["b"])
    # shares 40 normalised characters with paper e, then differs: no match
    assert match_item("", "Highly accurate protein structure prediction for the human proteome", idx) == (None, [])
    # short titles only match exactly
    assert match_item("", "Some chemistry", idx) == (None, [])


# ── tool against Neo4j ────────────────────────────────────────────────────────

@pytest.fixture
def admin():
    """The MCP server runs as the admin user (mcp_server.py), who sees every paper."""
    token = set_request_user("niklas")
    yield
    reset_request_user(token)


@pytest.fixture
def papers(admin):
    d = get_driver()
    a = create_paper(d, {"title": "Lookup Test: <i>Ensembles</i> of Proteins with Generative Deep Learning Models",
                         "doi": "10.5555/LOOKUP-TEST.1", "year": 2025, "raw_text": "text"})
    b = create_paper(d, {"title": "Lookup test arXiv paper on stochastic interpolants", "doi": "arXiv:2209.99999"})
    c = create_paper(d, {"title": "Lookup test arXiv paper on stochastic interpolants"})
    with d.session() as s:
        s.run("MERGE (pr:Project {id: 'lookup-test-project'}) SET pr.name = 'LookupTestProject' "
              "WITH pr MATCH (p:Paper {id: $id}) MERGE (p)-[:IN_PROJECT]->(pr)", id=a["id"])
        s.run("MERGE (t:Tag {name: 'from-references'}) WITH t MATCH (p:Paper {id: $id}) MERGE (p)-[:TAGGED]->(t)",
              id=c["id"])
    yield a, b, c
    for p in (a, b, c):
        delete_paper(d, p["id"])
    with d.session() as s:
        s.run("MATCH (pr:Project {id: 'lookup-test-project'}) DETACH DELETE pr")


def test_library_lookup_against_neo4j(papers):
    a, b, c = papers
    res = lt.library_lookup(
        dois=["https://doi.org/10.5555/lookup-test.1", "10.48550/arXiv.2209.99999v2", "", "10.9999/lookup-missing"],
        titles=["", "", "Lookup test: ensembles of proteins with generative deep learning models and more", ""],
        project="LookupTestProject")
    assert (res["found"], res["missing"], res["project"]) == (3, 1, "LookupTestProject")
    assert "project_error" not in res
    i0, i1, i2, i3 = res["items"]

    assert i0["kind"] == "doi" and i0["query"] == "https://doi.org/10.5555/lookup-test.1"
    m = i0["match"]
    assert m["id"] == a["id"] and m["year"] == 2025 and m["projects"] == ["LookupTestProject"]
    assert m["in_project"] is True and m["has_text"] is True and m["reference_stub"] is False
    assert m["url"].endswith(f"/paper/{a['id']}")
    assert set(m) == {"id", "title", "doi", "year", "projects", "reference_stub", "has_text", "url", "in_project"}

    # DOI hits only b; c has the same title but the DOI wins
    assert i1["kind"] == "doi" and i1["match"]["id"] == b["id"] and i1["match"]["in_project"] is False

    assert i2["kind"] == "title_prefix" and i2["match"]["id"] == a["id"]
    assert i3 == {"query": "10.9999/lookup-missing", "kind": None, "match": None}


def test_library_lookup_duplicates_and_stub_flag(papers):
    _, b, c = papers
    res = lt.library_lookup(titles=["LOOKUP TEST arXiv paper on stochastic interpolants"])
    item = res["items"][0]
    assert item["kind"] == "title_exact" and item["duplicates"] == 2
    assert [m["id"] for m in item["match"]] == [b["id"], c["id"]]       # stub last
    assert [m["reference_stub"] for m in item["match"]] == [False, True]
    assert "in_project" not in item["match"][0]


def test_library_lookup_hides_project_papers_from_non_members(papers):
    a, b, _ = papers
    token = set_request_user("lookup-test-outsider")
    try:
        res = lt.library_lookup(dois=["10.5555/lookup-test.1", "arXiv:2209.99999"])
    finally:
        reset_request_user(token)
    assert [i["match"] and i["match"]["id"] for i in res["items"]] == [None, b["id"]]


def test_library_lookup_errors(admin):
    assert "error" in lt.library_lookup()
    assert "error" in lt.library_lookup(dois=["10.1/x"] * 201)
    res = lt.library_lookup(dois=["10.9999/none"], project="no-such-project-xyz")
    assert res["missing"] == 1 and "project_error" in res


def test_library_lookup_tool_returns_compact_json(papers):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("t")
    lt.register(mcp)
    tool = mcp._tool_manager.get_tool("library_lookup")
    out = tool.fn(dois=["10.5555/lookup-test.1"], titles=[], project="")
    assert isinstance(out, str) and json.loads(out)["found"] == 1
    assert out == json.dumps(json.loads(out), ensure_ascii=False, separators=(",", ":"))
