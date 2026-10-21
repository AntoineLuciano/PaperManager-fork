/**
 * The demo as static markup, prerendered into the host page: one tab per sample paper, each with
 * the paper and one recorded question and answer. Tabs are radio buttons, so switching works
 * without any script; answers are the app's Markdown (KaTeX, tables, code); concept and structure
 * cards are islands, a still image the browser replaces with the live card.
 */
import { Markdown } from '../../src/components/kchat/Markdown';
import { citedPapers, splitSections } from '../../src/components/kchat/sections';
import type { ConceptSpec } from '../../src/types';
import { Island } from './Island';

export type Paper = { title: string; authors: string; year?: number | string | null; venue?: string | null; blurb?: string; link?: string | null };
export type Tab = {
  slug: string;
  short: string;
  /** What the answer shows, on the tab ("formula & plot", "protein in 3D"). */
  hint?: string;
  /** A one-character glyph for the tab. */
  icon?: string;
  paper: Paper;
  question: string;
  answer: string;
  concepts: { label?: string; section: number; spec: ConceptSpec }[];
  /** Papers cited in the answer, by library id: where the citation links to. */
  cited: Record<string, { title?: string | null; link?: string | null }>;
};

/** Library links `[title](/paper/<id>)` point at the paper itself (DOI or arXiv), or become text. */
function withPaperLinks(text: string, cited: Tab['cited']): string {
  return text.replace(/\[([^\]\n]+)\]\(\/paper\/([0-9a-f-]{36})\/?\)/gi, (_m, title: string, id: string) => {
    const link = cited[id]?.link;
    return link ? `[${title}](${link})` : title;
  });
}

function Answer({ tab }: { tab: Tab }) {
  const sections = splitSections(withPaperLinks(tab.answer, tab.cited));
  const cards = tab.concepts.map((c, i) => ({ c, i }));
  const placed = (s: number) => cards.filter(({ c }) => Math.min(c.section, sections.length - 1) === s);
  const cited = citedPapers(tab.answer);
  return (
    <div className="msg assistant">
      {sections.map((sec, s) => (
        <div key={s} className="kc-section">
          {sec.trim() && <Markdown text={sec} />}
          {placed(s).map(({ c, i }) => (
            <Island key={i} kind="concept" type={c.spec.type} label={`Concept card: ${c.spec.title || c.label || ''}`}
              payload={JSON.stringify({ spec: c.spec, label: c.label, foot: true })} />
          ))}
        </div>
      ))}
      {cited.length > 0 && (
        <div className="kc-answer-foot">
          <span className="kc-kicker">Cited</span>
          {cited.map((p) => {
            const link = tab.cited[p.id]?.link;
            return link
              ? <a key={p.id} className="kc-src-chip k-paper" href={link} target="_blank" rel="noopener noreferrer" title={p.title}><span>{p.title}</span></a>
              : <span key={p.id} className="kc-src-chip k-paper" title={p.title}><span>{p.title}</span></span>;
          })}
        </div>
      )}
    </div>
  );
}

function Panel({ tab, i, n }: { tab: Tab; i: number; n: number }) {
  const p = tab.paper;
  return (
    <section className="pmd-panel" data-i={i} aria-label={`${i + 1} of ${n}: ${p.title}`}>
      <header className="kc-topbar">
        <div className="kc-title"><h1>{tab.short}</h1></div>
        <span className="kc-model-pill" title="Model that wrote this answer">Claude Code</span>
        <span className="pmd-step">
          <label htmlFor={`pmd-r${(i + n - 1) % n}`} className="pmd-arrow" title="Previous paper" aria-hidden="true">‹</label>
          <span className="pmd-of">{i + 1} / {n}</span>
          <label htmlFor={`pmd-r${(i + 1) % n}`} className="pmd-arrow" title="Next paper" aria-hidden="true">›</label>
        </span>
      </header>
      <div className="kc-scroll">
        <div className="thread">
          <div className="pmd-paper">
            <span className="kc-kicker">In the library</span>
            <h2>{p.link ? <a href={p.link} target="_blank" rel="noopener noreferrer">{p.title}</a> : p.title}</h2>
            <div className="pmd-paper-meta">{[p.authors, p.year, p.venue].filter(Boolean).join(' · ')}</div>
            {p.blurb && <p>{p.blurb}</p>}
          </div>
          <div className="msg user">
            <div className="bubble-row"><div className="user-text">{tab.question}</div></div>
          </div>
          <Answer tab={tab} />
        </div>
      </div>
    </section>
  );
}

export function Widget({ tabs }: { tabs: Tab[] }) {
  const n = tabs.length;
  return (
    <div className="kchat pmd">
      {tabs.map((t, i) => (
        <input key={t.slug} type="radio" name="pmd-tab" id={`pmd-r${i}`} className="pmd-radio" value={t.slug}
          defaultChecked={i === 0} aria-label={`${i + 1}: ${t.short}${t.hint ? `, ${t.hint}` : ''}`} />
      ))}
      <nav className="pmd-bar" aria-label="Sample papers">
        <div className="pmd-bar-head">
          <span className="kc-brand-mark" />
          <span className="pmd-bar-title">Knowledge Chat</span>
          <span className="pmd-bar-note">{n} sample papers · one question each · pick one</span>
        </div>
        <div className="pmd-tabs">
          {tabs.map((t, i) => (
            <label key={t.slug} htmlFor={`pmd-r${i}`} data-i={i} className="pmd-tab">
              <span className="pmd-num">{i + 1}</span>
              <span className="pmd-tab-text">
                <span className="pmd-tab-title">{t.short}</span>
                {t.hint && <span className="pmd-tab-kind">{t.icon && <i aria-hidden="true">{t.icon}</i>}{t.hint}</span>}
              </span>
            </label>
          ))}
        </div>
      </nav>
      <main className="kc-main">
        {tabs.map((t, i) => <Panel key={t.slug} tab={t} i={i} n={n} />)}
      </main>
    </div>
  );
}
