import { useEffect, useMemo, useState } from "react";
import { getConferenceInstitution } from "../../api/client";
import type { ConfArea, ConfInstitution } from "../../types";
import AreaBar from "./AreaBar";
import PaperRow from "./PaperRow";

const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;

/** One institution at one conference: rank, counts, area mix against the conference,
 *  collaborators, authors and its papers (filterable by area). */
export default function InstitutionCard({
  confKey,
  slug,
  areas,
  onInstitution,
  onClose,
}: {
  confKey: string;
  slug: string;
  areas: ConfArea[];
  onInstitution: (slug: string) => void;
  onClose: () => void;
}) {
  const [data, setData] = useState<ConfInstitution | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [area, setArea] = useState<number>(-1);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    setArea(-1);
    getConferenceInstitution(confKey, slug)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e instanceof Error ? e.message : "Not found"));
    return () => {
      live = false;
    };
  }, [confKey, slug]);

  const papers = useMemo(
    () => (data ? data.paper_list.filter((p) => area < 0 || p.area === area) : []),
    [data, area],
  );

  if (error) return <div className="bg-raised border border-line rounded-xl p-5 text-sm text-coral">{error}</div>;
  if (!data) return <div className="bg-raised border border-line rounded-xl p-5 text-sm text-ink-3">Loading…</div>;

  const sectorLabel = data.sector === "I" ? "Company" : "University / institute";
  return (
    <div className="bg-raised border border-line rounded-xl shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-line-s flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className={`text-[10px] font-semibold uppercase tracking-wide ${data.sector === "I" ? "text-orange-600" : "text-blue-600"}`}>
            {sectorLabel}
          </div>
          <h2 className="text-lg font-semibold text-ink">{data.name}</h2>
          <div className="mt-1 text-xs text-ink-2">
            #{data.rank} overall{data.sector_rank ? ` · #${data.sector_rank} among ${data.sector === "I" ? "companies" : "universities & institutes"}` : ""}
          </div>
        </div>
        <div className="flex gap-5 text-right">
          <div>
            <div className="text-xl font-semibold text-ink">{data.papers}</div>
            <div className="text-[11px] text-ink-3">papers</div>
          </div>
          <div title="Each author counts 1/n of a paper, split over their institutions">
            <div className="text-xl font-semibold text-ink">{data.fractional.toFixed(1)}</div>
            <div className="text-[11px] text-ink-3">fractional</div>
          </div>
          <div>
            <div className="text-xl font-semibold text-ink">{pct(data.share)}</div>
            <div className="text-[11px] text-ink-3">of the conference</div>
          </div>
        </div>
        <button type="button" onClick={onClose} className="text-ink-3 hover:text-ink-2 text-lg leading-none" aria-label="Close">×</button>
      </div>

      <div className="px-5 py-4 space-y-4">
        <AreaBar
          areas={data.areas}
          compare={data.conference_areas}
          caption="Research areas (thin bar: whole conference; ×n: over-represented)"
          legend={10}
          onPick={(a) => setArea(area === a.index ? -1 : a.index)}
        />

        <div className="grid md:grid-cols-2 gap-4">
          <div>
            <div className="text-[11px] font-medium text-ink-3 uppercase tracking-wide mb-1.5">Most frequent co-authoring institutions</div>
            <div className="flex flex-wrap gap-1.5">
              {data.collaborators.length === 0 && <span className="text-xs text-ink-3">None</span>}
              {data.collaborators.map((c) => (
                <button
                  key={c.slug}
                  type="button"
                  onClick={() => onInstitution(c.slug)}
                  className={`text-xs px-2 py-0.5 rounded-full border ${c.sector === "I" ? "border-orange-200 text-orange-700 hover:bg-orange-50" : "border-blue-200 text-blue-700 hover:bg-blue-50"}`}
                >
                  {c.name} <span className="opacity-60">{c.shared}</span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <div className="text-[11px] font-medium text-ink-3 uppercase tracking-wide mb-1.5">Most papers here</div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ink-2">
              {data.authors.map((a) => (
                <span key={a.name}>
                  {a.name} <span className="text-ink-3">{a.papers}</span>
                </span>
              ))}
            </div>
          </div>
        </div>

        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="text-[11px] font-medium text-ink-3 uppercase tracking-wide">
              Papers {area >= 0 ? `in ${areas[area]?.name}` : ""} ({papers.length})
            </div>
            {area >= 0 && (
              <button type="button" onClick={() => setArea(-1)} className="text-[11px] text-accent hover:underline">show all</button>
            )}
          </div>
          <div className="max-h-[32rem] overflow-y-auto pr-1">
            {papers.map((p) => (
              <PaperRow key={p.id} confKey={confKey} paper={p} areas={areas} onInstitution={onInstitution} focusSlug={data.slug} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
