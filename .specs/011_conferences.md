# Conference explorer — developer context

User guide: `docs/user-guide/conferences.md`. This file is the how.

## Shape

```
backend/services/conferences/
  catalog.py       Series + years + source per conference-year (key "neurips2026")
  sources.py       fetch(edition) -> rows in one shape (miniconf feed or Paper Copilot list)
  institutions.py  split_and_normalise(raw) -> [(canonical name, "A"|"I")], ALIASES table
  areas.py         AREAS taxonomy (24), prototypes(embed_fn), assign(emb, protos)
  embedder.py      bge-small-en-v1.5 via transformers on CPU; embed(texts), embed_query(text)
  store.py         build(key), worker queue, start_auto_build(), load(key) -> Dataset, queries
backend/routers/conferences.py      /conferences/* HTTP API
backend/tools/conference_tools.py   MCP: list_conferences, conference_topic, conference_institution
frontend/src/pages/Conferences.tsx  /conferences (landing) and /conferences/:key (one conference)
frontend/src/components/conferences/  AreaBar, PaperRow, InstitutionsView, InstitutionCard, TopicView
```

No Neo4j: conference data lives on disk, never as Paper nodes. Neo4j is touched only for the
library title match (visibility-filtered, cached 2 min per user) and "+ Library".

## Storage

`<CONFERENCE_DATA_DIR or /data/conferences>/<key>/`:

- `dataset.json`: meta + `papers` + `insts`. Paper rows use short keys: `id` (sha1 of the folded
  title, 10 hex), `t` title, `a` abstract, `au` author names, `ai` per-author institution indices,
  `i` unique institution indices, `ar` area index (-1 until indexed), `d` decision, `tr` track,
  `s` session(s), `u` conference page, `f` forum / OpenReview, `nt` the site's own topic, `kw`.
  Institution rows: `n` name, `s` sector, `p` papers, `f` fractional, `a` per-area counts, `r` rank,
  `slug`.
- `emb.npy`: float16, (papers, 384), unit rows, same order as `papers`.
- `status.json`: `state` in none / queued / fetching / normalising / embedding / ready / partial /
  unavailable / error, plus `progress`, `message`, counts. A state left "building" by a restart is
  read back as ready / partial / none from the files present.
- `models/` (shared): the Hugging Face cache for the embedder.

`store.load` keeps up to `CONFERENCE_CACHE_MAX` (8) datasets in memory, keyed by the
dataset file's mtime, so a rebuild is picked up without a restart.

## Build

One daemon thread drains a queue, one conference at a time (`request_build` is idempotent while
queued). `dataset.json` is written twice: after normalising (institution views work) and after
embedding (areas, semantic search). Text embedded per paper: `title. abstract`, or
`title. keywords` without an abstract; batches are sorted by length (padding dominates CPU time).
Area prototypes: mean of the area's phrases as "A research paper about {phrase}.".

`start_auto_build()` runs from the FastAPI lifespan: queues `CONFERENCES_DEFAULT` entries that are
missing / partial / failed, this year's ones older than `CONFERENCES_REFRESH_DAYS`, and this year's
"unavailable" ones (they may have been published since). `CONFERENCES_AUTO=false` turns it off.

## Sources

- **miniconf**: `https://<host>/static/virtual/data/<conf>-<year>-orals-posters.json` (`results`,
  `count`, `next`). An oral is listed twice (poster + talk) and NeurIPS 2026 lists a paper once per
  city: rows are merged by folded title (not `paper_url`: some feeds reuse one OpenReview link),
  keeping the best decision and every session. When `next` points at the login-protected API the
  build keeps the first page, marks the dataset `partial` with `expected`, and adds the missing
  papers as title-only rows from `https://<host>/virtual/<year>/papers.html` (its `<noscript>`
  list), so topic search covers the conference.
- **Paper Copilot**: `raw.githubusercontent.com/papercopilot/paperlists/main/<dir>/<dir><year>.json`;
  large files are Git LFS pointers, fetched again from `media.githubusercontent.com`. Affiliations
  from `aff_unique_norm` + `aff_unique_index` (`"0+1;1"` = author 1 at institutions 0 and 1),
  falling back to raw `aff`. Statuses containing "reject" or "withdraw" are dropped.
- OpenReview's own API refuses anonymous clients (challenge page), so it is not a source.

## Maths

- Topic search: cosine similarity of the query vector to every paper (`emb @ q`), top-k, then
  per-institution counts over those k; ties broken by summed similarity.
- Areas: centre papers and prototypes on the conference's mean paper vector before the argmax.
  Without centring the most generic area (efficiency) took 21 % of NeurIPS 2026, 12 % after refinement
  (median paper–prototype cosine 0.80, median top-two margin 0.016); with it the largest area holds 7 %. Then two rounds of
  prototype := normalise(½ prototype + ½ mean of its papers) and reassign.
- Fractional counting: author = 1/n of the paper, split equally over the author's institutions.

## Routes

The API never uses a path a page uses: `/conferences/catalog` (not `/conferences`) and
`/conferences/{key}/overview` (not `/conferences/{key}`). With equal paths the browser answers
the `fetch` from the cached page HTML. nginx sends `/conferences*` requests that ask for
`text/html` to the SPA and everything else to the backend.

## Tests

`backend/tests/test_conferences.py`: normaliser cases, both parsers on fixtures (monkeypatched
`_get_json`), counting / ranking / fractional on a hand-made dataset, topic search (semantic
with a stubbed `embed_query`, keyword fallback), area assignment on synthetic clusters, and
the endpoints. No network, no model, no Neo4j. `frontend/src/pages/Conferences.test.tsx` covers
the landing page, the overview and a topic query from the URL.
