# Library Search

The Library page's search box, `GET /search`, `GET /search/suggest` and the MCP tools
`library_search` and `search_papers` all run one ranked search over the library. Code:
`backend/services/library_search/` (`query.py` parsing and matching, `ranking.py` scoring and
fusion, `engine.py` Neo4j retrieval, `suggest.py` type-ahead, `semantic.py` embedding store),
called through `db/queries/search.py::search_papers`. Frontend: `pages/Library.tsx` and
`components/search/` (`SearchBox`, `SearchResultRow`, `Highlight`, `searchUtils`).

---

## Query parsing (`query.py`)

A query is split into **units**, each of which a hit has to contain somewhere:

| Input | Unit | Lucene clause |
|---|---|---|
| a term of 3+ characters | term, prefix | `diffusion^2 OR diffusion* OR diffusion~1` |
| alphabetic term of 5+ characters | term, prefix, one edit | `~1` finds `scroe` → "score", `modeling` → "modelling" |
| term of 1–2 characters, a number | exact term | `3` |
| `word*` | explicit prefix, no fuzziness | `diffus*` |
| `"two words"` | phrase, required | `"two words"` |
| letters + number (`alphafold3`, `boltz2`) | term plus the spaced phrase | `... OR "alphafold 3"` |
| one word with punctuation inside (`over-conditioning`, `Boltz-2`, `SE(3)`) | phrase of its parts; with a hyphen also the joined word | `("over conditioning" OR overconditioning)` |

