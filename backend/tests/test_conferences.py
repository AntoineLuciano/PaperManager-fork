"""Conference explorer: institution normalisation, the two source parsers, counting and
ranking, area assignment, topic search and the HTTP endpoints. No network and no model:
sources are fed fixtures, and the datasets are written by hand."""
from __future__ import annotations

import json

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from services.conferences import areas, catalog, institutions, sources, store


# ── institutions ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("University of California, Berkeley", [("UC Berkeley", "A")]),
    ("Google, TUM", [("Google", "I"), ("TU Munich", "A")]),
    ("Tsinghua University, Tsinghua University", [("Tsinghua University", "A")]),
    ("Department of Computer Science, ETHZ - ETH Zurich", [("ETH Zurich", "A")]),
    ("Xi&#x27;an Jiaotong University", [("Xi'an Jiaotong University", "A")]),
    ("Institute of automation, Chinese academy of science, Chinese Academy of Sciences",
     [("Chinese Academy of Sciences", "A")]),
    ("University College London, University of London", [("University College London", "A")]),
    ("Google DeepMind", [("Google", "I")]),
    ("Meta FAIR", [("Meta", "I")]),
    ("JIUTIAN Ｒｅｓｅａｒｃｈ", [("JIUTIAN Research", "I")]),
    ("Guangdong OPPO Mobile Telecommunications Corp.,Ltd.", [("OPPO", "I")]),
    ("Independent Researcher", []),
    ("Meituan", [("Meituan", "I")]),
    ("Istituto Italiano di Tecnologia", [("Istituto Italiano di Tecnologia", "A")]),
    ("McGill University / Mila / DeepMind Montreal", [("McGill University", "A"), ("Mila", "A"), ("Google", "I")]),
    ("Tel Aviv University and Facebook AI Research", [("Tel Aviv University", "A"), ("Meta", "I")]),
    ("Texas A&amp;M University", [("Texas A&M University", "A")]),
    ("Department of Physics and Astronomy, University College London", [("University College London", "A")]),
])
def test_split_and_normalise(raw, expected):
    assert institutions.split_and_normalise(raw) == expected


def test_merge_key_folds_spellings():
    assert institutions.merge_key("The Ohio State University") == institutions.merge_key("ohio state university")
    assert institutions.merge_key("Universität Zürich") == institutions.merge_key("Universitat Zurich")


# ── catalog ───────────────────────────────────────────────────────────────────

def test_catalog_resolve():
    assert catalog.resolve("NeurIPS 2026").key == "neurips2026"
    assert catalog.resolve("nips2025").key == "neurips2025"
    assert catalog.resolve("iclr").key == "iclr2026"          # bare series = latest year
    assert catalog.resolve("acl2025").source == "papercopilot"
    assert catalog.resolve("nosuchconf") is None
    keys = [e.key for e in catalog.editions()]
    assert len(keys) == len(set(keys))


# ── sources ───────────────────────────────────────────────────────────────────

def _event(name, insts, decision="Accept (poster)", eventtype="Poster", session="Poster Session 1", **kw):
    return {
        "name": name, "decision": decision, "eventtype": eventtype, "session": session,
        "abstract": kw.get("abstract", ""), "virtualsite_url": f"/virtual/2026/poster/{abs(hash(name)) % 1000}",
        "paper_url": kw.get("paper_url", ""), "topic": kw.get("topic"), "keywords": [],
        "authors": [{"fullname": f"Author {i}", "institution": inst} for i, inst in enumerate(insts)],
    }


def test_miniconf_merges_oral_and_poster(monkeypatch):
    feed = {"count": 3, "next": None, "results": [
        _event("Paper A", ["MIT", "Google"], abstract="About A.", paper_url="https://openreview.net/forum?id=same"),
        _event("Paper A", ["MIT", "Google"], decision=None, eventtype="Oral", session="Oral 2"),
        _event("Paper B", ["Stanford University"], paper_url="https://openreview.net/forum?id=same"),
    ]}
    monkeypatch.setattr(sources, "_get_json", lambda url, timeout=0: feed)
    rows, info = sources.fetch(catalog.get_edition("neurips2026"))
    assert [r["title"] for r in rows] == ["Paper A", "Paper B"]   # shared paper_url does not merge B into A
    a = rows[0]
    assert a["decision"] == "Oral" and a["abstract"] == "About A."
    assert a["session"] == "Poster Session 1 · Oral 2"
    assert a["url"].startswith("https://neurips.cc/virtual/2026/")
    assert info == {"expected": 3, "partial": False, "events": 3}


