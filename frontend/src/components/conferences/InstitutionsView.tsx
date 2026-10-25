import { useEffect, useRef, useState } from "react";
import { listConferenceInstitutions } from "../../api/client";
import type { ConfArea, ConfInstRow } from "../../types";
import InstitutionCard from "./InstitutionCard";

const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;
const PAGE = 50;

/** Ranked, searchable table of every institution at the conference, with the selected
 *  institution's card above it. */
export default function InstitutionsView({
  confKey,
  areas,
  slug,
  initialArea = -1,
  onInstitution,
}: {
  confKey: string;
  areas: ConfArea[];
  slug: string | null;
  initialArea?: number;
  onInstitution: (slug: string | null) => void;
}) {
  const [q, setQ] = useState("");
  const [sector, setSector] = useState<"" | "A" | "I">("");
  const [area, setArea] = useState(initialArea);
  useEffect(() => setArea(initialArea), [initialArea]);
  const [rows, setRows] = useState<ConfInstRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      setLoading(true);
      listConferenceInstitutions(confKey, { q, sector, area, offset: 0, limit: PAGE })
        .then((r) => {
          if (!live) return;
          setRows(r.rows);
          setTotal(r.total);
          setError(null);
        })
        .catch((e) => live && setError(e instanceof Error ? e.message : "Failed"))
        .finally(() => live && setLoading(false));
    }, 150);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [confKey, q, sector, area]);

  useEffect(() => {
    if (slug) cardRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [slug]);

  const more = async () => {
    const r = await listConferenceInstitutions(confKey, { q, sector, area, offset: rows.length, limit: PAGE });
    setRows((prev) => [...prev, ...r.rows]);
  };

  const chip = (active: boolean) =>
    `px-3 py-1 text-xs rounded-full border ${active ? "bg-accent text-white border-accent" : "bg-raised text-ink-2 border-line hover:border-accent-border hover:text-accent"}`;

  return (
    <div className="space-y-4">
      <div ref={cardRef} className="scroll-mt-4">
        {slug && (
          <InstitutionCard confKey={confKey} slug={slug} areas={areas} onInstitution={(s) => onInstitution(s)} onClose={() => onInstitution(null)} />
        )}
      </div>

      <div className="bg-raised border border-line rounded-xl p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Find an institution (MIT, Tsinghua, Google…)"
            className="flex-1 min-w-[16rem] border border-line rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-300"
            onKeyDown={(e) => {
              if (e.key === "Enter" && rows[0]) onInstitution(rows[0].slug);
            }}
          />
          <button type="button" className={chip(sector === "")} onClick={() => setSector("")}>All</button>
          <button type="button" className={chip(sector === "A")} onClick={() => setSector("A")}>Academia</button>
          <button type="button" className={chip(sector === "I")} onClick={() => setSector("I")}>Industry</button>
          <select
            value={area}
            onChange={(e) => setArea(Number(e.target.value))}
            className="border border-line rounded-lg px-2 py-1.5 text-xs text-ink-2 bg-raised"
          >
            <option value={-1}>All research areas</option>
            {areas.filter((a) => a.count > 0).map((a) => (
              <option key={a.index} value={a.index}>{a.name} ({a.count})</option>
            ))}
          </select>
        </div>
        <div className="text-xs text-ink-3">
          {loading ? "Loading…" : `${total.toLocaleString()} institution${total === 1 ? "" : "s"}${area >= 0 ? ` with ${areas[area]?.short} papers` : ""}`}
          {error && <span className="text-coral ml-2">{error}</span>}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[11px] uppercase tracking-wide text-ink-3 border-b border-line">
                <th className="text-right font-medium py-2 pr-3 w-12">#</th>
                <th className="text-left font-medium py-2">Institution</th>
                <th className="text-right font-medium py-2 px-3">{area >= 0 ? areas[area]?.short : "Papers"}</th>
                <th className="text-right font-medium py-2 px-3" title="Each author counts 1/n of a paper">Fractional</th>
                <th className="text-right font-medium py-2 px-3">{area >= 0 ? "Of own" : "Share"}</th>
                <th className="text-left font-medium py-2 pl-3 w-48">Areas</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const tot = r.areas.reduce((a, b) => a + b, 0) || 1;
                return (
                  <tr
                    key={r.slug}
                    onClick={() => onInstitution(r.slug)}
                    className={`border-b border-line-s cursor-pointer hover:bg-accent-lo ${r.slug === slug ? "bg-accent-lo" : ""}`}
                  >
                    <td className="text-right py-1.5 pr-3 text-ink-3 tabular-nums">{area >= 0 && !q ? r.area_rank : r.rank}</td>
                    <td className="py-1.5">
                      <span className={`inline-block w-1.5 h-1.5 rounded-full mr-2 align-middle ${r.sector === "I" ? "bg-orange-500" : "bg-blue-500"}`} />
                      <span className="text-ink">{r.name}</span>
                    </td>
                    <td className="text-right py-1.5 px-3 tabular-nums text-ink">{r.count}</td>
                    <td className="text-right py-1.5 px-3 tabular-nums text-ink-2">{r.fractional.toFixed(1)}</td>
                    <td className="text-right py-1.5 px-3 tabular-nums text-ink-2">{pct(area >= 0 ? (r.of_own ?? 0) : r.share, area >= 0 ? 0 : 1)}</td>
                    <td className="py-1.5 pl-3">
                      <div className="flex h-2 w-44 overflow-hidden rounded-full bg-line-s">
                        {r.areas.map((c, i) =>
                          c > 0 ? <div key={i} style={{ flex: c, background: areas[i]?.color }} title={`${areas[i]?.name}: ${c} (${pct(c / tot, 0)})`} /> : null,
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {rows.length < total && (
          <button type="button" onClick={more} className="w-full py-2 text-sm border border-line text-ink-2 rounded-lg hover:border-accent-border hover:text-accent">
            Show more ({(total - rows.length).toLocaleString()} left)
          </button>
        )}
      </div>
    </div>
  );
}
