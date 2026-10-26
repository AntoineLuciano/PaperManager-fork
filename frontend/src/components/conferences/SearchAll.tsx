import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { searchConferences, searchConferencesTopic } from "../../api/client";
import type { ConfAuthor, ConfEdition, ConfSearch, ConfSearchPaper, ConfSearchTopic, ConfSearchTopicInst } from "../../types";
import AreaBar from "./AreaBar";
import Highlight, { type HighlightTerms } from "./Highlight";
import PaperRow from "./PaperRow";

type Kind = "paper" | "author" | "topic";
type AreaDef = { name: string; short: string; color: string };

const EXAMPLES: Record<Kind, string[]> = {
  paper: ["flow matching for generative modeling", "Gaussian splatting", "speculative decoding", "SE(3) diffusion"],
  author: ["Charlotte Deane", "Yoshua Bengio", "Kaiming He", "Sergey Levine"],
  topic: ["diffusion models for protein structure", "RL for LLM reasoning", "video generation", "mechanistic interpretability"],
};
const FIELD_LABEL: Record<string, string> = { AI: "General AI" };
const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;
const URL_MAX = 300;

/** Where to open an institution: its page at the given conference. */
const instPath = (key: string, slug: string) => `/conferences/${key}?view=institutions&inst=${encodeURIComponent(slug)}`;

