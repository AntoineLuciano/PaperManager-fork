import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "../api/client";

export interface TourStop {
  page: number;
  anchor_found: boolean;
  title: string;
  kind: string;
  anchor: string;
  explanation: string;
  concepts: string[];
}
interface Tour { overview: string; skip: string; stops: TourStop[]; generated_at: string | null }
interface TourStatus { tour: Tour | null; running: boolean; error: string | null; available: boolean; hint: string | null }

const KIND_STYLE: Record<string, string> = {
  problem: "bg-rose-100 text-rose-700", background: "bg-gray-100 text-gray-600",
  definition: "bg-sky-100 text-sky-700", method: "bg-violet-100 text-violet-700",
  equation: "bg-indigo-100 text-indigo-700", result: "bg-emerald-100 text-emerald-700",
  figure: "bg-amber-100 text-amber-700", limitation: "bg-orange-100 text-orange-700",
  takeaway: "bg-teal-100 text-teal-700",
};

interface Props {
  paperId: string;
  hasPdf: boolean;
  activeIndex: number | null;
  onStopsChange: (stops: TourStop[]) => void;
  onActivate: (index: number | null) => void;
}

export default function TourPanel({ paperId, hasPdf, activeIndex, onStopsChange, onActivate }: Props) {
  const [status, setStatus] = useState<TourStatus | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  const apply = useCallback((s: TourStatus) => {
    setStatus(s);
    onStopsChange(s.tour?.stops ?? []);
  }, [onStopsChange]);

  useEffect(() => {
    apiFetch<TourStatus>(`/papers/${paperId}/tour`).then(apply).catch((e) => setStartError(String(e)));
  }, [paperId, apply]);

  useEffect(() => {
    if (!status?.running) return;
    const t = setInterval(() => {
      apiFetch<TourStatus>(`/papers/${paperId}/tour`).then(apply).catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [status?.running, paperId, apply]);

  const stops = status?.tour?.stops ?? [];

  // ← / → step through the tour while this panel is open (not while typing).
  useEffect(() => {
    if (!stops.length) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, [contenteditable=true]")) return;
      if (e.key === "ArrowRight") onActivate(activeIndex == null ? 0 : Math.min(stops.length - 1, activeIndex + 1));
      if (e.key === "ArrowLeft") onActivate(activeIndex == null ? 0 : Math.max(0, activeIndex - 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [stops.length, activeIndex, onActivate]);

  const start = async () => {
    setStartError(null);
    try {
      apply(await apiFetch<TourStatus>(`/papers/${paperId}/tour`, { method: "POST" }));
    } catch (e) {
      setStartError(String(e).replace(/^Error: API \d+: /, ""));
    }
  };

  if (!hasPdf) return <p className="text-xs text-gray-400 text-center mt-8">The tour needs the paper's PDF.</p>;
  if (!status) return <p className="text-xs text-gray-400 text-center mt-8">Loading…</p>;

  const tour = status.tour;
  return (
    <div className="h-full overflow-y-auto text-sm">
      <div className="flex items-center gap-2 mb-3">
        <button onClick={start} disabled={status.running || !status.available}
          className="text-xs px-2.5 py-1 bg-violet-600 text-white rounded hover:bg-violet-700 disabled:opacity-50">
          {status.running ? "Sonnet is reading…" : tour ? "Regenerate tour" : "Make a quick tour"}
        </button>
        {stops.length > 0 && (
          <div className="ml-auto flex items-center gap-1 text-xs text-gray-500">
            <button onClick={() => onActivate(Math.max(0, (activeIndex ?? 0) - 1))} className="px-1.5 py-0.5 border border-gray-200 rounded hover:border-violet-300">←</button>
            <span>{activeIndex == null ? "–" : activeIndex + 1} / {stops.length}</span>
            <button onClick={() => onActivate(activeIndex == null ? 0 : Math.min(stops.length - 1, activeIndex + 1))} className="px-1.5 py-0.5 border border-gray-200 rounded hover:border-violet-300">→</button>
          </div>
        )}
      </div>
      {!status.available && <p className="text-xs text-amber-700 bg-amber-50 rounded p-2 mb-3">{status.hint}</p>}
      {(status.error || startError) && <p className="text-xs text-red-600 mb-3">{status.error || startError}</p>}
      {status.running && !tour && (
        <p className="text-xs text-gray-400">Sonnet reads the whole PDF with the summary and concepts; this takes about a minute.</p>
      )}

      {tour && (
        <>
          <div className="bg-violet-50 rounded-lg p-3 mb-3">
            <p className="text-gray-800 leading-relaxed">{tour.overview}</p>
            {tour.skip && <p className="text-xs text-gray-500 mt-2"><span className="font-medium">Skip on a quick read:</span> {tour.skip}</p>}
          </div>
          <ol className="space-y-2">
            {stops.map((s, i) => {
              const active = i === activeIndex;
              return (
                <li key={i}>
                  <button onClick={() => onActivate(active ? null : i)}
                    className={`w-full text-left rounded-lg border p-2.5 transition-colors ${active ? "border-violet-400 bg-violet-50/60" : "border-gray-100 hover:border-violet-200"}`}>
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs font-semibold text-violet-700 w-5">{i + 1}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${KIND_STYLE[s.kind] ?? "bg-gray-100 text-gray-600"}`}>{s.kind}</span>
                      <span className="text-xs font-medium text-gray-800 flex-1">{s.title}</span>
                      <span className="text-[10px] text-gray-400">p. {s.page + 1}{s.anchor_found ? "" : " ?"}</span>
                    </div>
                    {active && (
                      <div className="mt-2 pl-6 space-y-1.5">
                        <blockquote className="text-xs text-gray-500 italic border-l-2 border-violet-300 pl-2">{s.anchor}</blockquote>
                        <p className="text-xs text-gray-700 leading-relaxed">{s.explanation}</p>
                        {s.concepts.length > 0 && (
                          <div className="flex flex-wrap gap-1">{s.concepts.map((c) => (
                            <span key={c} className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600">{c}</span>
                          ))}</div>
                        )}
                      </div>
                    )}
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="text-[10px] text-gray-400 mt-3">← / → to step · highlighted passages are marked in the PDF{tour.generated_at ? ` · made ${tour.generated_at.slice(0, 10)}` : ""}</p>
        </>
      )}
    </div>
  );
}
