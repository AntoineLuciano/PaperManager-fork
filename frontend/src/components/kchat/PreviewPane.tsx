// The right-hand pane, as in the thesis desk: a cited paper or a figure beside the chat.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, apiUrl } from "../../api/client";
import type { Figure, Paper } from "../../types";
import { Markdown } from "./Markdown";

export type Preview =
  | { kind: "paper"; id: string; title: string }
  | { kind: "figure"; src: string; caption: string };

export function PreviewPane({ preview, onClose, onOpen }: { preview: Preview; onClose: () => void; onOpen: (p: Preview) => void }) {
  return (
    <aside className="kc-preview" aria-label="Preview">
      <div className="kc-preview-head">
        <span className="kc-kicker">{preview.kind === "paper" ? "Paper" : "Figure"}</span>
        <span className="kc-spacer" />
        <button type="button" className="kc-mini" onClick={onClose} aria-label="Close preview">×</button>
      </div>
      <div className="kc-preview-body">
        {preview.kind === "paper"
          ? <PaperPreview id={preview.id} title={preview.title} onOpen={onOpen} />
          : (
            <figure className="kc-preview-figure">
              <img src={preview.src} alt={preview.caption} />
              {preview.caption && <figcaption>{preview.caption}</figcaption>}
            </figure>
          )}
      </div>
    </aside>
  );
}

function PaperPreview({ id, title, onOpen }: { id: string; title: string; onOpen: (p: Preview) => void }) {
  const [paper, setPaper] = useState<Paper | null>(null);
  const [figures, setFigures] = useState<Figure[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setPaper(null); setFigures([]); setError(null);
    apiFetch<Paper>(`/papers/${id}`).then((p) => live && setPaper(p)).catch((e: Error) => live && setError(e.message));
    apiFetch<Figure[]>(`/papers/${id}/figures`).then((f) => live && setFigures(f)).catch(() => {});
    return () => { live = false; };
  }, [id]);

  if (error) return <p className="kc-muted">Could not load this paper ({error}).</p>;
  const shown = paper ?? ({ title } as Partial<Paper>);
  return (
    <article className="kc-paper">
      <h2>{shown.title}</h2>
      <div className="kc-paper-meta">
        {[paper?.year, paper?.venue].filter(Boolean).join(" · ")}
        {paper?.doi && <> · <a href={`https://doi.org/${paper.doi}`} target="_blank" rel="noreferrer">doi</a></>}
      </div>
      <div className="kc-paper-actions">
        <Link className="kc-btn-lg primary" to={`/paper/${id}`}>Open in library</Link>
        {paper?.drive_file_id && <a className="kc-btn-lg" href={apiUrl(`/papers/${id}/pdf`)} target="_blank" rel="noreferrer">PDF ↗</a>}
      </div>
      {!paper && <p className="kc-muted">Loading…</p>}
      {paper?.summary && (
        <section>
          <h3 className="kc-kicker">Summary</h3>
          <Markdown text={paper.summary} />
        </section>
      )}
      {paper && !paper.summary && !paper.abstract && (
        <p className="kc-muted kc-abstract">No summary or abstract is stored for this paper yet; open it in the library to add one.</p>
      )}
      {paper?.abstract && (
        <section>
          <h3 className="kc-kicker">Abstract</h3>
          <p className="kc-abstract">{paper.abstract}</p>
        </section>
      )}
      {figures.filter((f) => f.drive_file_id).length > 0 && (
        <section>
          <h3 className="kc-kicker">Figures</h3>
          <div className="kc-fig-grid">
            {figures.filter((f) => f.drive_file_id).slice(0, 12).map((f) => {
              const src = apiUrl(`/papers/${id}/figures/${f.id}/image`);
              const caption = f.caption || `Figure ${f.figure_number ?? ""}`;
              return (
                <button type="button" key={f.id} title={caption} onClick={() => onOpen({ kind: "figure", src, caption })}>
                  <img src={src} alt={caption} loading="lazy" />
                </button>
              );
            })}
          </div>
        </section>
      )}
    </article>
  );
}
