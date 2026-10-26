import { Link } from "react-router-dom";
import Highlight from "./Highlight";
import { FIELD_LABELS, matchChips } from "./searchUtils";
import type { SearchField, SearchResult } from "../../types";

// The user's own material (note, highlights) is tinted with the accent; everything else neutral.
const OWN: SearchField[] = ["note", "highlight"];

function chipClass(f: SearchField) {
  if (OWN.includes(f)) return "bg-accent-lo text-accent border-accent-border";
  if (f === "semantic") return "bg-blue-50 text-blue-700 border-blue-100";
  return "bg-base text-ink-2 border-line";
}

export default function SearchResultRow({ hit }: { hit: SearchResult }) {
  const authors = hit.authors ?? [];
  const byline = authors.slice(0, 3).join(", ") + (authors.length > 3 ? " et al." : "");
  // Some imports stored the string "null" as the venue.
  const venue = hit.venue && !["null", "none", "undefined"].includes(hit.venue.trim().toLowerCase()) ? hit.venue : "";
  return (
    <li className="bg-raised border border-line rounded-lg hover:border-accent-border hover:shadow-sm transition-all">
      <Link to={`/paper/${hit.id}`} className="block px-4 py-3 space-y-1.5" data-testid="search-hit">
        <div className="flex items-start gap-2">
          <h3 className="flex-1 text-sm font-medium text-ink leading-snug">
            <Highlight text={hit.title} marks={hit.title_marks} />
          </h3>
          {hit.year && <span className="text-xs text-ink-3 shrink-0">{hit.year}</span>}
        </div>
        {(byline || venue || hit.is_reference) && (
          <p className="text-xs text-ink-3 flex flex-wrap items-center gap-x-1.5">
            {byline && <span>{byline}</span>}
            {byline && venue && <span aria-hidden>·</span>}
            {venue && <span className="italic">{venue}</span>}
            {hit.is_reference && (
              <span className="text-[10px] font-semibold uppercase tracking-wide text-amber" title="Cited reference without a PDF in your library">
                Reference
              </span>
            )}
          </p>
        )}
        {(hit.matched_fields?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-1" aria-label="Matched in">
            {matchChips(hit).map((c) => (
              <span key={c.field} className={`text-[11px] px-2 py-0.5 rounded-full border ${chipClass(c.field)}`}>
                {c.label}
              </span>
            ))}
          </div>
        )}
        {hit.snippets?.map((s, i) => (
          <p key={i} className="text-xs text-ink-2 leading-relaxed">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-3 mr-1.5">
              {FIELD_LABELS[s.field] ?? s.field}{s.page != null ? ` · p. ${s.page}` : ""}
            </span>
            <Highlight text={s.text} marks={s.marks} />
          </p>
        ))}
      </Link>
    </li>
  );
}