- Tokens are what is left between non-letters/digits, so `over-conditioning`, `title: x` and
  `a:b (c)` never reach the Lucene parser with syntax in them; every term is also passed
  through `escape_lucene`. English stop words (Lucene's classic set) are dropped unless the
  query has nothing else. At most 12 units, 500 characters.
- Case and accents never matter: query tokens are folded (`fold()`: NFKD, combining marks
  removed, ø/ł/ß/æ/œ mapped, lower case) exactly as the `standard-folding` analyzer folds the
  indexed text. `EDM`, `edm`, `Edm` and `Kynkaanniemi` / `Kynkäänniemi` build identical queries.
- The whole unquoted query (2–8 tokens) is added as a boosted optional phrase.
- A query that is a DOI (bare, `doi:`, doi.org URL) or an arXiv id (`2210.02747`, `arXiv:…v2`,
  arxiv.org URL) is looked up by `toLower(p.doi)` / `p.arxiv_id` first (also `10.48550/arxiv.<id>`
  and `arXiv:<id>` spellings); only when nothing has that identifier does the text search run.

## Indexes (`db/schema.py`)

All search indexes use the `standard-folding` analyzer (lower case, accents folded, English
stop words removed). `_ensure_fulltext` compares each existing index's analyzer, properties and
consistency with `_SEARCH_INDEXES` at startup and drops and rebuilds any that differ; on the
production library (8.7k papers, 376 with full text) all six were online again by the end of the
~15 s backend restart that migrated them.

| Index | Nodes | Properties | Notes |
|---|---|---|---|
| `paper_search` | Paper | title, abstract, summary | queried with `title:(…)^4 OR abstract:(…) OR summary:(…)^0.7` |
| `entity_name_search` | Person, Topic, Tag, Project | name | authors/topics/tags in search; all four in suggest |
| `note_search` | Note | content | |
| `annotation_search` | Annotation | highlighted_text, note | the user's highlights and their comments |
| `claim_search` | Claim | text | |
| `paper_text_search` | Paper | venue, raw_text | eventually consistent (uploads do not wait); 13 MB on disk for 36 MB of text, populated in < 4 s |

`message_search` (conversations) keeps its original analyzer.

## Retrieval (`engine.py`)

One Lucene query per source, run in parallel on separate sessions (thread pool of 8), each
restricted by the same filter predicate before `LIMIT`:

| Source | Query | Limit | Returns |
|---|---|---|---|
| paper | any unit, title/abstract/summary | 1000 | abstract, summary (for coverage, snippets) |
| entity | any unit on names, best 200 entities → `AUTHORED_BY` / `ABOUT` / `TAGGED` papers | 5000 | matched name |
| venue | any unit on `venue` | 300 | venue |
| fulltext | **every** unit on `raw_text` (`+a +b`) | 300 | — |
| note, highlight, claim | any unit | 300 each | the matched text (highlight page) |
| identifier | DOI / arXiv equality | — | — |

The filter predicate (`filter_clause`) holds tag, topic, project id, project name-or-id (MCP),
person id (`AUTHORED_BY|INVOLVES`), venue, year range, reading status, bookmarked, reference
stubs and `paper_visibility_clause`. Tag, topic, venue and status compare with `toLower` on both
sides. Reference stubs are papers tagged `from-references`; `include_references=false` drops them.

Every row carries `cited` = `COUNT { (p)<-[:CITES]-() }`, the papers in the library citing it.
A source that fails (an index still populating) is skipped and named in `failed_sources`.

## Scoring (`ranking.py`)

Lucene scores are not comparable across indexes, so per query each source's scores are divided
by the best score that source returned, then weighted:

| Source | Weight |
|---|---|
| identifier | 20 |
| paper (title^4 / abstract / summary^0.7 inside Lucene) | 4 |
| author | 3 |
| note, highlight | 2.5 |
| topic | 2 |
| tag, claim, fulltext | 1.5 |
| venue | 1 |

Bonuses, computed in Python from the title and matched names: every unit in the title +3, the
query as a phrase in the title +2, title equal to the query +4, every unit in one author's name
+5 (papers *by* Karras before papers citing Karras).

**Coverage.** A unit is covered when it occurs in the title or any matched text (author, topic,
tag, venue, abstract, summary, note, highlight, claim); a full-text hit covers every unit (its
query required all of them). `Coverage` builds, once per query, the set of word forms that
satisfy each term (the term, words it prefixes, words within one edit, found by length buckets
over the vocabulary of all candidate texts), so checking 1,000 candidates is a few set
intersections each. Phrases and word+number units use the regex `UnitMatcher`.

```
score = (Σ weight · score/max + bonuses) · (0.4 + 0.6 · coverage)
        · 0.6 if reference stub · (1 + 0.12 · ln(1 + cited))
```

Only hits with coverage 1 are returned. If none has it, all hits are returned ordered by score
and the response says `relaxed: true`. Ties break on title, then id. `total` is the number of
hits after this filter; `skip` / `limit` page it. `sort` (`relevance`, `date_desc`, `date_asc`,
`year_desc`, `year_asc`, `title_asc`) reorders the full ranked list before paging.

`matched_fields` lists where a hit matched, in the order `doi, title, author, topic, tag, venue,
abstract, summary, note, highlight, claim, fulltext, semantic`. `matched_in` keeps the old
coarse string (`note+paper`: metadata fields map to `paper`).

## Snippets and marks

Per hit, up to `snippets` (default 2, max 6) passages, preferring the user's own material:
note, highlight (with `page`), abstract, summary, claim, full text. A passage is the ~240
character window with the most distinct units, snapped to word boundaries, markdown markers
removed, `…` where cut. `marks` and `title_marks` are `[start, end)` ranges in **code points**
(Python string indices); the frontend splits with `Array.from` so astral characters do not shift
them, and renders text nodes plus `<mark>`, never HTML. For a full-text passage Neo4j locates the
first occurrence of the most specific needle (`split(toLower(raw_text), needle)[0]`, Cypher has
no indexOf) and returns only 1,400 characters around it.

## Semantic and hybrid (`semantic.py`)

- Model: the conference explorer's BAAI/bge-small-en-v1.5 (`services/conferences/embedder.py`,
  384-dim unit vectors, CPU, query instruction prefix for short queries).
- Text per paper: title + abstract (else the cleaned summary), first 1,500 characters.
- Store: `<LIBRARY_SEARCH_DIR or /data/library_search>/emb.npy` (float32, N × 384) and
  `meta.json` (`model`, `ids`, `hashes` = sha1 of each embedded text). Written atomically
  (temp file + rename), every 2,048 new vectors during a build.
- A daemon thread started in the FastAPI lifespan loads the file, loads the model, then syncs
  every `LIBRARY_SEMANTIC_INTERVAL` s (600): new papers and papers whose text hash changed are
  embedded, deleted ones dropped. First build on production: 8,698 papers in 214 s on four CPU
  threads, 13.4 MB. `LIBRARY_SEMANTIC=false` turns it off.
- Requests never load the model: until the thread has it, `query()` returns nothing and the
  search answers lexically (`mode: "lexical"` in the response, `semantic.state` says why).
