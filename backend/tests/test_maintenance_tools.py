"""MCP maintenance tools (tools/maintenance_tools.py) and the author / title rules behind them.

The first block is pure; the second hits Neo4j like test_mcp_tools.py and cleans up after itself.
"""
from unittest.mock import patch

import pytest

from db.connection import get_driver
from db.queries.papers import _is_short_title_of, _normalize_title, create_paper, delete_paper, get_paper
from db.queries.people import get_authors_for_paper
from services.pdf_parser import clean_authors, strip_line_numbers
from tools import maintenance_tools as mt


# ── pure rules ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (["Anonymous Authors1"], []),                                   # ICML double-blind byline
    (["Anonymous Author", "Anonymized Submission"], []),
    (["Unknown", "et al."], []),
    (["Jonathan Feldman1", "Maximilian Brogi2", "Jeffrey Skolnick1*"],
     ["Jonathan Feldman", "Maximilian Brogi", "Jeffrey Skolnick"]),
    (["Ada Lovelace", "Ada Lovelace"], ["Ada Lovelace"]),
    (["Anonymous Authors", "Grace Hopper"], ["Grace Hopper"]),
])
def test_clean_authors(raw, expected):
    assert clean_authors(raw) == expected


def test_strip_line_numbers_removes_review_margin():
    text = "000\n001\n002\nStructural Memorization in AlphaFold\n003\nAnonymous Authors1\nAbstract\n"
    out = strip_line_numbers(text)
    assert out.startswith("Structural Memorization")
    assert "001" not in out


def test_strip_line_numbers_keeps_numbers_inside_text():
    text = "We used 200 proteins\n2026\n"
    assert strip_line_numbers(text) == text


def test_short_title_of():
    stub = _normalize_title("Structural memorization in AlphaFold: adversarial mutations")
    full = _normalize_title("Structural Memorization in AlphaFold: Adversarial Mutations Reveal "
                            "Template Reliance, Confidence Failures, and Implications for Protein Design")
    assert _is_short_title_of(stub, full)
    assert not _is_short_title_of(_normalize_title("Structural memorization"), full)   # too short
    assert not _is_short_title_of(full, full)


# ── tools against Neo4j ───────────────────────────────────────────────────────

@pytest.fixture
def paper():
    d = get_driver()
    p = create_paper(d, {"title": "Maintenance Tool Test Paper", "raw_text": "Some extracted text."})
    yield p
    delete_paper(d, p["id"])


def test_update_paper_metadata_replaces_authors(paper):
    mt.update_paper_metadata(paper["id"], authors=["Anonymous Authors1"])
    assert [a["name"] for a in get_authors_for_paper(get_driver(), paper["id"])] == []

    mt.update_paper_metadata(paper["id"], authors=["MaintTest Alpha", "MaintTest Beta"])
    res = mt.update_paper_metadata(paper["id"], year=2026, authors=["MaintTest Beta", "MaintTest Gamma"])
    assert res["year"] == 2026 and res["updated"] == ["year"]
    assert sorted(res["authors"]) == ["MaintTest Beta", "MaintTest Gamma"]
    assert res["authors_removed"] == ["MaintTest Alpha"]
    # unlinked people with nothing else attached are removed; clean up the rest
    with get_driver().session() as s:
        assert not s.run("MATCH (a:Person {name: 'MaintTest Alpha'}) RETURN a").data()
        s.run("MATCH (a:Person) WHERE a.name STARTS WITH 'MaintTest ' DETACH DELETE a")


def test_update_paper_metadata_missing():
    assert "error" in mt.update_paper_metadata("nonexistent", title="x")


def test_regenerate_summary(paper):
    with patch("services.ai.summarize_paper", return_value="## Summary\nok") as fake:
        res = mt.regenerate_summary(paper["id"])
    fake.assert_called_once()
    assert res["summary_chars"] == len("## Summary\nok")
    assert get_paper(get_driver(), paper["id"])["summary"] == "## Summary\nok"


def test_merge_papers_dry_run_changes_nothing(paper):
    d = get_driver()
    dup = create_paper(d, {"title": "Maintenance Tool Test Paper (dup)", "year": 2001})
    try:
        report = mt.merge_papers(paper["id"], [dup["id"]], dry_run=True)
        assert report["dry_run"] and report["removed"] == [dup["id"]]
        assert get_paper(d, dup["id"]) is not None
        assert "error" in mt.merge_papers(paper["id"], [paper["id"]])
    finally:
        delete_paper(d, dup["id"])


def test_delete_paper_needs_confirm():
    d = get_driver()
    p = create_paper(d, {"title": "Maintenance Tool Delete Test"})
    res = mt.delete_paper(p["id"])
    assert res["status"] == "preview" and get_paper(d, p["id"]) is not None
    with patch("services.drive.delete_file"):
        res = mt.delete_paper(p["id"], confirm=True)
    assert res["status"] == "deleted" and get_paper(d, p["id"]) is None


def test_find_duplicates_rejects_unknown_class():
    assert "error" in mt.find_duplicates("nonsense")
