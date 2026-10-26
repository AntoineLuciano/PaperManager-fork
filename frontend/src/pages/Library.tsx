import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { apiFetch, interpretSearch, searchLibrary } from "../api/client";
import PaperCard from "../components/PaperCard";
import PaperDrop from "../components/PaperDrop";
import EditPaperModal from "../components/EditPaperModal";
import EntityPanel from "../components/EntityPanel";
import ResearchGapPanel from "../components/ResearchGapPanel";
import SearchBox, { type PickedSuggestion } from "../components/search/SearchBox";
import SearchResultRow from "../components/search/SearchResultRow";
import { buildSearchParams, FILTER_KEYS, QUERY_PAGE_ALL } from "../components/search/searchUtils";
import type { EntityType } from "../components/EntityPanel";
import { useAppSettings } from "../contexts/SettingsContext";
import type { Paper, Person, Project, SearchMode, SearchResponse, T_IngestOut, Stats, VenueOut } from "../types";

const QUERY_SORTS: { value: string; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "date_desc", label: "Newest added" },
  { value: "year_desc", label: "Year ↓" },
  { value: "year_asc", label: "Year ↑" },
  { value: "title_asc", label: "Title A→Z" },
];
const MODES: { value: SearchMode; label: string; title: string }[] = [
  { value: "lexical", label: "Exact", title: "Words, prefixes and near-spellings only" },
  { value: "hybrid", label: "Hybrid", title: "Words and meaning combined (default)" },
  { value: "semantic", label: "Meaning", title: "Papers whose title and abstract mean something similar" },
];
export default function Library() {
  const { settings } = useAppSettings();
  const navigate = useNavigate();
  const [papers, setPapers]     = useState<Paper[]>([]);
  const [searchRes, setSearchRes] = useState<SearchResponse | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [stats, setStats]           = useState<Stats | null>(null);
  // Key of the request whose results are on screen; "loading" while it differs from the
  // key of what the URL asks for (no synchronous setState in the fetch effect).
  const [doneKey, setDoneKey]       = useState<string | null>(null);
  const [editingPaper, setEditingPaper] = useState<Paper | null>(null);
  const [activePanel, setActivePanel]   = useState<EntityType | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const [surprisingMe, setSurprisingMe] = useState(false);
  const [showResearchGaps, setShowResearchGaps] = useState(false);
  const [aiSearching, setAiSearching] = useState(false);
  const [personNames, setPersonNames] = useState<Record<string, string>>({});

  const q             = searchParams.get("q") ?? "";
  const activeTag     = searchParams.get("tag") ?? "";
  const activeTopic   = searchParams.get("topic") ?? "";
  const activeProject = searchParams.get("project_id") ?? "";
  const activePerson  = searchParams.get("person_id") ?? "";
  const activeStatus  = searchParams.get("reading_status") ?? "";
  const activeBookmarked = searchParams.get("bookmarked") === "true";
  const activeVenue   = searchParams.get("venue") ?? "";
  const querySort     = searchParams.get("sort") || "relevance";
  const queryMode     = (searchParams.get("mode") as SearchMode) || "hybrid";
  const withRefs      = searchParams.get("refs") === "1";
  const hasQuery      = q.trim().length > 0;
  const hasNarrowing  = FILTER_KEYS.some((k) => searchParams.get(k));
  const hasFilters    = hasQuery || hasNarrowing;

  // The text in the box runs ahead of the URL while typing; the URL follows debounced.
  const [input, setInput] = useState(q);
  const lastCommitted = useRef(q);
  useEffect(() => {
    if (q !== lastCommitted.current) {
      lastCommitted.current = q;
      setInput(q);
    }
  }, [q]);

  // Page number, reset whenever the query or a filter changes.
  const queryKey = searchParams.toString();
  const pageKey = `${queryKey}|${settings.defaultSort}|${settings.papersPerPage}`;
  const [pageState, setPageState] = useState({ key: pageKey, page: 1 });
  const page = pageState.key === pageKey ? pageState.page : 1;
  const setPage = (p: number) => setPageState({ key: pageKey, page: p });

  // Browsing (no query): sort client-side per settings. A query keeps the server's order.
  const sortedPapers = useMemo(() => {
    const sorted = [...papers];
    switch (settings.defaultSort) {
      case "date_asc":        return sorted.reverse();
      case "year_desc":       return sorted.sort((a, b) => (b.year ?? 0) - (a.year ?? 0));
      case "year_asc":        return sorted.sort((a, b) => (a.year ?? 0) - (b.year ?? 0));
      case "title_asc":       return sorted.sort((a, b) => a.title.localeCompare(b.title));
      case "rating_desc":     return sorted.sort((a, b) => (b.rating ?? 0) - (a.rating ?? 0));
      case "citations_desc":  return sorted.sort((a, b) => (b.citation_count ?? 0) - (a.citation_count ?? 0));
      default:                return sorted; // date_desc = API order
    }
  }, [papers, settings.defaultSort]);

  const perPage = settings.papersPerPage;
  const querySize = perPage || QUERY_PAGE_ALL;
  const totalPages = hasQuery
    ? Math.max(1, Math.ceil((searchRes?.total ?? 0) / querySize))
    : perPage === 0 ? 1 : Math.ceil(sortedPapers.length / perPage);
  const visiblePapers = perPage === 0 ? sortedPapers : sortedPapers.slice((page - 1) * perPage, page * perPage);

  const requestKey = `${queryKey}|${hasQuery ? page : 0}|${hasQuery ? perPage : 0}`;
  const loading = doneKey !== requestKey;
  const latestKey = useRef(requestKey);

  const loadPapers = async (params: URLSearchParams, pageNo: number, key: string) => {
    latestKey.current = key;
    const stale = () => latestKey.current !== key; // a newer keystroke won
    try {
      const hasQ = !!params.get("q")?.trim();
      const narrowed = FILTER_KEYS.some((k) => params.get(k));
      if (hasQ || narrowed) {
        const res = await searchLibrary(buildSearchParams(params, pageNo, perPage));
        if (stale()) return;
        setSearchRes(hasQ ? res : null);
        setPapers(res.results);
      } else {
        const res = await apiFetch<Paper[]>("/papers");
        if (stale()) return;
        setSearchRes(null);
        setPapers(res);
      }
    } catch {
      if (stale()) return;
      setPapers([]);
      setSearchRes(null);
    }
    setDoneKey(key);
  };

  useEffect(() => {
    if (searchParams.has("year_min") || searchParams.has("year_max")) {
      const next = new URLSearchParams(searchParams);
      next.delete("year_min");
      next.delete("year_max");
      setSearchParams(next, { replace: true });
      return;
    }
    // State is only set once the request resolves (loadPapers awaits first).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadPapers(searchParams, page, requestKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  useEffect(() => {
    apiFetch<Project[]>("/projects").then(setProjects).catch(() => {});
    apiFetch<Stats>("/stats").then(setStats).catch(() => {});
  }, []);

  // Name for the author chip when the page was opened with ?person_id=...
  useEffect(() => {
    if (activePerson && !personNames[activePerson]) {
      apiFetch<Person>(`/people/${activePerson}`)
        .then((p) => setPersonNames((m) => ({ ...m, [activePerson]: p.name })))
        .catch(() => {});
    }
  }, [activePerson, personNames]);

  const update = (mutate: (next: URLSearchParams) => void, replace = false) => {
    const next = new URLSearchParams(searchParams);
    mutate(next);
    setSearchParams(next, { replace });
  };

  const setFilter = (key: string, value: string) => update((next) => {
    if (next.get(key) === value) next.delete(key);
    else next.set(key, value);
  });

  const setParam = (key: string, value: string | null) => update((next) => {
    if (value) next.set(key, value);
    else next.delete(key);
  });

  const commitQuery = (text: string) => {
    if (text.trim() === q.trim()) return;
    lastCommitted.current = text;
    update((next) => {
      if (text.trim()) next.set("q", text);
      else next.delete("q");
    }, true);
  };

  const pickSuggestion = (s: PickedSuggestion) => {
    if (s.kind === "paper") {
      navigate(`/paper/${s.id}`);
      return;
    }
    // An author / topic / tag / project replaces the typed text with a filter.
    lastCommitted.current = "";
    setInput("");
    update((next) => {
      next.delete("q");
      if (s.kind === "author") {
        next.set("person_id", s.id);
        setPersonNames((m) => ({ ...m, [s.id]: s.name }));
      }
      if (s.kind === "topic") next.set("topic", s.name);
      if (s.kind === "tag") next.set("tag", s.name);
      if (s.kind === "project") next.set("project_id", s.id);
    });
  };

  const clearAll = () => {
    lastCommitted.current = "";
    setInput("");
    setSearchParams(new URLSearchParams());
  };

  const clearNarrowing = () => update((next) => { FILTER_KEYS.forEach((k) => next.delete(k)); });

  const toggleBookmarked = () => update((next) => {
    if (activeBookmarked) next.delete("bookmarked");
    else next.set("bookmarked", "true");
  });

  const surpriseMe = async () => {
    setSurprisingMe(true);
    try {
      const paper = await apiFetch<Paper>("/papers/random");
      navigate(`/paper/${paper.id}`);
    } catch {
      // no papers
    } finally {
      setSurprisingMe(false);
    }
  };

  const runAiSearch = async () => {
    const text = input.trim();
    if (!text || aiSearching) return;
    setAiSearching(true);
    try {
      const result = await interpretSearch(text);
      const next = new URLSearchParams();
      if (result.keyword) next.set("q", result.keyword);
      if (result.tag)     next.set("tag", result.tag);
      if (result.topic)   next.set("topic", result.topic);
      if (result.venue)   next.set("venue", result.venue);
      if (result.year_min) next.set("year_min", String(result.year_min));
      if (result.year_max) next.set("year_max", String(result.year_max));
      setSearchParams(next);
    } catch { /* ignore */ } finally {
      setAiSearching(false);
    }
  };

  const refreshStats = () => apiFetch<Stats>("/stats").then(setStats).catch(() => {});

  const handleDeleted = (id: string) => {
    setPapers((prev) => prev.filter((p) => p.id !== id));
    refreshStats();
  };

  const handleUpdated = (updated: Paper) => {
    setPapers((prev) => prev.map((p) => p.id === updated.id ? updated : p));
    setEditingPaper(null);
  };

  const semanticNote = (() => {
    if (!searchRes || queryMode === "lexical" || searchRes.mode !== "lexical") return null;
    const s = searchRes.semantic;
    if (s && s.state !== "ready" && s.enabled) {
      return s.state === "building" && s.todo
        ? `Meaning search is still indexing (${s.done} / ${s.todo} papers); showing exact matches.`
        : "Meaning search is starting up; showing exact matches.";
    }
    return queryMode === "semantic" ? "Nothing in the library is close enough in meaning; showing exact matches." : null;
  })();

  return (
    <div className="h-[calc(100vh-53px)] overflow-y-auto">
      <main>
        {/* Search + upload + view toggle bar */}
        <div className="sticky top-0 z-20 bg-raised border-b border-line-s px-6 py-3 flex gap-2 items-center flex-wrap">
          <SearchBox
            value={input}
            onChange={setInput}
            onCommit={commitQuery}
            onPick={pickSuggestion}
            placeholder="Search titles, authors, notes, highlights, full text… or describe it and press ✦"
          >
            <button
              onClick={runAiSearch}
              disabled={aiSearching || !input.trim()}
              title="Let AI interpret your query into filters"
              className={`h-9 px-2.5 rounded-lg border text-sm font-semibold transition-colors shrink-0 ${
                aiSearching
                  ? "border-violet-300 text-violet-400 bg-violet-50 cursor-wait"
                  : "border-violet-200 text-violet-500 bg-white hover:bg-violet-50 hover:border-violet-400 disabled:opacity-30"
              }`}
            >
              {aiSearching
                ? <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
                : "✦"}
            </button>
          </SearchBox>

          {/* Reading status filter */}
          <select
            value={activeStatus}
            onChange={(e) => setParam("reading_status", e.target.value || null)}
            className="h-9 border border-gray-200 rounded-lg px-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 bg-white text-gray-600 shrink-0"
          >
            <option value="">All statuses</option>
            <option value="unread">Unread</option>
            <option value="reading">Reading</option>
            <option value="read">Read</option>
          </select>

          {/* Right-side icon buttons — all h-9 w-9 */}
          <div className="flex items-center gap-2 shrink-0 ml-auto">
            {/* Bookmark filter */}
            <button
              onClick={toggleBookmarked}
              title={activeBookmarked ? "Showing bookmarked only — click to clear" : "Show bookmarked only"}
              className={`h-9 w-9 flex items-center justify-center rounded-lg border text-sm transition-colors ${
                activeBookmarked
                  ? "bg-amber-500 border-amber-500 text-white"
                  : "border-gray-200 text-gray-400 hover:text-amber-500 hover:border-amber-300"
              }`}
            >
              ★
            </button>

            {/* Surprise Me */}
            <button
              onClick={surpriseMe}
              disabled={surprisingMe}
              title="Open a random paper"
              className="h-9 w-9 flex items-center justify-center rounded-lg border border-gray-200 text-gray-400 hover:text-violet-600 hover:border-violet-300 transition-colors disabled:opacity-50"
            >
              {surprisingMe
                ? <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
                : <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19.5 12c0-3.866-3.134-7-7-7S5.5 8.134 5.5 12s3.134 7 7 7 7-3.134 7-7z"/><path strokeLinecap="round" strokeLinejoin="round" d="M9 9h.01M15 9h.01M9 15h.01M15 15h.01M12 12h.01"/></svg>
              }
            </button>

            {/* Research Gaps */}
            <button
              onClick={() => setShowResearchGaps(true)}
              title="Find research gaps"
              className="h-9 px-3 flex items-center justify-center gap-1.5 rounded-lg border border-gray-200 text-gray-600 hover:text-violet-600 hover:border-violet-300 transition-colors text-sm font-medium whitespace-nowrap"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
              </svg>
              <span>Find Gaps</span>
            </button>

            <PaperDrop onUploaded={(p: T_IngestOut) => {
              setPapers((prev) => [p, ...prev]);
              refreshStats();
            }} debug={settings.debugMode} />
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* Active filter chips */}
          {hasFilters && (
            <div className="flex flex-wrap gap-2 items-center">
              <span className="text-xs text-gray-500">Showing:</span>
              {q            && <Chip label={`"${q}"`}    onRemove={() => { lastCommitted.current = ""; setInput(""); setParam("q", null); }} />}
              {activeTag    && <Chip label={activeTag}   onRemove={() => setFilter("tag", activeTag)} />}
              {activeTopic  && <Chip label={activeTopic} onRemove={() => setFilter("topic", activeTopic)} />}
              {activePerson && (
                <Chip
                  label={`Author: ${personNames[activePerson] ?? "…"}`}
                  onRemove={() => setFilter("person_id", activePerson)}
                />
              )}
              {activeProject && (
                <Chip
                  label={projects.find((p) => p.id === activeProject)?.name ?? activeProject}
                  onRemove={() => setFilter("project_id", activeProject)}
                />
              )}
              {activeStatus && <Chip label={`Status: ${activeStatus}`} onRemove={() => setFilter("reading_status", activeStatus)} />}
              {activeBookmarked && <Chip label="★ Bookmarked" onRemove={toggleBookmarked} />}
              {activeVenue && <Chip label={`Venue: ${activeVenue}`} onRemove={() => setFilter("venue", activeVenue)} />}
              <button onClick={clearAll} className="text-xs text-gray-400 hover:text-gray-600 underline">
                Clear all
              </button>
            </div>
          )}

          {/* Dashboard — only shown when no filters active */}
          {!hasFilters && stats && (
            <Dashboard
              stats={stats}
              onTopicClick={(name) => setFilter("topic", name)}
              onEntityClick={(type) => setActivePanel(type)}
              onVenueClick={(name) => setFilter("venue", name)}
            />
          )}

          {hasQuery ? (
            <section className="space-y-3" aria-label="Search results">
              {/* Results header: count, mode, sort, references */}
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-xs text-ink-3" aria-live="polite">
                  {loading && !searchRes ? "Searching…" : searchRes && (
                    <>
                      <span className="font-semibold text-ink-2">{searchRes.total.toLocaleString()}</span>
                      {` result${searchRes.total === 1 ? "" : "s"}`}
                      {searchRes.took_ms != null && ` · ${Math.round(searchRes.took_ms)} ms`}
                      {loading && " · updating…"}
                    </>
                  )}
                </p>
                <div className="flex items-center gap-2 ml-auto">
                  <div role="group" aria-label="Search mode" className="flex rounded-lg border border-line overflow-hidden">
                    {MODES.map((m) => (
                      <button
                        key={m.value}
                        title={m.title}
                        aria-pressed={queryMode === m.value}
                        onClick={() => setParam("mode", m.value === "hybrid" ? null : m.value)}
                        className={`px-2.5 h-7 text-xs ${queryMode === m.value ? "bg-accent text-white" : "bg-raised text-ink-2 hover:text-accent"}`}
                      >
                        {m.label}
                      </button>
                    ))}
                  </div>
                  <label className="flex items-center gap-1 text-xs text-ink-2 cursor-pointer" title="Also search cited references that have no PDF in the library">
                    <input type="checkbox" checked={withRefs} onChange={() => setParam("refs", withRefs ? null : "1")} />
                    References
                  </label>
                  <select
                    aria-label="Sort results"
                    value={querySort}
                    onChange={(e) => setParam("sort", e.target.value === "relevance" ? null : e.target.value)}
                    className="h-7 border border-line rounded px-2 text-xs bg-raised text-ink-2 focus:outline-none focus:ring-2 focus:ring-violet-300"
                  >
                    {QUERY_SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
              </div>

              {semanticNote && <p className="text-xs text-amber">{semanticNote}</p>}
              {searchRes?.relaxed && searchRes.results.length > 0 && (
                <p className="text-xs text-amber">
                  No paper contains every word of “{q}”; showing papers that match some of them.
                </p>
              )}

              {searchRes && searchRes.results.length === 0 && !loading ? (
                <div className="bg-raised border border-line rounded-xl p-6 text-center space-y-3">
                  <p className="text-sm text-ink">
                    No papers match “{q}”{hasNarrowing ? " with these filters" : ""}.
                  </p>
                  <p className="text-xs text-ink-3">
                    Titles, authors, topics, tags, abstracts, your notes and highlights, claims and full texts were searched.
                  </p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {!withRefs && (
                      <button onClick={() => setParam("refs", "1")} className="px-3 py-1.5 text-xs border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent">
                        Search cited references too
                      </button>
                    )}
                    {queryMode !== "semantic" && (
                      <button onClick={() => setParam("mode", "semantic")} className="px-3 py-1.5 text-xs border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent">
                        Search by meaning
                      </button>
                    )}
                    {hasNarrowing && (
                      <button onClick={clearNarrowing} className="px-3 py-1.5 text-xs border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent">
                        Remove filters
                      </button>
                    )}
                  </div>
                </div>
              ) : (
                <ul className={`space-y-2 ${loading ? "opacity-60" : ""}`}>
                  {searchRes?.results.map((hit) => <SearchResultRow key={hit.id} hit={hit} />)}
                </ul>
              )}

              {searchRes && totalPages > 1 && (
                <Pager page={page} totalPages={totalPages} onPage={setPage} />
              )}
            </section>
          ) : loading ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : papers.length === 0 ? (
            <div className="text-sm text-ink-3 space-y-2">
              <p>No papers found{hasNarrowing ? " with these filters" : ""}.</p>
              {hasNarrowing && (
                <button onClick={clearNarrowing} className="text-xs text-accent underline">Remove filters</button>
              )}
            </div>
          ) : (
            <>
              {!hasFilters && (
                <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
                  All papers ({papers.length})
                </h2>
              )}
              <div className="grid grid-cols-2 xl:grid-cols-3 gap-4">
                {visiblePapers.map((p) => (
                  <PaperCard key={p.id} paper={p}
                    showAbstract={settings.showAbstractPreview}
                    onDeleted={handleDeleted}
                    onUpdated={handleUpdated}
                  />
                ))}
              </div>

              {totalPages > 1 && <Pager page={page} totalPages={totalPages} onPage={setPage} />}
            </>
          )}
        </div>
      </main>

      {editingPaper && (
        <EditPaperModal
          paper={editingPaper}
          onSaved={handleUpdated}
          onClose={() => setEditingPaper(null)}
        />
      )}


      {activePanel && (
        <EntityPanel
          type={activePanel}
          onClose={() => setActivePanel(null)}
          onStatsChanged={refreshStats}
          onTagClick={(name) => {
            setActivePanel(null);
            update((next) => { next.set("tag", name); });
          }}
        />
      )}

      {showResearchGaps && (
        <ResearchGapPanel
          onClose={() => setShowResearchGaps(false)}
          projectId={activeProject || undefined}
        />
      )}
    </div>
  );
}