def test_papercopilot_drops_rejected_and_reads_affiliations(monkeypatch):
    data = [
        {"title": "Kept", "status": "Spotlight", "track": "main", "author": "X;Y",
         "aff_unique_norm": "Princeton University;NVIDIA", "aff_unique_index": "0;1+0", "aff": "",
         "abstract": "abs", "site": "https://openreview.net/forum?id=1", "keywords": "a;b"},
        {"title": "Gone", "status": "Reject", "author": "Z", "aff_unique_norm": "", "aff_unique_index": "", "aff": ""},
        {"title": "Withdrawn", "status": "Withdraw", "author": "Z"},
    ]
    monkeypatch.setattr(sources, "_get_json", lambda url, timeout=0: data)
    rows, _ = sources.fetch(catalog.get_edition("acl2025"))
    assert [r["title"] for r in rows] == ["Kept"]
    r = rows[0]
    assert r["decision"] == "Spotlight"
    assert r["authors"] == [{"name": "X", "insts": ["Princeton University"]},
                            {"name": "Y", "insts": ["NVIDIA", "Princeton University"]}]
    assert r["forum"] == "https://openreview.net/forum?id=1" and r["keywords"] == ["a", "b"]


# ── areas ─────────────────────────────────────────────────────────────────────

def test_area_assignment_follows_prototypes():
    rng = np.random.default_rng(0)
    protos = np.eye(len(areas.AREAS), 32, dtype=np.float32)
    truth = rng.integers(0, len(areas.AREAS), 400)
    emb = protos[truth] + 0.05 * rng.standard_normal((400, 32)).astype(np.float32)
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    assert (areas.assign(emb, protos) == truth).mean() > 0.95


# ── store: a hand-made dataset ────────────────────────────────────────────────

def _fake_dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_data_dir", tmp_path)
    store._cache.clear()
    ds = {
        "key": "corl2025", "name": "CoRL 2025", "series": "CoRL", "slug": "corl", "field": "Robotics",
        "year": 2025, "source": "papercopilot", "source_url": "https://example.org/corl2025.json",
        "fetched_at": "2026-10-25T00:00:00+00:00", "partial": False, "expected": 3, "areas_ready": True,
        "insts": [{"n": "MIT", "s": "A"}, {"n": "NVIDIA", "s": "I"}, {"n": "Stanford University", "s": "A"}],
        "papers": [
            {"id": "p1", "t": "Diffusion policies for robot manipulation", "a": "We grasp things.", "au": ["A", "B"],
             "ai": [[0], [1]], "i": [0, 1], "ar": 7, "d": "Oral", "tr": "", "s": "", "u": "https://x/1", "f": "", "nt": "", "kw": []},
            {"id": "p2", "t": "Legged locomotion with reinforcement learning", "a": "", "au": ["C"],
             "ai": [[0, 2]], "i": [0, 2], "ar": 6, "d": "Poster", "tr": "", "s": "", "u": "", "f": "", "nt": "", "kw": []},
            {"id": "p3", "t": "Tactile sensing for dexterous hands", "a": "", "au": ["D", "E"],
             "ai": [[2], []], "i": [2], "ar": 7, "d": "Poster", "tr": "", "s": "", "u": "", "f": "", "nt": "", "kw": []},
        ],
    }
    store._finalise(ds)
    (tmp_path / "corl2025").mkdir()
    (tmp_path / "corl2025" / "dataset.json").write_text(json.dumps(ds))
    emb = np.eye(3, 384, dtype=np.float32)
    np.save(tmp_path / "corl2025" / "emb.npy", emb.astype(np.float16))
    store._set_status("corl2025", "ready", papers=3, institutions=3)
    return ds


