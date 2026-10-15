"""Tests for interactive concepts: service logic, model routing and the router.

No model is called: ``_run_json`` / the Claude Code and API entry points are
patched. The router tests patch the query layer in the router's namespace.
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import routers.concepts as rc
import services.concepts as sc
from main import app
from services.auth import get_current_user

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "attention.pdf"


# ── Page text and batching ───────────────────────────────────────────────────

def test_page_texts_from_pdf_reads_pages_with_collapsed_whitespace():
    pages = sc.page_texts_from_pdf(FIXTURE_PDF.read_bytes())  # one-page stub PDF
    assert len(pages) == 1
    assert pages[0].startswith("Attention Is All You Need")
    assert "\n" not in pages[0] and "  " not in pages[0]


def test_batch_pages_skips_empty_pages_and_caps_length():
    pages = ["a", "", "b", "c", "d", "e", "f"]
    batches = sc.batch_pages(pages, size=2)
    assert [[i for i, _ in b] for b in batches] == [[0, 2], [3, 4], [5, 6]]
    assert len(sc.batch_pages(["x"] * (sc.MAX_PAGES + 10), size=1000)[0]) == sc.MAX_PAGES


# ── Detection ────────────────────────────────────────────────────────────────

PAGES = [
    "Title page of the paper.",
    "We define the denoiser D(x, sigma) and train it with the EDM loss over noise levels.",
    "The sampler integrates the probability flow ODE from sigma_max down to zero.",
]


def _concept(page, label, vtype="formula", anchor="", context="A self-contained context sentence."):
    return {"page": page, "label": label, "type": vtype, "anchor": anchor, "context": context}


def test_detect_concepts_cleans_and_flags_anchors():
    reply = {"concepts": [
        _concept(1, "EDM loss", anchor="train it with the EDM loss"),
        _concept(2, "Probability flow ODE", "2d-anim", anchor="not on the page at all"),
        _concept(7, "Out of batch page"),                       # page not in batch
        _concept(1, "Bad type", vtype="3d"),                    # type no longer offered
        _concept(1, "edm LOSS", anchor="EDM loss"),            # duplicate label on page
    ]}
    with patch.object(sc, "_run_json", return_value=reply) as run:
        found = sc.detect_concepts(PAGES, "EDM")
    assert run.call_count == 1
    assert [(c["page"], c["label"]) for c in found] == [(1, "EDM loss"), (2, "Probability flow ODE")]
    assert found[0]["anchor_found"] is True
    assert found[1]["anchor_found"] is False
    system, prompt, schema, effort = run.call_args.args
    assert "===== PAGE_INDEX 1 =====" in prompt and "PAPER: EDM" in prompt
    assert schema is sc.DETECTION_SCHEMA and effort == sc.EFFORT_DETECT


def test_detect_concepts_caps_concepts_per_page():
    reply = {"concepts": [_concept(1, f"Concept {i}") for i in range(6)]}
    with patch.object(sc, "_run_json", return_value=reply):
        found = sc.detect_concepts(PAGES)
    assert len(found) == sc.MAX_CONCEPTS_PER_PAGE


def test_detect_concepts_keeps_good_batches_when_one_fails():
    pages = [f"page {i} text" for i in range(2 * sc.PAGES_PER_BATCH)]

    def fake(system, prompt, schema, effort):
        if "PAGE_INDEX 0 " in prompt:
            raise sc.ConceptsError("boom")
        return {"concepts": [_concept(sc.PAGES_PER_BATCH, "Survivor")]}

    with patch.object(sc, "_run_json", side_effect=fake):
        found = sc.detect_concepts(pages)
    assert [c["label"] for c in found] == ["Survivor"]


def test_detect_concepts_raises_when_every_batch_fails():
    with patch.object(sc, "_run_json", side_effect=sc.ConceptsError("down")):
        with pytest.raises(sc.ConceptsError, match="down"):
            sc.detect_concepts(PAGES)


def test_detect_concepts_on_empty_document_makes_no_call():
    with patch.object(sc, "_run_json") as run:
        assert sc.detect_concepts(["", ""]) == []
    run.assert_not_called()


def test_detection_schema_has_no_unsupported_constraints():
    """Structured outputs reject length / numeric constraints."""
    text = json.dumps([sc.DETECTION_SCHEMA, sc.SPEC_SCHEMAS])
    for key in ("minLength", "maxLength", "minimum", "maximum", "maxItems", "minItems"):
        assert key not in text


# ── Spec validation ──────────────────────────────────────────────────────────

def _graph(chart, data):
    return {"type": "graph", "title": "t", "caption": "c", "chart_type": chart,
            "x_label": "x", "y_label": "y", "data_json": json.dumps(data)}


def test_clean_spec_accepts_each_graph_shape():
    sc.clean_spec("graph", _graph("lines", {"series": [{"name": "a", "points": [[0, 1]]}]}))
    sc.clean_spec("graph", _graph("points", {"points": [[0, 1]]}))
    sc.clean_spec("graph", _graph("bars", {"bars": [{"label": "a", "value": 1}]}))


@pytest.mark.parametrize("spec", [
    _graph("function", {"fn": "Math.sin(x)"}),                 # code-carrying type removed
    _graph("lines", {"points": [[0, 1]]}),                     # shape does not match chart
    {**_graph("lines", {}), "data_json": "not json"},
])
def test_clean_spec_rejects_bad_graphs(spec):
    with pytest.raises(sc.ConceptsError):
        sc.clean_spec("graph", spec)


def test_clean_spec_rejects_wrong_type():
    with pytest.raises(sc.ConceptsError, match="Expected a formula"):
        sc.clean_spec("formula", {"type": "graph"})


def test_clean_spec_strips_code_fences_and_blanks_bad_urls():
    anim = sc.clean_spec("2d-anim", {"type": "2d-anim", "title": "t", "caption": "c",
                                     "setup_code": "```js\nreturn { draw: function () {} };\n```"})
    assert anim["setup_code"] == "return { draw: function () {} };"
    text = sc.clean_spec("2d-text", {"type": "2d-text", "title": "t", "caption": "c",
                                     "body_markdown": "Body [1]",
                                     "citations": [{"label": "a", "source": "s", "url": "javascript:alert(1)"},
                                                   {"label": "b", "source": "s", "url": "https://arxiv.org/abs/2206.00364"}]})
    assert [c["url"] for c in text["citations"]] == ["", "https://arxiv.org/abs/2206.00364"]


def test_generate_spec_uses_type_prompt_and_effort():
    concept = {"label": "EDM loss", "type": "formula", "context": "The EDM loss."}
    spec = {"type": "formula", "title": "EDM loss", "caption": "c", "main_latex": "L", "steps": []}
    with patch.object(sc, "_run_json", return_value=spec) as run:
        assert sc.generate_spec(concept, "EDM")["main_latex"] == "L"
    system, prompt, schema, effort = run.call_args.args
    assert "walkthroughs of equations" in system
    assert schema is sc.SPEC_SCHEMAS["formula"] and effort == sc.EFFORT_SPEC
    assert "REPAIR" not in prompt


def test_generate_spec_repair_sends_error_and_code_at_high_effort():
    concept = {"label": "Sampler", "type": "2d-anim", "context": "The sampler."}
    previous = {"spec": {"setup_code": "return {draw: oops};"}, "error": "oops is not defined"}
    fixed = {"type": "2d-anim", "title": "t", "caption": "c", "setup_code": "return { draw: function () {} };"}
    with patch.object(sc, "_run_json", return_value=fixed) as run:
        sc.generate_spec(concept, "", previous)
    _, prompt, _, effort = run.call_args.args
    assert "oops is not defined" in prompt and "return {draw: oops};" in prompt
    assert effort == sc.EFFORT_CODE


# ── Model routing ────────────────────────────────────────────────────────────

def test_routes_to_claude_code_sonnet_when_available():
    with patch.object(sc, "claude_code_available", return_value=True), \
         patch.object(sc, "run_structured_claude_code", return_value={"concepts": []}) as cc, \
         patch.object(sc, "_run_json_api") as api:
        sc._run_json("sys", "prompt", sc.DETECTION_SCHEMA, "low")
    cc.assert_called_once_with("sys", "prompt", sc.DETECTION_SCHEMA, model="sonnet", effort="low")
    api.assert_not_called()


def test_routes_to_api_when_claude_code_unavailable():
    with patch.object(sc, "claude_code_available", return_value=False), \
         patch.object(sc, "run_structured_claude_code") as cc, \
         patch.object(sc, "_run_json_api", return_value={"concepts": []}) as api:
        sc._run_json("sys", "prompt", sc.DETECTION_SCHEMA, "low")
    cc.assert_not_called()
    api.assert_called_once()


def _fake_api_client(stop_reason="end_turn", text='{"concepts": []}'):
    response = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])
    stream = MagicMock()
    stream.__enter__.return_value.get_final_message.return_value = response
    client = MagicMock()
    client.beta.messages.stream.return_value = stream
    return client


def test_api_call_uses_sonnet_structured_output_and_fallbacks():
    client = _fake_api_client()
    with patch.object(sc, "_personal_client", return_value=client):
        assert sc._run_json_api("sys", "prompt", sc.DETECTION_SCHEMA, "medium") == {"concepts": []}
    kwargs = client.beta.messages.stream.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5-5"
    assert kwargs["output_config"] == {"effort": "medium",
                                       "format": {"type": "json_schema", "schema": sc.DETECTION_SCHEMA}}
    assert kwargs["extra_body"] == {"fallbacks": "default"}
    assert "thinking" not in kwargs and "temperature" not in kwargs


@pytest.mark.parametrize("stop_reason,text,match", [
    ("refusal", "", "declined"),
    ("max_tokens", "{", "output tokens"),
    ("end_turn", "not json", "invalid JSON"),
])
def test_api_call_errors(stop_reason, text, match):
    with patch.object(sc, "_personal_client", return_value=_fake_api_client(stop_reason, text)):
        with pytest.raises(sc.ConceptsError, match=match):
            sc._run_json_api("sys", "prompt", sc.DETECTION_SCHEMA, "low")


def test_api_call_without_key_is_a_concepts_error():
    with patch.object(sc, "_personal_client", side_effect=ValueError("no key")):
        with pytest.raises(sc.ConceptsError, match="no key"):
            sc._run_json_api("sys", "prompt", sc.DETECTION_SCHEMA, "low")


# ── Router ───────────────────────────────────────────────────────────────────

PAPER = {"id": "p1", "title": "EDM", "drive_file_id": "drive1"}
STORED = {"id": "c1", "page": 1, "label": "EDM loss", "type": "formula",
          "anchor": "a", "anchor_found": True, "context": "ctx", "spec": None}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[get_current_user] = lambda: "tester"
    rc._detecting.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(rc, "get_driver", lambda: None)
    monkeypatch.setattr(rc, "concepts_backend", lambda: "claude-code")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        yield c


async def test_requires_login():
    app.dependency_overrides.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as c:
        resp = await c.get("/papers/p1/concepts")
    assert resp.status_code == 401


async def test_list(client, monkeypatch):
    monkeypatch.setattr(rc, "list_concepts", lambda d, pid: [STORED])
    resp = await client.get("/papers/p1/concepts")
    assert resp.status_code == 200
    assert resp.json() == {"concepts": [STORED], "backend": "claude-code"}


async def test_detect_stores_found_concepts(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    monkeypatch.setattr(rc, "download_pdf", lambda fid: b"%PDF")
    monkeypatch.setattr(rc, "page_texts_from_pdf", lambda b: ["p0", "p1"])
    monkeypatch.setattr(rc, "detect_concepts", lambda pages, title: [{"page": 1}])
    stored = {}
    monkeypatch.setattr(rc, "replace_concepts", lambda d, pid, cs: stored.setdefault("c", cs) and [STORED])
    resp = await client.post("/papers/p1/concepts/detect")
    assert resp.status_code == 200
    assert resp.json()["pages_total"] == 2 and resp.json()["concepts"] == [STORED]
    assert stored["c"] == [{"page": 1}]
    assert "p1" not in rc._detecting


async def test_detect_without_pdf_is_422(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: {**PAPER, "drive_file_id": None})
    assert (await client.post("/papers/p1/concepts/detect")).status_code == 422


async def test_detect_while_running_is_409(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    rc._detecting.add("p1")
    assert (await client.post("/papers/p1/concepts/detect")).status_code == 409


async def test_detect_model_failure_is_502_and_releases_lock(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    monkeypatch.setattr(rc, "download_pdf", lambda fid: b"%PDF")
    monkeypatch.setattr(rc, "page_texts_from_pdf", lambda b: ["p0"])

    def fail(pages, title):
        raise sc.ConceptsError("rate limited")

    monkeypatch.setattr(rc, "detect_concepts", fail)
    resp = await client.post("/papers/p1/concepts/detect")
    assert resp.status_code == 502 and "rate limited" in resp.json()["detail"]
    assert "p1" not in rc._detecting


async def test_viz_returns_cached_spec_without_a_model_call(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    monkeypatch.setattr(rc, "get_concept", lambda d, pid, cid: {**STORED, "spec": {"type": "formula"}})
    gen = MagicMock()
    monkeypatch.setattr(rc, "generate_spec", gen)
    resp = await client.post("/papers/p1/concepts/c1/viz")
    assert resp.status_code == 200 and resp.json()["spec"] == {"type": "formula"}
    gen.assert_not_called()


async def test_viz_generates_and_stores(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    monkeypatch.setattr(rc, "get_concept", lambda d, pid, cid: STORED)
    monkeypatch.setattr(rc, "generate_spec", lambda c, title, prev=None: {"type": "formula", "main_latex": "L"})
    monkeypatch.setattr(rc, "set_concept_spec",
                        lambda d, pid, cid, spec, err=None: {**STORED, "spec": spec, "spec_error": err})
    resp = await client.post("/papers/p1/concepts/c1/viz")
    assert resp.status_code == 200
    assert resp.json()["spec"]["main_latex"] == "L" and resp.json()["spec_error"] is None


async def test_viz_failure_records_error(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    monkeypatch.setattr(rc, "get_concept", lambda d, pid, cid: STORED)

    def fail(c, title, prev=None):
        raise sc.ConceptsError("bad graph")

    monkeypatch.setattr(rc, "generate_spec", fail)
    saved = {}
    monkeypatch.setattr(rc, "set_concept_spec", lambda d, pid, cid, spec, err=None: saved.update(err=err))
    resp = await client.post("/papers/p1/concepts/c1/viz")
    assert resp.status_code == 502 and saved["err"] == "bad graph"


async def test_repair_passes_previous_spec_and_error(client, monkeypatch):
    old = {"type": "2d-anim", "setup_code": "x"}
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    monkeypatch.setattr(rc, "get_concept", lambda d, pid, cid: {**STORED, "type": "2d-anim", "spec": old})
    seen = {}

    def gen(c, title, prev=None):
        seen["prev"] = prev
        return {"type": "2d-anim", "setup_code": "y"}

    monkeypatch.setattr(rc, "generate_spec", gen)
    monkeypatch.setattr(rc, "set_concept_spec", lambda d, pid, cid, spec, err=None: {**STORED, "spec": spec})
    resp = await client.post("/papers/p1/concepts/c1/repair", json={"error": "draw is not a function"})
    assert resp.status_code == 200
    assert seen["prev"] == {"spec": old, "error": "draw is not a function"}


async def test_repair_without_spec_is_409(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    monkeypatch.setattr(rc, "get_concept", lambda d, pid, cid: STORED)
    resp = await client.post("/papers/p1/concepts/c1/repair", json={"error": "e"})
    assert resp.status_code == 409


async def test_unknown_concept_is_404(client, monkeypatch):
    monkeypatch.setattr(rc, "get_paper", lambda d, pid: PAPER)
    monkeypatch.setattr(rc, "get_concept", lambda d, pid, cid: None)
    assert (await client.post("/papers/p1/concepts/nope/viz")).status_code == 404


def test_detect_batches_see_the_request_user():
    """Worker threads must inherit the request context (regression: they did not)."""
    from services.auth import get_request_user, reset_request_user, set_request_user

    seen = []

    def fake(system, prompt, schema, effort):
        seen.append(get_request_user())
        return {"concepts": []}

    pages = [f"page {i}" for i in range(3 * sc.PAGES_PER_BATCH)]
    token = set_request_user("niklas")
    try:
        with patch.object(sc, "_run_json", side_effect=fake):
            sc.detect_concepts(pages)
    finally:
        reset_request_user(token)
    assert seen == ["niklas"] * 3