- `query()` embeds the query (≈10–30 ms), takes the 200 nearest by dot product, then keeps those
  passing the filters with cosine ≥ max(0.62, best − 0.12), at most 100.
- `mode=semantic`: those hits by cosine; if there are none, the lexical answer.
- `mode=hybrid`: weighted reciprocal-rank fusion, `w / (20 + rank)`, of the lexical and semantic
  lists. Lexical weight 1.0 (0.8 for 4 units, 0.4 for 5+, ×0.6 when relaxed: long questions match
  every word somewhere in many long full texts); semantic weight 0.7 × clip((best − 0.6)/0.2, 0, 1),
  so jargon the model does not know (`over-conditioning`, best ≈ 0.66) barely moves the order.
- The MCP server is a separate process without the thread; `library_search` calls
  `ensure_loaded()` (reads the file, loads the model once) and searches in hybrid mode.

## Suggest (`suggest.py`)

`GET /search/suggest?q=&limit=5`: every token a required prefix (`tero kar` → `+tero* +kar*`;
finished stop words dropped, a trailing stop word optional). Two queries: `paper_search` on
titles for library papers (no reference stubs, visibility applied) and `entity_name_search`
(limit 80) for Person/Topic/Tag/Project with paper counts; projects pass
`project_visibility_clause`. Entities rank by Lucene score + 0.5 · ln(1 + papers), entities
without papers last. 15–30 ms server-side on the production library.

## Response

```json
{"results": [{"id": "...", "title": "...", "score": 9.1, "matched_in": "note+paper",
   "matched_fields": ["title", "author", "note"], "matches": {"author": ["Tero Karras"]},
   "snippets": [{"field": "note", "text": "…the EDM preconditioning…", "marks": [[4, 7]]}],
   "title_marks": [[32, 41]], "authors": ["Tero Karras", "..."], "is_reference": false,
   "similarity": 0.78, "text_chars": 81234, "has_note": true, "highlight_count": 3,
   "projects": ["MasterThesis"], "...paper fields": "..."}],
 "total": 38, "mode": "hybrid", "relaxed": false, "failed_sources": [], "took_ms": 112.4,
 "semantic": {"state": "ready", "indexed": 8698, "top_similarity": 0.81, "...": "..."}}
```

Without `q` the endpoint is the filter-only listing (`matched_in: "filter"`, `total` from a
count query, `sort` defaults to `date_desc`). `raw_text` and `embedding` are never returned.

## Frontend

- `SearchBox`: the input runs ahead of the URL; the URL's `q` is committed 250 ms after the last
  keystroke (history `replace`), immediately on Enter. Suggestions are fetched 80 ms after the
  last keystroke from 2 characters on, previous request aborted; ↑/↓/Enter/Esc, mouse. Picking
  a paper opens it; an author sets `person_id`, a topic `topic`, a tag `tag`, a project
  `project_id`, and clears the text.
- URL: `q`, the filters, `sort`, `mode` (absent = hybrid), `refs=1` (include reference stubs).
  The page number is local state keyed by the URL, so any change resets it to 1.
- With a query: rows (`SearchResultRow`) in server order, paged server-side (`skip`/`limit` =
  papers-per-page setting, 200 for "All"); the settings sort only applies to browsing. Stale
  responses are dropped by request key; while a new query loads, the old rows stay dimmed
  rather than disappearing.

## Tests and relevance check

- `tests/test_library_search.py`: parsing, escaping, folding, Lucene strings, matcher/marks,
  coverage, scoring, fusion, suggest ranking, semantic helpers, engine merge/paging/visibility
  with a scripted driver (no Neo4j).
- `tests/test_search_demo.py`: the demo library on a real Neo4j: author+title, typos, DOI/arXiv,
  snippets, reference stubs, sort/paging, case and accent variants, case-insensitive filters,
  suggest and its visibility.
- `frontend/src/components/search/*.test.tsx`, `frontend/src/pages/Library.test.tsx`.
- `backend/scripts/search_relevance_check.py`: 26 realistic queries against the real library
  (expected paper in the top 3). Before this search (Lucene OR over `paper_search` +
  `note_search`, no escaping): 17/26; after: 26/26 lexical and hybrid. `--impl` scores any other
  `search_papers` implementation.
