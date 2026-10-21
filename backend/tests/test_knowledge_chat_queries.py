"""The Knowledge Chat query layer against a real Neo4j.

The in-memory fake driver only understands the Cypher patterns of older
queries, so these tests need a throwaway Neo4j and are skipped without one.
``backend/scripts/run_tests.sh tests/test_knowledge_chat_queries.py`` provides
one (``PM_TESTS_ALLOW_DB=1`` with ``NEO4J_URI``); so does setting
``NEO4J_TEST_URI`` / ``NEO4J_TEST_PASSWORD`` to a scratch container.

Never point NEO4J_TEST_URI at a library you care about: every test wipes the
nodes it creates, but the fixtures assume an empty database.
"""
import os

import pytest

import db.queries.conversations as q

URI = os.environ.get("NEO4J_TEST_URI") or (os.environ.get("NEO4J_URI") if os.environ.get("PM_TESTS_ALLOW_DB") == "1" else None)
PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD") or os.environ.get("NEO4J_PASSWORD", "")
pytestmark = pytest.mark.skipif(not URI, reason="NEO4J_TEST_URI not set (needs a throwaway Neo4j)")


@pytest.fixture
def driver():
    from neo4j import GraphDatabase

    drv = GraphDatabase.driver(URI, auth=(os.environ.get("NEO4J_TEST_USER", "neo4j"), PASSWORD))
    with drv.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
        s.run("CREATE (:Paper {id: 'p1', title: 'AlphaFold 3', year: 2024}), (:Paper {id: 'p2', title: 'RFdiffusion', year: 2023})")
    yield drv
    with drv.session() as s:
        s.run("MATCH (n) DETACH DELETE n")
    drv.close()


def _chat(driver, title="Chat", turns=2):
    c = q.create_conversation(driver, title)
    for i in range(turns):
        q.add_message(driver, c["id"], "user", f"question {i}", ["p1"], 1)
        q.add_message(driver, c["id"], "assistant", f"answer {i}", ["p1", "p2"], 1)
    return c


def test_list_excludes_per_paper_chats_and_counts_messages(driver):
    c = _chat(driver, "Library chat")
    q.create_paper_conversation(driver, "p1", "Paper chat")
    rows = q.list_conversations(driver)
    assert [r["title"] for r in rows] == ["Library chat"]
    assert rows[0]["id"] == c["id"] and rows[0]["message_count"] == 4


def test_get_messages_returns_cited_papers_with_titles(driver):
    c = _chat(driver, turns=1)
    msgs = q.get_messages(driver, c["id"])
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert sorted(p["title"] for p in msgs[1]["papers"]) == ["AlphaFold 3", "RFdiffusion"]
    assert sorted(msgs[1]["paper_refs"]) == ["p1", "p2"]
    assert msgs[1]["concepts"] is None


def test_get_message_names_conversation_and_the_question_it_answers(driver):
    c = _chat(driver)
    answer = q.get_messages(driver, c["id"])[3]
    msg = q.get_message(driver, answer["id"])
    assert msg["conversation_id"] == c["id"]
    assert msg["question"] == "question 1"
    assert q.get_message(driver, "missing") is None


def test_set_message_concepts_stores_cards_and_status(driver):
    c = _chat(driver, turns=1)
    aid = q.get_messages(driver, c["id"])[1]["id"]
    q.set_message_concepts(driver, aid, None, "running")
    m = q.get_message(driver, aid)
    assert m["concepts_status"] == "running" and m["concepts"] is None
    cards = [{"label": "Loss", "type": "formula", "section": 1, "spec": {"type": "formula"}, "error": None}]
    q.set_message_concepts(driver, aid, cards, "done")
    assert q.get_message(driver, aid)["concepts"] == cards
    # a failed rerun keeps the earlier cards
    q.set_message_concepts(driver, aid, None, "failed", "boom")
    m = q.get_message(driver, aid)
    assert m["concepts"] == cards and m["concepts_status"] == "failed" and m["concepts_error"] == "boom"


def test_fork_strand_copies_through_the_answer_and_leaves_the_original(driver):
    c = _chat(driver, "Parent", turns=3)
    aid = q.get_messages(driver, c["id"])[1]["id"]
    q.set_message_concepts(driver, aid, [{"label": "x"}], "done")
    fork = q.fork_conversation(driver, c["id"], keep=2, kind="strand")
    assert fork["parent_id"] == c["id"] and fork["fork_at"] == 2 and fork["fork_kind"] == "strand"
    copied = q.get_messages(driver, fork["id"])
    assert [m["content"] for m in copied] == ["question 0", "answer 0", "question 1", "answer 1"]
    assert copied[1]["concepts"] == [{"label": "x"}]
    assert sorted(copied[1]["paper_refs"]) == ["p1", "p2"]
    assert {m["id"] for m in copied}.isdisjoint({m["id"] for m in q.get_messages(driver, c["id"])})
    assert len(q.get_messages(driver, c["id"])) == 6


def test_fork_edit_before_first_question_and_beyond_the_end(driver):
    c = _chat(driver, turns=2)
    assert q.get_messages(driver, q.fork_conversation(driver, c["id"], 0, "edit")["id"]) == []
    whole = q.fork_conversation(driver, c["id"], 9)
    assert whole["fork_at"] == 2 and len(q.get_messages(driver, whole["id"])) == 4


def test_fork_of_a_missing_conversation_raises(driver):
    with pytest.raises(ValueError):
        q.fork_conversation(driver, "missing", 1)


def test_fork_is_listed_and_named_by_its_first_question(driver):
    c = _chat(driver, "Parent", turns=1)
    fork = q.fork_conversation(driver, c["id"], 1)
    q.set_branch_label_if_empty(driver, fork["id"], "What about AF3?")
    q.set_branch_label_if_empty(driver, fork["id"], "a later question")
    q.set_branch_label_if_empty(driver, c["id"], "never on a root")
    rows = {r["id"]: r for r in q.list_conversations(driver)}
    assert rows[fork["id"]]["branch_label"] == "What about AF3?"
    assert rows[fork["id"]]["parent_id"] == c["id"]
    assert rows[c["id"]].get("branch_label") is None


def test_rename_and_delete(driver):
    c = _chat(driver, "Old", turns=1)
    assert q.rename_conversation(driver, c["id"], "New")["title"] == "New"
    assert q.rename_conversation(driver, "missing", "x") == {}
    q.delete_conversation(driver, c["id"])
    assert q.list_conversations(driver) == []
    with driver.session() as s:
        assert s.run("MATCH (m:Message) RETURN count(m) AS n").single()["n"] == 0
