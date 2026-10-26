# Library

The Library is the main page of PaperManager (`/`). It shows all papers in your collection and provides powerful search and filtering tools.

---

## Dashboard

When no filters are active you see a dashboard at the top showing:

- **Count cards** — total papers, authors, topics, tags, projects
- **Papers by year** bar chart
- **Top topics** list
- **Recently added** papers

---

## Search

Type in the search box at the top. Results appear as you type (250 ms after the last
keystroke, or at once on **Enter**), ranked by relevance, and every row says **why** it matched:
chips such as *Title*, *Author: Tero Karras*, *Topic: Diffusion Models*, *Your note*,
*Highlight*, *Full text* or *Meaning 0.78*, and one or two passages with the matched words
marked.

### What is searched

| Where | Weight |
|---|---|
| DOI or arXiv id typed as the query | exact match, always first |
| Title | highest; extra when every word or the whole query is in the title |
| Authors | high; a query that is someone's name puts their papers first |
| Your notes and your PDF highlights (with their comments) | high |
| Topics, tags | medium |
| Abstract, AI summary, extracted claims | medium |
| Venue | low |
| Extracted full text of the PDF | lowest (every word must occur in it) |

A paper has to contain **every word** of the query somewhere in those fields (one word in the
author list and another in the title is fine). If no paper does, the papers that contain some
of the words are shown with a note saying so. Papers cited by many other papers in your
library rank a little higher among equally good matches.

Case and accents never matter: `edm`, `EDM` and `Edm` find the same papers, as do `Kynkaanniemi`
and `Kynkäänniemi`, in the search, the suggestions and the filters.

### Syntax

| You type | It finds |
|---|---|
| `diffusion` | diffusion, diffusions, Diffusion-based (every word is also a prefix) |
| `diffus*` | any word starting with *diffus* |
| `scroe based` | score-based: words of 5+ letters tolerate one typo |
| `"flow matching"` | the exact phrase only |
| `alphafold3` | AlphaFold3 and AlphaFold 3 |
| `over-conditioning`, `co-folding` | the two parts next to each other (over-conditioning, over conditioning) and the joined word (cofolding) |
| `10.1038/s41586-024-07487-w`, `https://doi.org/…`, `2210.02747`, `arXiv:2210.02747` | that paper |
| `the`, `of`, `for` … | ignored unless the query has nothing else |

Other punctuation (`:`, brackets, slashes) is treated as a word break, so `title: diffusion` or
`SE(3)` are safe to type.

### Suggestions

From the second character on, a dropdown lists matching **papers** (by title), **authors**,
**topics**, **tags** and **projects** with their paper counts. Use ↑ / ↓ and **Enter**, or click:
a paper opens it; an author, topic, tag or project becomes a filter (and the typed text is
cleared). **Esc** closes the list.

### Modes, sort, references

Above the results:

- **Exact** matches words only. **Hybrid** (the default) also ranks papers whose title and
  abstract *mean* something close to the query, which helps for questions in plain language
  ("why do co-folding models collapse to one pose"). **Meaning** ranks by meaning alone. Meaning
  search needs a one-time embedding of the library in the background (a few minutes); until it
  is ready, the page says so and shows exact matches.
- **Sort**: Relevance (default with a query), Newest added, Year, Title. The sort in Settings
  applies to browsing without a query.
- **References**: also search the cited references that have no PDF in your library (hidden by
  default; they rank below your own papers).

The query, filters, mode, sort and the references switch are kept in the URL, so a search can
be bookmarked or shared. When nothing matches, the page offers to search the references, to
search by meaning, or to remove the filters.

The **✦** button next to the box still turns a plain-language request into filters with the
AI model.

## Filters {#filters}

The left sidebar provides filters that narrow down the paper list:

| Filter | How it works |
|--------|-------------|
| **Tag** | Shows papers tagged with the selected tag |
| **Topic** | Shows papers about the selected research topic |
| **Project** | Shows papers belonging to the selected project |
| **Person** | Shows papers authored by or involving the selected person (pick an author in the search suggestions) |

Multiple filters can be combined, with or without a search query. Active filters appear as
removable chips below the search bar. Tag, topic and venue filters ignore case.

### Tag Categories

157 tags are seeded on startup:

=== "Source"
    `pdf-upload`, `from-url`, `from-references`, `bulk-import`, `from-linkedin`, `from-twitter`, `from-email`, `from-conference`, `from-newsletter`, `from-google-scholar`, `from-colleague`

=== "Workflow"
    `to-read`, `reading`, `read`, `important`, `revisit`, `needs-review`, `relevant`, `in-bibliography`, `reproduced`, `code-available`

=== "Content type"
    `review`, `benchmark`, `dataset`, `method`, `theory`, `negative-result`, `foundational`, `highly-cited`, `sota`

=== "Math"
    `algebra`, `topology`, `differential-geometry`, `probability`, `statistics`, `optimization`, `graph-theory`, `information-theory`, and more

=== "ML / AI"
    `machine-learning`, `deep-learning`, `transformers`, `LLMs`, `diffusion-models`, `GNNs`, `bayesian-inference`, and ~40 more

=== "Physics / Simulation"
    `statistical-mechanics`, `quantum-mechanics`, `molecular-dynamics`, `monte-carlo`, `biophysics`, and more

=== "Biology"
    `protein-structure`, `protein-folding`, `protein-design`, `genomics`, `CRISPR`, `single-cell`, `evolutionary-biology`, and more

=== "Drug discovery"
    `drug-design`, `molecular-docking`, `ADMET`, `QSAR`, `retrosynthesis`, `PROTAC`, and more

---

## View Options

### View mode

Toggle between **grid** and **list** view using the buttons in the top-right corner.

- **Grid** — compact cards ideal for large libraries
- **List** — more detail per row, easier to scan metadata

### Sort

| Sort option | Description |
|-------------|-------------|
| Date added ↓ | Newest first (default) |
| Date added ↑ | Oldest first |
| Year ↓ | Latest publication year first |
| Title A→Z | Alphabetical |

### Page size

Choose how many papers to show per page: **20**, **50**, **100**, or **All**.

---

## Paper Cards

Each paper card shows:

- **Title** and **year**
- **Authors** (up to 3, then "et al.")
- **Metadata source badge** (colour-coded: green / yellow / red)
- **Abstract preview** (toggleable in Settings)
- **Tags** as coloured pills
- **Quick edit** and **delete** buttons

Click any card to open the [Paper Detail](paper-detail.md) view.

---

## Adding Papers

From the Library page:

- **Drag and drop** a PDF file onto the page → upload flow starts
- Click the **+** button → choose PDF upload or URL/DOI ingest
- Navigate to **Bulk Import** in the nav bar for batch import

---

## Settings Reference

Library display settings are persisted to `localStorage`:

| Setting | Options | Default |
|---------|---------|---------|
| Default view | grid / list | grid |
| Default sort | date desc/asc, year desc, title asc | date desc |
| Abstract preview | on / off | on |
| Papers per page | 20 / 50 / 100 / all | 20 |

See [Settings](../user-guide/getting-started.md) for all available options.