function Pager({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  return (
    <div className="flex items-center justify-center gap-2 pt-2">
      <button
        onClick={() => onPage(Math.max(1, page - 1))}
        disabled={page === 1}
        className="px-3 py-1 text-xs rounded border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
      >
        ← Prev
      </button>
      <span className="text-xs text-gray-400">
        {page} / {totalPages}
      </span>
      <button
        onClick={() => onPage(Math.min(totalPages, page + 1))}
        disabled={page === totalPages}
        className="px-3 py-1 text-xs rounded border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-40"
      >
        Next →
      </button>
    </div>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

function Dashboard({ stats, onTopicClick, onEntityClick, onVenueClick }: {
  stats: Stats;
  onTopicClick: (name: string) => void;
  onEntityClick: (type: EntityType) => void;
  onVenueClick: (name: string) => void;
}) {
  const { counts, papers_by_year, top_topics, recent_papers, reading_status } = stats;
  const navigate = useNavigate();
  const [venues, setVenues] = useState<VenueOut[]>([]);
  useEffect(() => {
    apiFetch<VenueOut[]>("/venues?min_count=2").then(setVenues).catch(() => {});
  }, []);

  const maxYear = Math.max(...papers_by_year.map((y) => y.count), 1);

  const STATUS_COLORS: Record<string, string> = {
    unread:  "bg-gray-100 text-gray-600",
    reading: "bg-blue-100 text-blue-700",
    read:    "bg-green-100 text-green-700",
  };

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <StatCard value={counts.papers}    label="Papers"     color="violet" onClick={() => onEntityClick("papers")}   />
        <StatCard value={counts.authors}   label="Authors"    color="blue"   onClick={() => onEntityClick("authors")}  />
        <StatCard value={counts.topics}    label="Topics"     color="green"  onClick={() => onEntityClick("topics")}   />
        <StatCard value={counts.tags}      label="Tags"       color="amber"  onClick={() => onEntityClick("tags")}     />
        <StatCard value={counts.projects}  label="Projects"   color="pink"   onClick={() => onEntityClick("projects")} />
        <StatCard value={counts.bookmarked ?? 0} label="Bookmarked" color="orange" />
      </div>

      {/* Reading status breakdown */}
      {reading_status && reading_status.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Reading progress</h3>
          <div className="flex flex-wrap gap-2">
            {reading_status.map(({ status, count }) => (
              <span key={status} className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full font-medium ${STATUS_COLORS[status] ?? "bg-gray-100 text-gray-600"}`}>
                {status === "unread" ? "📚 Unread" : status === "reading" ? "📖 Reading" : "✅ Read"}
                <span className="font-bold">{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {/* Papers by year */}
        <div className="col-span-1 bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Papers by year
          </h3>
          {papers_by_year.length === 0 ? (
            <p className="text-xs text-gray-300">No data yet</p>
          ) : (
            <div className="space-y-1.5">
              {papers_by_year.slice(-12).map(({ year, count }) => (
                <div key={year} className="flex items-center gap-2">
                  <span className="text-xs text-gray-400 w-10 shrink-0">{year}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="h-2 rounded-full bg-violet-500 transition-all"
                      style={{ width: `${(count / maxYear) * 100}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-500 w-4 text-right">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Top topics */}
        <div className="col-span-1 bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Top topics
          </h3>
          {top_topics.length === 0 ? (
            <p className="text-xs text-gray-300">No topics yet</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {top_topics.map(({ name, count }) => (
                <button
                  key={name}
                  onClick={() => onTopicClick(name)}
                  className="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full hover:bg-blue-100 transition-colors"
                >
                  {name}
                  <span className="bg-blue-100 text-blue-500 rounded-full px-1.5 py-0.5 text-[10px] font-semibold">
                    {count}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Recent papers */}
        <div className="col-span-1 bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Recently added
          </h3>
          {recent_papers.length === 0 ? (
            <p className="text-xs text-gray-300">No papers yet</p>
          ) : (
            <ul className="space-y-2">
              {recent_papers.map((p) => (
                <li key={p.id}>
                  <button
                    onClick={() => navigate(`/paper/${p.id}`)}
                    className="w-full text-left group"
                  >
                    <p className="text-xs font-medium text-gray-800 group-hover:text-violet-600 line-clamp-1 leading-snug">
                      {p.title}
                    </p>
                    <p className="text-[10px] text-gray-400 mt-0.5">
                      {p.authors?.slice(0, 2).join(", ")}
                      {p.year ? ` · ${p.year}` : ""}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* Venues */}
      {venues.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Venues</h3>
          <div className="flex flex-wrap gap-1.5">
            {venues.map((v) => (
              <button
                key={v.name}
                onClick={() => onVenueClick(v.name)}
                className="inline-flex items-center gap-1 text-xs bg-indigo-50 text-indigo-700 px-2.5 py-1 rounded-full hover:bg-indigo-100 transition-colors"
              >
                {v.name}
                <span className="bg-indigo-100 text-indigo-500 rounded-full px-1.5 py-0.5 text-[10px] font-semibold">
                  {v.count}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const STAT_COLORS: Record<string, { bg: string; text: string; num: string }> = {
  violet: { bg: "bg-violet-50", text: "text-violet-500", num: "text-violet-700" },
  blue:   { bg: "bg-blue-50",   text: "text-blue-500",   num: "text-blue-700"   },
  green:  { bg: "bg-green-50",  text: "text-green-500",  num: "text-green-700"  },
  amber:  { bg: "bg-amber-50",  text: "text-amber-500",  num: "text-amber-700"  },
  pink:   { bg: "bg-pink-50",   text: "text-pink-500",   num: "text-pink-700"   },
  orange: { bg: "bg-orange-50", text: "text-orange-500", num: "text-orange-700" },
};

function StatCard({ value, label, color, onClick }: { value: number; label: string; color: string; onClick?: () => void }) {
  const c = STAT_COLORS[color];
  return (
    <button
      onClick={onClick}
      className={`${c.bg} rounded-xl p-4 flex flex-col gap-1 text-left w-full transition-all hover:shadow-md hover:scale-[1.02] active:scale-[0.98] ${onClick ? "cursor-pointer" : ""}`}
    >
      <span className={`text-2xl font-bold ${c.num}`}>{value.toLocaleString()}</span>
      <span className={`text-xs font-medium ${c.text}`}>{label}</span>
    </button>
  );
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 bg-violet-100 text-violet-700 text-xs px-2 py-0.5 rounded-full">
      {label}
      <button onClick={onRemove} className="hover:text-violet-900">×</button>
    </span>
  );
}