const ordinal = (n: number) => {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`;
};

/** "5th of 9 authors · University of Oxford" */
function authorNote(p: ConfSearchPaper): string {
  const n = p.authors;
  const pos = p.author_position ?? 0;
  const role = n <= 1 ? "Sole author" : pos === 1 ? `First of ${n} authors` : pos === n ? `Last of ${n} authors` : `${ordinal(pos)} of ${n} authors`;
  const inst = p.author_institutions && p.author_institutions.length ? p.author_institutions.join("; ") : "no institution listed";
  return `${role} · ${inst}`;
}

function Rows({ papers, areas, title, hint, highlight, children }: {
  papers: ConfSearchPaper[];
  areas: AreaDef[];
  title: string;
  hint?: string;
  highlight?: HighlightTerms | null;
  children?: ReactNode;
}) {
  const navigate = useNavigate();
  return (
    <div className="bg-raised border border-line rounded-xl px-4 sm:px-5 py-3">
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {hint && <p className="text-xs text-ink-3">{hint}</p>}
      {papers.map((p) => (
        <PaperRow
          key={`${p.conf_key}/${p.id}`}
          confKey={p.conf_key}
          paper={p}
          areas={areas}
          highlight={highlight}
          conference={{ key: p.conf_key, name: p.conf_name }}
          onInstitution={(slug) => navigate(instPath(p.conf_key, slug))}
        />
      ))}
      {children}
    </div>
  );
}

function AuthorCard({ a, areas, initiallyOpen, highlight }: {
  a: ConfAuthor;
  areas: AreaDef[];
  initiallyOpen: boolean;
  highlight?: HighlightTerms | null;
}) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <div className="bg-raised border border-line rounded-xl p-4">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <h3 className="text-[16px] font-semibold text-ink">
          <button
            type="button"
            data-result=""
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="text-left hover:text-accent rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300"
          >
            <Highlight text={a.name} terms={highlight} />
          </button>
        </h3>
        <span className="text-xs text-ink-3">
          {a.papers} paper{a.papers === 1 ? "" : "s"} at {a.conference_count} conference{a.conference_count === 1 ? "" : "s"} · {a.coauthors} co-author{a.coauthors === 1 ? "" : "s"}
        </span>
        <button type="button" onClick={() => setOpen(!open)} className="ml-auto text-xs text-accent hover:underline">
          {open ? "Hide papers" : "Show papers"}
        </button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
        {a.institutions.length === 0 && <span className="text-ink-3">No institution listed on these papers.</span>}
        {a.institutions.map((i) => (
          <span key={i.name} className={`px-1.5 py-px rounded-full border ${i.sector === "I" ? "border-orange-200 text-orange-700" : "border-blue-200 text-blue-700"}`}>
            {i.name} <span className="text-ink-3">{i.papers}</span>
          </span>
        ))}
      </div>
      {a.identities.length > 1 && (
        <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs">
          <p className="font-medium text-amber-800">
            These papers fall into {a.identities.length} groups that share no institution and no co-author, so the name may belong to
            {" "}{a.identities.length} people:
          </p>
          <ul className="mt-1 space-y-0.5 text-amber">
            {a.identities.map((g, n) => (
              <li key={n}>
                {g.institutions.length ? g.institutions.join(", ") : "no institution listed"} · {g.papers} paper{g.papers === 1 ? "" : "s"} ({g.conferences.join(", ")})
              </li>
            ))}
          </ul>
        </div>
      )}
      {open && a.conferences.map((c) => (
        <div key={c.key} className="mt-3">
          <Link to={`/conferences/${c.key}`} className="text-[11px] font-semibold text-ink-3 uppercase tracking-wide hover:text-accent">
            {c.name} · {c.papers_by_author.length}
          </Link>
          {c.papers_by_author.map((p) => (
            <PaperRow
              key={p.id}
              confKey={c.key}
              paper={p}
              areas={areas}
              onInstitution={(slug) => navigate(instPath(c.key, slug))}
              note={authorNote(p)}
            />
          ))}
        </div>
      ))}
      {open && a.more_papers > 0 && <p className="mt-2 text-xs text-ink-3">+{a.more_papers} more papers not listed.</p>}
    </div>
  );
}

function PooledList({ title, list, tone, names }: {
  title: string;
  list: ConfSearchTopicInst[];
  tone: "A" | "I";
  names: Record<string, string>;
}) {
  const navigate = useNavigate();
  const max = list[0]?.count ?? 1;
  return (
    <div className="bg-raised border border-line rounded-xl p-4 min-w-0">
      <h3 className={`text-[11px] font-semibold uppercase tracking-wide mb-2 ${tone === "I" ? "text-orange-600" : "text-blue-600"}`}>{title}</h3>
      {list.length === 0 && <p className="text-xs text-ink-3">{tone === "I" ? "No company authors among these papers." : "No academic authors among these papers."}</p>}
      <div className="space-y-1">
        {list.map((x, j) => {
          const by = x.conferences.map((c) => `${names[c.key] ?? c.key} ${c.count}`).join(" · ");
          return (
            <button
              key={x.name}
              type="button"
              onClick={() => x.conferences[0] && navigate(instPath(x.conferences[0].key, x.conferences[0].slug))}
              title={`${x.name}: ${x.count} of these papers (${by}) · ${pct(x.of_own, 1)} of its ${x.papers} papers at these conferences`}
              className="w-full flex items-center gap-2 text-left text-sm hover:bg-accent-lo rounded px-1 py-0.5"
            >
              <span className="w-4 text-right text-xs text-ink-3 tabular-nums">{j + 1}</span>
              <span className="flex-1 min-w-0">
                <span className="block truncate text-ink">{x.name}</span>
                <span className="block truncate text-[10px] text-ink-3">{by}</span>
              </span>
              <span className={`h-2 shrink-0 rounded-full ${tone === "I" ? "bg-orange-400" : "bg-blue-400"}`} style={{ width: `${Math.max(6, (60 * x.count) / max)}px` }} />
              <span className="w-6 text-right text-xs tabular-nums text-ink-2">{x.count}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function TopicResult({ t, areas }: { t: ConfSearchTopic; areas: AreaDef[] }) {
  const names = useMemo(() => Object.fromEntries(t.conferences.map((c) => [c.key, c.name])), [t]);
  const maxRate = Math.max(...t.conferences.map((c) => c.per_1k), 0.001);
  const shortQ = t.query.length > 70 ? t.query.slice(0, 67).trimEnd() + "…" : t.query;
  const qParam = t.query.length <= URL_MAX ? `&q=${encodeURIComponent(t.query)}` : "";
  return (
    <>
      <div className="bg-raised border border-line rounded-xl p-4 sm:p-5 space-y-4">
        <div>
          <div className="text-xl font-semibold text-ink break-words">
            Where <span className="text-accent">“{shortQ}”</span> is published
          </div>
          <div className="text-xs text-ink-2">
            The {t.k} closest of {t.total.toLocaleString()} papers at {t.conferences.length} conferences
            {t.threshold != null && <> (title similarity ≥ {t.threshold.toFixed(2)})</>} · {pct(t.with_industry / Math.max(1, t.k))} have a company author
          </div>
        </div>
        <div>
          <div className="text-[11px] font-medium text-ink-3 uppercase tracking-wide mb-1.5">Per conference: papers · per 1,000 of its papers</div>
          <div className="space-y-1">
            {t.conferences.map((c) => (
              <Link
                key={c.key}
                data-result=""
                to={`/conferences/${c.key}?view=topics${qParam}`}
                title={`${c.count} of ${c.papers.toLocaleString()} papers · closest: ${c.top[0]?.title ?? "–"}`}
                className="flex items-center gap-2 text-sm hover:bg-accent-lo rounded px-1 py-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300"
              >
                <span className="w-24 sm:w-28 shrink-0 truncate text-ink">{c.name}</span>
                <span className="flex-1 min-w-0 h-2.5 rounded-full bg-line-s overflow-hidden">
                  <span className="block h-full rounded-full bg-accent" style={{ width: `${(100 * c.per_1k) / maxRate}%` }} />
                </span>
                <span className="w-20 sm:w-28 shrink-0 text-right text-xs tabular-nums text-ink-2">
                  {c.count} · {c.per_1k.toFixed(1)}<span className="hidden sm:inline"> per 1,000</span>
                </span>
              </Link>
            ))}
          </div>
        </div>
        {t.trend.length > 0 && (
          <div>
            <div className="text-[11px] font-medium text-ink-3 uppercase tracking-wide mb-1.5">Over the years (per 1,000 papers)</div>
            <div className="space-y-1">
              {t.trend.map((s) => {
                const first = s.points[0];
                const last = s.points[s.points.length - 1];
                const change = first.per_1k > 0 ? last.per_1k / first.per_1k - 1 : null;
                return (
                  <div key={s.slug} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
                    <span className="w-20 font-semibold text-ink">{s.series}</span>
                    {s.points.map((p) => (
                      <span key={p.key} className="inline-flex items-center gap-1" title={`${p.count} of ${p.papers.toLocaleString()} papers`}>
                        <span className="text-ink-3">{p.year}</span>
                        <span className="inline-block h-2 rounded-full bg-violet-300" style={{ width: `${Math.max(3, (60 * p.per_1k) / maxRate)}px` }} />
                        <span className="tabular-nums">{p.per_1k.toFixed(1)}</span>
                      </span>
                    ))}
                    {change != null && (
                      <span className={`font-semibold ${change >= 0 ? "text-green-600" : "text-coral"}`}>
                        {change >= 0 ? "+" : ""}{pct(change)}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
        <AreaBar areas={t.areas} caption={`Research areas of these ${t.k} papers`} />
        {t.skipped.length > 0 && (
          <p className="text-xs text-amber">
            Not counted: {t.skipped.map((s) => `${s.name} (${s.reason})`).join(", ")}.
          </p>
        )}
        {t.with_institution < t.k * 0.9 && (
          <p className="text-xs text-ink-3">
            Institutions are known for {t.with_institution} of these {t.k} papers; some sources list none.
          </p>
        )}
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        <PooledList title="Universities & institutes, all conferences" list={t.academia} tone="A" names={names} />
        <PooledList title="Companies, all conferences" list={t.industry} tone="I" names={names} />
      </div>
      <Rows papers={t.papers} areas={areas} title="Closest papers" hint="Over all conferences; click a title for the abstract and authors." />
    </>
  );
}

function DidYouMean({ text, onPick }: { text: string; onPick: (t: string) => void }) {
  return (
    <p className="text-sm text-ink-2">
      Did you mean{" "}
      <button type="button" onClick={() => onPick(text)} className="font-medium text-accent hover:underline">
        {text}
      </button>
      ? Results include it already.
    </p>
  );
}

/** One search box over every loaded conference: papers (title words, then meaning),
 *  authors (name) and topics (where a topic is published, per conference and year).
 *  The query, tab and filters live in the URL: /conferences?q=...&kind=author.
 *  Keys: Enter searches at once, Esc clears, ↑ / ↓ move through the results. */
export default function SearchAll({ areas, editions }: { areas: AreaDef[]; editions: ConfEdition[] }) {
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const urlQ = params.get("q") ?? "";
  const stateQ = (location.state as { q?: string } | null)?.q ?? "";
  const urlKind = params.get("kind") as Kind | null;
  const k = Number(params.get("k") ?? 300) || 300;
  const series = params.get("series") ?? "";
  const field = params.get("field") ?? "";
  const yearMin = Number(params.get("from")) || null;
  const yearMax = Number(params.get("to")) || null;
  const filters = useMemo(() => ({ series, field, year_min: yearMin, year_max: yearMax }), [series, field, yearMin, yearMax]);

  const rootRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState(urlQ || stateQ);
  const [query, setQuery] = useState((urlQ || stateQ).trim());
  const [res, setRes] = useState<ConfSearch | null>(null);
  const [topic, setTopic] = useState<ConfSearchTopic | null>(null);
  const [loading, setLoading] = useState(false);
  const [topicLoading, setTopicLoading] = useState(false);
  const [slow, setSlow] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const update = (patch: Record<string, string | null>, replace = false) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [key, v] of Object.entries(patch)) {
        if (v == null || v === "") next.delete(key);
        else next.set(key, v);
      }
      return next;
    }, { replace });
  };

  // Back / forward or a link changed the URL's query.
  useEffect(() => {
    if (urlQ && urlQ !== query) {
      setText(urlQ);
      setQuery(urlQ);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQ]);

  const commit = (v: string) => {
    const t = v.trim();
    if (t === query) return;
    setQuery(t);
    update({ q: t && t.length <= URL_MAX ? t : null }, true);
  };

  const pick = (t: string, kind?: Kind) => {
    setText(t);
    setQuery(t);
    update({ q: t.length <= URL_MAX ? t : null, ...(kind ? { kind } : {}) });
  };

  // Search while typing, 300 ms after the last key.
  useEffect(() => {
    const id = setTimeout(() => commit(text), 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  useEffect(() => {
    if (!query) {
      setRes(null);
      return;
    }
    let live = true;
    setLoading(true);
    searchConferences(query, { kind: "all", ...filters })
      .then((r) => {
        if (!live) return;
        setRes(r);
        setError(null);
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Search failed"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [query, filters]);

  // The tab: the one the user picked (kept in the URL, never overridden), else the
  // backend's suggestion for this query.
  const longText = query.split(/\s+/).length > 12;
  const active: Kind = urlKind ?? (longText ? "topic" : res?.suggested ?? "paper");

  useEffect(() => {
    if (!query || active !== "topic") {
      setTopic(null);
      return;
    }
    let live = true;
    setTopicLoading(true);
    searchConferencesTopic(query, { k, ...filters })
      .then((r) => {
        if (!live) return;
        setTopic(r);
        setError(null);
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Topic search failed"))
      .finally(() => live && setTopicLoading(false));
    return () => {
      live = false;
    };
  }, [query, active, k, filters]);

  // Show "searching" and dim old results only when a request takes long enough to notice.
  const busy = loading || topicLoading;
  useEffect(() => {
    if (!busy) {
      setSlow(false);
      return;
    }
    const id = setTimeout(() => setSlow(true), 200);
    return () => clearTimeout(id);
  }, [busy]);
  const stale = slow || text.trim() !== query;

  const clear = () => {
    setText("");
    setQuery("");
    setRes(null);
    setTopic(null);
    setError(null);
    update({ q: null, kind: null });
    boxRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      if (document.activeElement !== boxRef.current) boxRef.current?.focus();
      else clear();
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const inBox = e.target === boxRef.current;
    if (inBox && text.includes("\n")) return;         // a pasted abstract: the caret moves
    const items = Array.from(rootRef.current?.querySelectorAll<HTMLElement>("[data-result]") ?? []);
    if (!items.length) return;
    const i = items.indexOf(document.activeElement as HTMLElement);
    e.preventDefault();
    if (e.key === "ArrowDown") items[Math.min(i + 1, items.length - 1)].focus();
    else if (i <= 0) boxRef.current?.focus();
    else items[i - 1].focus();
  };

  const seriesOptions = useMemo(() => {
    const m = new Map<string, string>();
    for (const e of editions) m.set(e.slug, e.series);
    return [...m.entries()];
  }, [editions]);
  const fieldOptions = useMemo(() => [...new Set(editions.map((e) => e.field))], [editions]);
  const years = useMemo(() => [...new Set(editions.map((e) => e.year))].sort(), [editions]);

  const tabs: { kind: Kind; label: string; count?: number }[] = [
    { kind: "paper", label: "Papers", count: res?.papers ? res.papers.title_total : undefined },
    { kind: "author", label: "Authors", count: res?.authors?.total },
    { kind: "topic", label: "Topics" },
  ];
  const select = "border border-line rounded px-1.5 py-1 text-xs bg-raised text-ink-2 focus:outline-none focus:ring-2 focus:ring-violet-300";

  const examples = (kind: Kind, lead: string) => (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-ink-3">{lead}</span>
      {EXAMPLES[kind].map((ex) => (
        <button key={ex} type="button" onClick={() => pick(ex, kind)} className="text-xs px-2 py-0.5 rounded-full border border-line text-ink-2 hover:border-accent-border hover:text-accent">
          {ex}
        </button>
      ))}
    </div>
  );
  const nothing = (what: string, kind: Kind) => (
    <div className="bg-raised border border-line rounded-xl p-4 space-y-2">
      <p className="text-sm text-ink-2">{what}</p>
      {examples(kind, "Try:")}
    </div>
  );

  const papers = res?.papers;
  const authors = res?.authors;

  return (
    <div ref={rootRef} onKeyDown={onKeyDown} className="space-y-4">
      <section className="bg-raised border border-line rounded-xl p-4 space-y-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[10px] font-semibold text-accent uppercase tracking-wide">Search all loaded conferences</h2>
          <span className={`text-[11px] text-ink-3 ${slow ? "animate-pulse" : ""}`}>
            {slow ? "searching…" : res ? `${res.conferences.length} searched` : ""}
          </span>
        </div>
        <div className="relative">
          <textarea
            ref={boxRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                commit(text);
              }
            }}
            rows={text.length > 120 ? 4 : 1}
            aria-label="Search all conferences"
            placeholder="A paper title, an author or a topic, or paste an abstract"
            className="block w-full min-h-[42px] max-h-48 [field-sizing:content] border border-line rounded-lg pl-3 pr-9 py-2 text-[15px] leading-6 text-ink bg-raised placeholder:text-ink-3 focus:outline-none focus:ring-2 focus:ring-violet-300 resize-none"
          />
          {text && (
            <button
              type="button"
              onClick={clear}
              aria-label="Clear search"
              title="Clear (Esc)"
              className="absolute right-2 top-2 h-6 w-6 rounded text-ink-3 hover:text-ink hover:bg-line-s"
            >
              ×
            </button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1 bg-line-s border border-line rounded-xl p-1" role="tablist">
            {tabs.map((t) => (
              <button
                key={t.kind}
                type="button"
                role="tab"
                aria-selected={active === t.kind}
                onClick={() => update({ kind: t.kind })}
                className={`px-3 py-1 text-sm font-medium rounded-lg ${active === t.kind ? "bg-raised text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}
              >
                {t.label}
                {t.count != null && <span className="ml-1.5 text-xs text-ink-3 tabular-nums">{t.count.toLocaleString()}</span>}
              </button>
            ))}
          </div>
          <select aria-label="Field" value={field} onChange={(e) => update({ field: e.target.value || null })} className={select}>
            <option value="">All fields</option>
            {fieldOptions.map((f) => <option key={f} value={f}>{FIELD_LABEL[f] ?? f}</option>)}
          </select>
          <select aria-label="Series" value={series} onChange={(e) => update({ series: e.target.value || null })} className={select}>
            <option value="">All series</option>
            {seriesOptions.map(([slug, name]) => <option key={slug} value={slug}>{name}</option>)}
          </select>
          {years.length > 1 && (
            <>
              <select aria-label="From year" value={yearMin ?? ""} onChange={(e) => update({ from: e.target.value || null })} className={select}>
                <option value="">from</option>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
              <select aria-label="To year" value={yearMax ?? ""} onChange={(e) => update({ to: e.target.value || null })} className={select}>
                <option value="">to</option>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </>
          )}
          {active === "topic" && (
            <label className="text-xs text-ink-2 flex items-center gap-1.5">
              closest
              <select aria-label="Closest papers" value={k} onChange={(e) => update({ k: e.target.value === "300" ? null : e.target.value })} className={select}>
                {[100, 300, 1000].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              papers
            </label>
          )}
        </div>
        {!query && examples(active, active === "author" ? "Find an author:" : active === "topic" ? "Where is it published:" : "Find a paper:")}
        {!query && (
          <p className="text-[11px] text-ink-3">Enter searches at once · Esc clears · ↑ ↓ move through the results</p>
        )}
        {error && <p className="text-xs text-coral">{error}</p>}
      </section>

      <div className={`space-y-4 transition-opacity duration-150 ${stale ? "opacity-50" : ""}`} aria-busy={busy}>
        {query && papers && active === "paper" && (
          <>
            {papers.corrected && <DidYouMean text={papers.corrected} onPick={(t) => pick(t)} />}
            {papers.title.length > 0 && (
              <Rows
                papers={papers.title}
                areas={areas}
                highlight={papers.highlight}
                title={`Title matches · ${papers.title_total.toLocaleString()}`}
                hint={papers.title_total > papers.title.length ? `The best ${papers.title.length}: whole title, start, phrase, then all words, ties by meaning.` : undefined}
              />
            )}
            {papers.semantic.length > 0 && (
              <Rows
                papers={papers.semantic}
                areas={areas}
                highlight={papers.highlight}
                title="Closest by meaning"
                hint="Titles closest to the query in bge-small embedding space, not matched by words above."
              />
            )}
            {papers.title.length === 0 && papers.semantic.length === 0 && nothing(`No papers found for “${query}”.`, "paper")}
          </>
        )}

        {query && authors && active === "author" && (
          <div className="space-y-3">
            {authors.corrected && <DidYouMean text={authors.corrected} onPick={(t) => pick(t)} />}
            {authors.authors.length === 0 && nothing(`No author named “${query}” at the loaded conferences.`, "author")}
            {authors.total > authors.authors.length && (
              <p className="text-xs text-ink-3">The best {authors.authors.length} of {authors.total} matching names.</p>
            )}
            {authors.authors.map((a, n) => (
              <AuthorCard key={a.folded} a={a} areas={areas} highlight={authors.highlight} initiallyOpen={n === 0 || authors.authors.length <= 2} />
            ))}
            {authors.authors.length > 0 && (
              <p className="text-[11px] text-ink-3">
                Names are matched with accents and case folded, so one name can be several people; each paper shows the institution the author gave on it.
              </p>
            )}
          </div>
        )}

        {query && active === "topic" && (
          topic ? (
            <>
              {topic.corrected && <p className="text-sm text-ink-2">Searched for “{topic.corrected}”.</p>}
              <TopicResult t={topic} areas={areas} />
            </>
          ) : topicLoading ? <p className="text-xs text-ink-3 animate-pulse">Searching all conferences…</p> : null
        )}
      </div>
    </div>
  );
}
