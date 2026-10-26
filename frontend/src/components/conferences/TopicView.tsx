import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { conferenceTopic } from "../../api/client";
import type { ConfArea, ConfTopic, ConfTopicInst } from "../../types";
import AreaBar from "./AreaBar";
import PaperRow from "./PaperRow";

const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;

const EXAMPLES = [
  "RL for LLM reasoning",
  "diffusion models for protein structure",
  "video generation",
  "mechanistic interpretability",
  "Gaussian splatting",
  "federated learning privacy",
];

function SideList({ title, list, onInstitution, tone }: {
  title: string;
  list: ConfTopicInst[];
  onInstitution: (slug: string) => void;
  tone: "A" | "I";
}) {
  const max = list[0]?.count ?? 1;
  return (
    <div className="bg-raised border border-line rounded-xl p-4">
      <h3 className={`text-[11px] font-semibold uppercase tracking-wide mb-2 ${tone === "I" ? "text-orange-600" : "text-blue-600"}`}>{title}</h3>
      {list.length === 0 && <p className="text-xs text-ink-3">{tone === "I" ? "No company authors among these papers." : "No academic authors among these papers."}</p>}
      <div className="space-y-1">
        {list.map((x, j) => (
          <button
            key={x.slug}
            type="button"
            onClick={() => onInstitution(x.slug)}
            title={`${x.name}: ${x.count} of these papers · ${pct(x.of_own)} of its ${x.papers} papers at the conference`}
            className="w-full flex items-center gap-2 text-left text-sm hover:bg-accent-lo rounded px-1 py-0.5"
          >
            <span className="w-4 text-right text-xs text-ink-3 tabular-nums">{j + 1}</span>
            <span className="flex-1 min-w-0 truncate text-ink">{x.name}</span>
            <span className={`h-2 rounded-full ${tone === "I" ? "bg-orange-400" : "bg-blue-400"}`} style={{ width: `${Math.max(6, (70 * x.count) / max)}px` }} />
            <span className="w-6 text-right text-xs tabular-nums text-ink-2">{x.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** "Who publishes on X": the k papers closest to a topic or a pasted abstract, counted per
 *  institution, with their area mix and the closest papers themselves. */
export default function TopicView({
  confKey,
  confName,
  areas,
  areasReady,
  query,
  k,
  onSearch,
  onInstitution,
}: {
  confKey: string;
  confName: string;
  areas: ConfArea[];
  areasReady: boolean;
  query: string;
  k: number;
  onSearch: (q: string, k: number) => void;
  onInstitution: (slug: string) => void;
}) {
  const [text, setText] = useState(query);
  const [kk, setKk] = useState(k);
  const [res, setRes] = useState<ConfTopic | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setText(query), [query]);
  useEffect(() => setKk(k), [k]);

  useEffect(() => {
    if (!query.trim()) {
      setRes(null);
      return;
    }
    let live = true;
    setLoading(true);
    setError(null);
    conferenceTopic(confKey, query, k)
      .then((r) => live && setRes(r))
      .catch((e) => live && setError(e instanceof Error ? e.message : "Search failed"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [confKey, query, k]);

  const go = (t = text, n = kk) => {
    if (t.trim()) onSearch(t.trim(), n);
  };
  const shortQ = res ? (res.query.length > 70 ? res.query.slice(0, 67).trimEnd() + "…" : res.query) : "";
  const topArea = res ? [...res.areas].sort((a, b) => b.count - a.count)[0] : null;

  return (
    <div className="space-y-4">
      <div className="bg-raised border border-line rounded-xl p-4 space-y-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              go();
            }
          }}
          rows={text.length > 120 ? 5 : 2}
          placeholder="A topic (“RL for LLM reasoning”) or a whole abstract"
          className="w-full border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300 resize-y"
        />
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => go()} disabled={loading || !text.trim()} className="px-4 py-1.5 text-sm bg-accent text-white rounded-lg hover:bg-violet-700 disabled:opacity-50">
            {loading ? "Searching…" : "Search"}
          </button>
          <label className="text-xs text-ink-2 flex items-center gap-1.5">
            closest
            <select
              value={kk}
              onChange={(e) => {
                const n = Number(e.target.value);
                setKk(n);
                if (query) go(query, n);
              }}
              className="border border-line rounded px-1.5 py-1 text-xs bg-raised"
            >
              {[50, 100, 200, 500].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
            papers
          </label>
          <span className="text-xs text-ink-3 ml-1">Try:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex} type="button" onClick={() => { setText(ex); go(ex); }} className="text-xs px-2 py-0.5 rounded-full border border-line text-ink-2 hover:border-accent-border hover:text-accent">
              {ex}
            </button>
          ))}
        </div>
        {!areasReady && (
          <p className="text-xs text-amber">Semantic search becomes available when indexing finishes; until then results use keyword matching.</p>
        )}
        {error && <p className="text-xs text-coral">{error}</p>}
      </div>

      {res && (
        <>
          <div className="bg-raised border border-line rounded-xl p-5 space-y-3">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <div className="text-xl font-semibold text-ink">
                Who publishes on <span className="text-accent">“{shortQ}”</span>
              </div>
              <Link
                to={res.query.length <= 300 ? `/conferences?kind=topic&q=${encodeURIComponent(res.query)}` : "/conferences?kind=topic"}
                state={{ q: res.query }}
                className="text-xs text-accent hover:underline"
              >
                Search all conferences →
              </Link>
            </div>
            <div className="text-xs text-ink-2">
              The {res.k} closest of {res.total.toLocaleString()} papers at {confName} · {pct(res.with_industry / Math.max(1, res.k))} have a company author
              {topArea && topArea.count > 0 ? ` · most common area: ${topArea.name}` : ""}
              {res.mode === "keyword" ? " · keyword matching" : ""}
            </div>
            <AreaBar areas={res.areas} caption={`Research areas of these ${res.k} papers`} />
          </div>
          <div className="grid md:grid-cols-2 gap-4">
            <SideList title="Universities & institutes" list={res.academia} onInstitution={onInstitution} tone="A" />
            <SideList title="Companies" list={res.industry} onInstitution={onInstitution} tone="I" />
          </div>
          <div className="bg-raised border border-line rounded-xl px-5 py-3">
            <h3 className="text-sm font-semibold text-ink">Closest papers</h3>
            <p className="text-xs text-ink-3">Click a title for the abstract, authors and its neighbours; ↗ opens it at the conference.</p>
            {res.papers.map((p) => (
              <PaperRow key={p.id} confKey={confKey} paper={p} areas={areas} onInstitution={onInstitution} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