def test_counts_fractional_and_rank(tmp_path, monkeypatch):
    ds = _fake_dataset(tmp_path, monkeypatch)
    by = {r["n"]: r for r in ds["insts"]}
    assert by["MIT"]["p"] == 2 and by["Stanford University"]["p"] == 2 and by["NVIDIA"]["p"] == 1
    # MIT: 1/2 of p1 + half of the single author of p2 = 1.0; Stanford: 0.5 (p2) + 0.5 (p3)
    assert by["MIT"]["f"] == 1.0 and by["Stanford University"]["f"] == 1.0 and by["NVIDIA"]["f"] == 0.5
    assert by["MIT"]["r"] == by["Stanford University"]["r"] == 1 and by["NVIDIA"]["r"] == 3
    assert by["MIT"]["a"][7] == 1 and by["MIT"]["a"][6] == 1


def test_search_institutions_and_detail(tmp_path, monkeypatch):
    _fake_dataset(tmp_path, monkeypatch)
    ds = store.load("corl2025")
    assert ds.areas_ready
    res = store.search_institutions(ds, q="stanf")
    assert [r["name"] for r in res["rows"]] == ["Stanford University"]
    ind = store.search_institutions(ds, sector="I")
    assert [r["name"] for r in ind["rows"]] == ["NVIDIA"]
    robo = store.search_institutions(ds, area=7)
    assert {r["name"]: r["count"] for r in robo["rows"]} == {"MIT": 1, "NVIDIA": 1, "Stanford University": 1}
    d = store.institution_detail(ds, "mit", library={"diffusionpoliciesforrobotmanipulation": "lib-1"})
    assert d["papers"] == 2 and d["paper_list"][0]["decision"] == "Oral"
    assert d["paper_list"][0]["library_id"] == "lib-1"
    assert {c["name"] for c in d["collaborators"]} == {"NVIDIA", "Stanford University"}


def test_topic_semantic_and_keyword(tmp_path, monkeypatch):
    _fake_dataset(tmp_path, monkeypatch)
    ds = store.load("corl2025")
    from services.conferences import embedder

    monkeypatch.setattr(embedder, "embed_query", lambda text: np.eye(3, 384, dtype=np.float32)[1])
    res = store.topic(ds, "legged robots", k=10)
    assert res["mode"] == "semantic" and res["papers"][0]["id"] == "p2"
    assert {x["name"] for x in res["academia"]} == {"MIT", "Stanford University"}
    ds.emb = None                       # not indexed yet: keyword fallback
    res = store.topic(ds, "tactile hands", k=10)
    assert res["mode"] == "keyword" and [p["id"] for p in res["papers"]] == ["p3"]


@pytest.mark.asyncio
async def test_endpoints(tmp_path, monkeypatch):
    _fake_dataset(tmp_path, monkeypatch)
    from main import app
    from routers import conferences as router

    monkeypatch.setattr(router, "library_titles", lambda: {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cat = (await client.get("/conferences/catalog")).json()
        row = next(c for c in cat["conferences"] if c["key"] == "corl2025")
        assert row["state"] == "ready" and len(cat["areas"]) == len(areas.AREAS)
        ov = (await client.get("/conferences/CoRL 2025/overview")).json()
        assert ov["papers"] == 3 and ov["top_industry"][0]["name"] == "NVIDIA"
        inst = (await client.get("/conferences/corl2025/institutions", params={"sector": "A"})).json()
        assert inst["total"] == 2
        assert (await client.get("/conferences/corl2025/institutions/nvidia")).json()["papers"] == 1
        assert (await client.get("/conferences/corl2025/papers/p1")).json()["author_list"][1]["institutions"] == ["NVIDIA"]
        assert (await client.get("/conferences/icml2023/overview")).status_code == 409   # known, not loaded
        assert (await client.get("/conferences/nosuch/overview")).status_code == 404


def test_hong_kong_universities_stay_apart():
    assert institutions.split_and_normalise("City University of Hong Kong") == [("City University of Hong Kong", "A")]
    assert institutions.split_and_normalise("The University of Hong Kong") == [("University of Hong Kong", "A")]
    assert institutions.split_and_normalise("The Chinese University of Hong Kong") == [("CUHK", "A")]
