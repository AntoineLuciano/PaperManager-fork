import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { addConferencePaper, getConferencePaper } from "../../api/client";
import type { ConfArea, ConfPaper, ConfPaperDetail } from "../../types";
import Highlight, { type HighlightTerms } from "./Highlight";

const DECISION_STYLE: Record<string, string> = {
  Oral: "bg-amber-50 text-amber-700 border-amber-200",
  Spotlight: "bg-sky-50 text-sky-700 border-sky-200",
  Highlight: "bg-sky-50 text-sky-700 border-sky-200",
};

/** One conference paper: title, match, area, decision, session, institutions; expands to
 *  abstract, authors with institutions and similar papers; adds itself to the library.
 *  `conference` adds a chip linking to the conference (search across conferences);
 *  `note` is an extra line under the metadata; `highlight` marks the query's words in the
 *  title. The title button carries `data-result` for arrow-key navigation. */
export default function PaperRow({
  confKey,
  paper,
  areas,
  onInstitution,
  focusSlug,
  conference,
  note,
  highlight,
}: {
  confKey: string;
  paper: ConfPaper;
  areas: ConfArea[] | { name: string; short: string; color: string }[];
  onInstitution?: (slug: string) => void;
  focusSlug?: string;
  conference?: { key: string; name: string };
  note?: ReactNode;
  highlight?: HighlightTerms | null;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ConfPaperDetail | null>(null);
  const [libraryId, setLibraryId] = useState<string | null>(paper.library_id ?? null);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const area = paper.area >= 0 ? areas[paper.area] : null;
  const link = paper.url || paper.forum;

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !detail) {
      try {
        setDetail(await getConferencePaper(confKey, paper.id));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load the paper");
      }
    }
  };

  const add = async () => {
    setAdding(true);
    setError(null);
    try {
      const res = await addConferencePaper(confKey, paper.id);
      setLibraryId(res.paper_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the paper");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="py-3 border-b border-line-s last:border-0">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <button
            type="button"
            onClick={toggle}
            data-result=""
            aria-expanded={open}
            className="text-left text-sm font-medium text-ink hover:text-accent rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-300"
          >
            <Highlight text={paper.title} terms={highlight} />
          </button>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-ink-3">
            {conference && (
              <Link
                to={`/conferences/${conference.key}`}
                className="px-1.5 py-px rounded bg-accent-lo text-accent border border-accent-border font-medium hover:bg-violet-100"
                title={`Open ${conference.name}`}
              >
                {conference.name}
              </Link>
            )}
            {paper.match != null && (
              <span className="font-mono text-ink-2" title="Cosine similarity to your query">match {(paper.match * 100).toFixed(0)}</span>
            )}
            {area && (
              <span className="inline-flex items-center gap-1">
                <i className="inline-block w-2 h-2 rounded-sm" style={{ background: area.color }} />
                {area.short}
              </span>
            )}
            {paper.decision && paper.decision !== "Poster" && (
              <span className={`px-1.5 py-px rounded border ${DECISION_STYLE[paper.decision] ?? "bg-gray-50 text-ink-2 border-line"}`}>
                {paper.decision}
              </span>
            )}
            {paper.track && <span className="px-1.5 py-px rounded border border-line">{paper.track}</span>}
            {paper.session && <span title="Session">{paper.session}</span>}
            {paper.institutions.map((i) => (
              <button
                key={i.slug}
                type="button"
                onClick={() => onInstitution?.(i.slug)}
                className={`px-1.5 py-px rounded-full border ${
                  i.slug === focusSlug
                    ? "border-accent text-accent"
                    : i.sector === "I"
                      ? "border-orange-200 text-orange-700 hover:bg-orange-50"
                      : "border-blue-200 text-blue-700 hover:bg-blue-50"
                }`}
              >
                {i.name}
              </button>
            ))}
            {paper.more_institutions > 0 && <span>+{paper.more_institutions} more</span>}
          </div>
          {note && <div className="mt-0.5 text-[11px] text-ink-2">{note}</div>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {link && (
            <a href={link} target="_blank" rel="noopener noreferrer" className="text-xs text-ink-3 hover:text-accent" title="Open at the conference">
              ↗
            </a>
          )}
          {libraryId ? (
            <Link to={`/paper/${libraryId}`} className="text-[11px] px-2 py-1 rounded-lg bg-accent-lo text-accent border border-accent-border">
              In library
            </Link>
          ) : (
            <button
              type="button"
              onClick={add}
              disabled={adding}
              className="text-[11px] px-2 py-1 rounded-lg border border-line text-ink-2 hover:border-accent-border hover:text-accent disabled:opacity-50"
            >
              {adding ? "Adding…" : "+ Library"}
            </button>
          )}
        </div>
      </div>
      {error && <p className="mt-1 text-xs text-coral">{error}</p>}
      {open && (
        <div className="mt-2 ml-1 pl-3 border-l-2 border-accent-border space-y-2">
          {!detail && !error && <p className="text-xs text-ink-3">Loading…</p>}
          {detail && (
            <>
              {detail.abstract ? (
                <p className="text-xs leading-relaxed text-ink-2 whitespace-pre-line">{detail.abstract}</p>
              ) : (
                <p className="text-xs text-ink-3">The conference has not published the abstract yet.</p>
              )}
              <p className="text-xs text-ink-2">
                {detail.author_list.map((a, n) => (
                  <span key={n}>
                    {n > 0 && ", "}
                    <span className="text-ink">{a.name}</span>
                    {a.institutions.length > 0 && <span className="text-ink-3"> ({a.institutions.join("; ")})</span>}
                  </span>
                ))}
              </p>
              {detail.similar && detail.similar.length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold text-ink-3 uppercase tracking-wide mb-1">Closest papers at this conference</div>
                  <ul className="space-y-0.5">
                    {detail.similar.map((s) => (
                      <li key={s.id} className="text-xs text-ink-2">
                        <span className="font-mono text-ink-3 mr-1.5">{((s.match ?? 0) * 100).toFixed(0)}</span>
                        {s.url || s.forum ? (
                          <a href={s.url || s.forum} target="_blank" rel="noopener noreferrer" className="hover:text-accent">{s.title}</a>
                        ) : s.title}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
