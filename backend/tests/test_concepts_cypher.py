"""Cypher regression tests for the Concept queries, against a live Neo4j.

Need a running Neo4j (run_tests.sh / CI provide one); they skip when it is down.
"""
import pytest

from db.connection import get_driver
from db.queries.concepts import (
    delete_concepts,
    get_concept,
    list_concepts,
    replace_concepts,
    set_concept_spec,
)
from db.queries.papers import create_paper, delete_paper


@pytest.fixture
def driver():
    try:
        drv = get_driver()
        drv.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 — any connection problem means "skip"
        pytest.skip(f"Neo4j not reachable: {exc}")
    return drv


@pytest.fixture
def paper(driver):
    p = create_paper(driver, {"title": "Concepts Cypher Paper"})
    yield p
    delete_paper(driver, p["id"])


def _concept(page, label):
    return {"page": page, "label": label, "type": "formula", "anchor": "anchor text",
            "anchor_found": True, "context": "Context sentence."}


def test_replace_list_get_set_delete(driver, paper):
    pid = paper["id"]
    stored = replace_concepts(driver, pid, [_concept(2, "B"), _concept(0, "A"), _concept(2, "C")])
    assert [(c["page"], c["label"]) for c in stored] == [(0, "A"), (2, "B"), (2, "C")]
    assert all(c["spec"] is None for c in stored)

    # Replacing drops the old set.
    stored = replace_concepts(driver, pid, [_concept(1, "Only")])
    assert [c["label"] for c in stored] == ["Only"]
    cid = stored[0]["id"]

    spec = {"type": "formula", "main_latex": "x^2", "steps": []}
    updated = set_concept_spec(driver, pid, cid, spec)
    assert updated["spec"] == spec and updated["spec_error"] is None
    assert get_concept(driver, pid, cid)["spec"] == spec

    errored = set_concept_spec(driver, pid, cid, spec, "render failed")
    assert errored["spec"] == spec and errored["spec_error"] == "render failed"

    assert get_concept(driver, "other-paper", cid) is None
    assert delete_concepts(driver, pid) == 1
    assert list_concepts(driver, pid) == []


def test_delete_paper_removes_its_concepts(driver):
    p = create_paper(driver, {"title": "Concepts Cascade Paper"})
    cid = replace_concepts(driver, p["id"], [_concept(0, "A")])[0]["id"]
    assert delete_paper(driver, p["id"]) is True
    with driver.session() as session:
        left = session.run("MATCH (c:Concept {id: $id}) RETURN count(c) AS n", id=cid).single()["n"]
    assert left == 0
