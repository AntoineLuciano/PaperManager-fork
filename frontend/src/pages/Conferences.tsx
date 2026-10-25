import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { buildConference, getConference, getConferenceStatus, listConferences } from "../api/client";
import type { ConfCatalog, ConfEdition, ConfOverview, ConfStatus } from "../types";
import AreaBar from "../components/conferences/AreaBar";
import InstitutionsView from "../components/conferences/InstitutionsView";
import TopicView from "../components/conferences/TopicView";

const FIELDS = ["ML", "Vision", "NLP", "AI", "Robotics", "Data"];
const BUILDING = new Set(["queued", "fetching", "normalising", "embedding"]);
const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;

function stateLabel(e: ConfEdition | ConfStatus): string {
  switch (e.state) {
    case "queued": return "queued";
    case "fetching": return "downloading";
    case "normalising": return "reading";
    case "embedding": return `indexing ${Math.round((e.progress ?? 0) * 100)}%`;
    case "unavailable": return "not published";
    case "error": return "failed";
    default: return "";
  }
}

// ── Landing: every conference-year ────────────────────────────────────────────

function Landing() {
  const navigate = useNavigate();
  const [cat, setCat] = useState<ConfCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listConferences().then(setCat).catch((e) => setError(e instanceof Error ? e.message : "Failed"));
  }, []);
  useEffect(load, [load]);
  const building = cat?.conferences.some((c) => BUILDING.has(c.state)) ?? false;
  useEffect(() => {
    if (!building) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [building, load]);

  const open = async (e: ConfEdition) => {
    if (e.state === "unavailable") return;
    if (e.state === "none" || e.state === "error") {
      try {
        await buildConference(e.key);
      } catch {
        /* the conference page shows the state */
      }
    }
    navigate(`/conferences/${e.key}`);
  };

  const series = useMemo(() => {
    const m = new Map<string, ConfEdition[]>();
    for (const c of cat?.conferences ?? []) {
      if (!m.has(c.slug)) m.set(c.slug, []);
      m.get(c.slug)!.push(c);
    }
    return m;
  }, [cat]);

  return (
    <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
      <div>
        <div className="text-[10px] font-semibold text-accent uppercase tracking-wide">Conference explorer</div>
        <h1 className="text-2xl font-semibold text-ink">Who publishes what, where</h1>
        <p className="mt-1 text-sm text-ink-2 max-w-3xl">
          Browse the accepted papers of the major ML, vision, NLP and robotics conferences by institution (rank, paper count,
          research-area mix, collaborators) or by topic (which universities and companies publish most on it, and the closest papers).
          Pick a conference; ones not loaded yet are downloaded and indexed on this server, which takes a few minutes.
        </p>
      </div>
      {error && <p className="text-sm text-coral">{error}</p>}
      {!cat && !error && <p className="text-sm text-ink-3">Loading…</p>}
      {cat && FIELDS.map((field) => {
        const rows = [...series.entries()].filter(([, eds]) => eds[0]?.field === field);
        if (!rows.length) return null;
        return (
          <section key={field} className="bg-raised border border-line rounded-xl p-4">
            <h2 className="text-[11px] font-semibold text-ink-3 uppercase tracking-wide mb-2">{field === "AI" ? "General AI" : field}</h2>
            <div className="divide-y divide-line-s">
              {rows.map(([slug, eds]) => (
                <div key={slug} className="flex flex-wrap items-center gap-2 py-2">
                  <div className="w-24 text-sm font-semibold text-ink">{eds[0].series}</div>
                  {eds.map((e) => {
                    const ready = e.state === "ready" || e.state === "partial";
                    const busy = BUILDING.has(e.state);
                    const cls = ready
                      ? "bg-accent text-white border-accent hover:bg-violet-700"
                      : busy
                        ? "bg-accent-lo text-accent border-accent-border"
                        : e.state === "unavailable"
                          ? "bg-raised text-ink-3 border-line-s line-through cursor-default"
                          : e.state === "error"
                            ? "bg-raised text-coral border-red-200 hover:border-red-300"
                            : "bg-raised text-ink-2 border-line hover:border-accent-border hover:text-accent";
                    const title = ready
                      ? `${e.name}: ${e.papers?.toLocaleString()} papers, ${e.institutions?.toLocaleString()} institutions`
                      : e.message || (e.state === "none" ? `Load ${e.name}` : e.name);
                    return (
                      <button key={e.key} type="button" title={title} onClick={() => open(e)} className={`px-2.5 py-1 text-xs rounded-lg border ${cls}`}>
                        {e.year}
                        {ready && e.papers ? <span className="ml-1.5 opacity-75">{e.papers.toLocaleString()}</span> : null}
                        {busy && <span className="ml-1.5">{stateLabel(e)}</span>}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </section>
        );
      })}
      <p className="text-xs text-ink-3">
        Sources: the official conference sites (NeurIPS, ICML, ICLR, CVPR, ICCV, ECCV publish every accepted paper with its authors'
        institutions) and <a className="underline hover:text-accent" href="https://github.com/papercopilot/paperlists" target="_blank" rel="noopener noreferrer">Paper Copilot's paper lists</a>{" "}
        for the rest. Research areas and topic search use bge-small embeddings computed here; nothing leaves the server.
      </p>
    </div>
  );
}

// ── One conference ────────────────────────────────────────────────────────────

function Overview({ ov, onView, onInstitution }: {
  ov: ConfOverview;
  onView: (v: "institutions" | "topics", area?: number) => void;
  onInstitution: (slug: string) => void;
}) {
  const list = (title: string, rows: ConfOverview["top_academia"], tone: "A" | "I") => {
    const max = rows[0]?.papers ?? 1;
    return (
      <div className="bg-raised border border-line rounded-xl p-4">
        <h3 className={`text-[11px] font-semibold uppercase tracking-wide mb-2 ${tone === "I" ? "text-orange-600" : "text-blue-600"}`}>{title}</h3>
        <div className="space-y-1">
          {rows.map((x) => (
            <button key={x.slug} type="button" onClick={() => onInstitution(x.slug)} className="w-full flex items-center gap-2 text-left text-sm hover:bg-accent-lo rounded px-1 py-0.5">
              <span className="w-6 text-right text-xs text-ink-3 tabular-nums">#{x.rank}</span>
              <span className="flex-1 min-w-0 truncate text-ink">{x.name}</span>
              <span className={`h-2 rounded-full ${tone === "I" ? "bg-orange-400" : "bg-blue-400"}`} style={{ width: `${Math.max(6, (90 * x.papers) / max)}px` }} />
              <span className="w-8 text-right text-xs tabular-nums text-ink-2">{x.papers}</span>
            </button>
          ))}
        </div>
      </div>
    );
  };
  return (
    <div className="space-y-4">
      <div className="grid md:grid-cols-2 gap-4">
        <button type="button" onClick={() => onView("institutions")} className="text-left bg-raised border border-line rounded-xl p-5 hover:border-accent-border">
          <div className="text-[10px] font-semibold text-accent uppercase tracking-wide">Institutions</div>
          <div className="mt-1 text-base font-semibold text-ink">Find a university, lab or company</div>
          <p className="mt-1 text-xs text-ink-2">Rank, paper count (full and fractional), research-area mix against the conference, collaborators and every paper.</p>
        </button>
        <button type="button" onClick={() => onView("topics")} className="text-left bg-raised border border-line rounded-xl p-5 hover:border-accent-border">
          <div className="text-[10px] font-semibold text-accent uppercase tracking-wide">Topics & papers</div>
          <div className="mt-1 text-base font-semibold text-ink">Who publishes on your topic?</div>
          <p className="mt-1 text-xs text-ink-2">Type a topic or paste an abstract: the closest papers, and which universities and companies wrote them.</p>
        </button>
      </div>
      <div className="bg-raised border border-line rounded-xl p-5">
        <AreaBar
          areas={ov.areas}
          caption={`Research areas of all ${ov.papers.toLocaleString()} papers (click one for its ranking)`}
          legend={24}
          height="h-5"
          onPick={(a) => onView("institutions", a.index)}
        />
      </div>
      <div className="grid md:grid-cols-2 gap-4">
        {list("Top universities & institutes", ov.top_academia, "A")}
        {list("Top companies", ov.top_industry, "I")}
      </div>
    </div>
  );
}

function Edition({ confKey }: { confKey: string }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const view = (params.get("view") as "overview" | "institutions" | "topics") || "overview";
  const inst = params.get("inst");
  const q = params.get("q") ?? "";
  const k = Number(params.get("k") ?? 100) || 100;
  const [ov, setOv] = useState<ConfOverview | null>(null);
  const [status, setStatus] = useState<ConfStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cat, setCat] = useState<ConfCatalog | null>(null);
  // A pasted abstract is too long for the URL: the URL keeps short queries only.
  const [topicQ, setTopicQ] = useState(q);
  useEffect(() => {
    if (q) setTopicQ(q);
  }, [q]);
  const area = params.get("area");

  const load = useCallback(async () => {
    try {
      const o = await getConference(confKey);
      setOv(o);
      setStatus(o.status);
      setError(null);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed";
      if (msg.includes("API 409") || msg.includes("API 404")) {
        setOv(null);
        try {
          setStatus(await getConferenceStatus(confKey));
        } catch {
          setError(msg.includes("404") ? "Unknown conference." : msg);
        }
      } else setError(msg);
    }
  }, [confKey]);

  useEffect(() => {
    setOv(null);
    setStatus(null);
    load();
    listConferences().then(setCat).catch(() => {});
  }, [load]);

  // Poll while the conference is being built; reload the overview when a phase finishes.
  const busy = status ? BUILDING.has(status.state) : false;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(async () => {
      try {
        const st = await getConferenceStatus(confKey);
        setStatus(st);
        if (!BUILDING.has(st.state) || (!ov && st.state === "embedding")) load();
      } catch {
        /* keep polling */
      }
    }, 2500);
    return () => clearInterval(t);
  }, [busy, confKey, load, ov]);

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, v] of Object.entries(patch)) {
      if (v == null || v === "") next.delete(key);
      else next.set(key, v);
    }
    setParams(next);
  };
  const onInstitution = (slug: string | null) => set({ view: "institutions", inst: slug, area: null });

  const readyEditions = (cat?.conferences ?? []).filter((c) => c.state === "ready" || c.state === "partial");
  const name = ov?.name ?? status?.name ?? confKey;

  const tab = (v: typeof view, label: string) => (
    <button
      type="button"
      onClick={() => set({ view: v === "overview" ? null : v, inst: v === "institutions" ? inst : null })}
      className={`px-3.5 py-1.5 text-sm font-medium rounded-lg ${view === v ? "bg-raised text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}
    >
      {label}
    </button>
  );

  return (
    <div className="max-w-5xl mx-auto px-6 py-6 space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-0">
          <Link to="/conferences" className="text-[10px] font-semibold text-accent uppercase tracking-wide hover:underline">← All conferences</Link>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold text-ink">{name}</h1>
            {readyEditions.length > 1 && (
              <select
                value={confKey}
                onChange={(e) => navigate(`/conferences/${e.target.value}${view !== "overview" ? `?view=${view}${view === "topics" && q ? `&q=${encodeURIComponent(q)}` : ""}` : ""}`)}
                className="border border-line rounded-lg px-2 py-1 text-xs text-ink-2 bg-raised"
                title="Switch conference"
              >
                {!readyEditions.some((c) => c.key === confKey) && <option value={confKey}>{name}</option>}
                {readyEditions.map((c) => <option key={c.key} value={c.key}>{c.name}</option>)}
              </select>
            )}
          </div>
          {ov && (
            <div className="mt-0.5 text-xs text-ink-2">
              {ov.papers.toLocaleString()} accepted papers · {ov.institutions.toLocaleString()} institutions ·{" "}
              {pct(ov.with_industry / Math.max(1, ov.papers))} with a company author
              {!ov.partial && ov.with_institution < ov.papers * 0.5 && " · the source lists few affiliations, so institution views are thin"}
            </div>
          )}
        </div>
        {ov && (
          <div className="flex gap-1 bg-line-s border border-line rounded-xl p-1">
            {tab("overview", "Overview")}
            {tab("institutions", "Institutions")}
            {tab("topics", "Topics & papers")}
          </div>
        )}
      </div>

      {error && <p className="text-sm text-coral">{error}</p>}

      {status && (BUILDING.has(status.state) || !ov) && (
        <div className="bg-raised border border-line rounded-xl p-4 space-y-2">
          <div className="text-sm text-ink">
            {status.state === "none" && `${name} is not loaded yet.`}
            {status.state === "unavailable" && (status.message || `${name} is not published at the source yet.`)}
            {status.state === "error" && <span className="text-coral">{status.message || "The last build failed."}</span>}
            {BUILDING.has(status.state) && (status.message || stateLabel(status))}
          </div>
          {BUILDING.has(status.state) && (
            <div className="h-1.5 w-full rounded-full bg-line-s overflow-hidden">
              <div className="h-full bg-accent transition-all" style={{ width: `${Math.max(3, (status.progress ?? 0) * 100)}%` }} />
            </div>
          )}
          {(status.state === "none" || status.state === "error" || status.state === "unavailable") && (
            <button
              type="button"
              onClick={async () => setStatus(await buildConference(confKey))}
              className="px-4 py-1.5 text-sm bg-accent text-white rounded-lg hover:bg-violet-700"
            >
              {status.state === "none" ? `Load ${name}` : "Try again"}
            </button>
          )}
        </div>
      )}

      {ov?.partial && (
        <p className="text-xs text-amber">
          Without a login the conference site lists authors and institutions for {ov.with_institution.toLocaleString()} of its{" "}
          {ov.papers.toLocaleString()} papers, so the institution views count those only; topic search covers all of them (titles).
        </p>
      )}

      {ov && view === "overview" && (
        <Overview ov={ov} onView={(v, area) => set({ view: v, area: area != null ? String(area) : null })} onInstitution={(s) => onInstitution(s)} />
      )}
      {ov && view === "institutions" && (
        <InstitutionsView
          confKey={ov.key}
          areas={ov.areas}
          slug={inst}
          initialArea={area != null ? Number(area) : -1}
          onInstitution={onInstitution}
        />
      )}
      {ov && view === "topics" && (
        <TopicView
          confKey={ov.key}
          confName={ov.name}
          areas={ov.areas}
          areasReady={ov.areas_ready}
          query={topicQ}
          k={k}
          onSearch={(text, n) => {
            setTopicQ(text);
            set({ q: text.length <= 300 ? text : null, k: n === 100 ? null : String(n) });
          }}
          onInstitution={(s) => onInstitution(s)}
        />
      )}
      {ov && (
        <p className="text-[11px] text-ink-3">
          Data: <a href={ov.source_url} target="_blank" rel="noopener noreferrer" className="underline hover:text-accent">{ov.source === "miniconf" ? "official conference site" : "Paper Copilot"}</a>,
          fetched {new Date(ov.fetched_at).toLocaleDateString()} ·{" "}
          <button
            type="button"
            className="underline hover:text-accent"
            onClick={async () => {
              setStatus(await buildConference(confKey));
            }}
          >
            refresh
          </button>{" "}
          · a paper counts once for every institution with an author on it; fractional splits each author's 1/n over their institutions.
        </p>
      )}
    </div>
  );
}

export default function Conferences() {
  const { key } = useParams();
  return key ? <Edition key={key} confKey={key} /> : <Landing />;
}
