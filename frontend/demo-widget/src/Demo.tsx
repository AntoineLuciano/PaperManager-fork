/**
 * The Knowledge Chat demo: recorded conversations replayed with the app's own components.
 * Tabs on the left (a chip row on narrow screens), the transcript on the right with the
 * branch lane, concept cards, structure cards and citations that open a preview of the paper.
 * Nothing is sent anywhere; the conversations are static JSON next to the bundle.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { BranchLane, type Branch } from '../../src/components/kchat/BranchLane';
import ConceptCard from '../../src/components/kchat/ConceptCard';
import { ChatLinksContext, Markdown, type ChatLinks } from '../../src/components/kchat/Markdown';
import { citedPapers, splitSections } from '../../src/components/kchat/sections';
import type { ConceptSpec } from '../../src/types';
import { where } from './config';

type PaperRef = { id: string; title?: string | null; year?: number | string | null };
type Paper = { title?: string | null; year?: number | string | null; venue?: string | null; summary?: string; link?: string | null; cited?: boolean };
type Concept = { label?: string; section: number; spec: ConceptSpec };
type Msg = { role: 'user' | 'assistant'; content: string; papers?: PaperRef[]; concepts?: Concept[] };
type Tab = { slug: string; title: string; hint?: string; parent?: string | null; fork_at?: number | null };
type Conv = Tab & { messages: Msg[]; papers: Record<string, Paper> };

const json = <T,>(url: string): Promise<T> => fetch(url).then((r) => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json() as Promise<T>;
});

/* ------------------------------------------------------------- an answer */

function Answer({ msg, onPaper }: { msg: Msg; onPaper: (p: PaperRef) => void }) {
  const [showContext, setShowContext] = useState(false);
  const [copied, setCopied] = useState(false);
  const sections = useMemo(() => splitSections(msg.content), [msg.content]);
  const cited = useMemo(() => citedPapers(msg.content), [msg.content]);
  const cards = (msg.concepts ?? []).map((c, i) => ({ c, i }));
  const placed = (s: number) => cards.filter(({ c }) => Math.min(c.section, sections.length - 1) === s);
  const context = msg.papers ?? [];
  const copy = async () => {
    try { await navigator.clipboard.writeText(msg.content); setCopied(true); setTimeout(() => setCopied(false), 1200); } catch { /* no clipboard */ }
  };
  return (
    <div className="msg assistant">
      {sections.map((sec, s) => (
        <div key={s} className="kc-section">
          {sec.trim() && <Markdown text={sec} />}
          {placed(s).map(({ c, i }) => (
            <ConceptCard key={i} spec={c.spec} label={c.label} footnote="made from this answer" />
          ))}
        </div>
      ))}
      <div className="kc-answer-foot">
        {cited.length > 0 && <span className="kc-kicker">Cited</span>}
        {cited.map((p) => (
          <button type="button" key={p.id} className="kc-src-chip k-paper" onClick={() => onPaper(p)} title={p.title}><span>{p.title}</span></button>
        ))}
        {context.length > 0 && (
          <button type="button" className="kc-src-more" onClick={() => setShowContext((v) => !v)}>
            {context.length} in context {showContext ? '▾' : '▸'}
          </button>
        )}
        <span className="kc-spacer" />
        <button type="button" className="kc-mini" onClick={copy}>{copied ? 'copied' : 'copy'}</button>
      </div>
      {showContext && (
        <div className="kc-src-list kc-context-papers">
          {context.map((p) => (
            <button type="button" key={p.id} className="kc-src-chip" onClick={() => onPaper(p)}>{p.title}{p.year ? ` · ${p.year}` : ''}</button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------- paper preview */

function Preview({ paper, onClose }: { paper: Paper & { id: string }; onClose: () => void }) {
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => { body.current?.scrollTo({ top: 0 }); }, [paper.id]);
  return (
    <aside className="kc-preview pmd-preview" aria-label="Paper preview">
      <div className="kc-preview-head">
        <span className="kc-kicker">Paper</span>
        <span className="kc-spacer" />
        <button type="button" className="kc-mini" onClick={onClose} aria-label="Close preview">×</button>
      </div>
      <div className="kc-preview-body" ref={body}>
        <article className="kc-paper">
          <h2>{paper.title}</h2>
          <div className="kc-paper-meta">{[paper.year, paper.venue].filter(Boolean).join(' · ')}</div>
          {paper.link && (
            <div className="kc-paper-actions">
              <a className="kc-btn-lg primary" href={paper.link} target="_blank" rel="noopener noreferrer">Open the paper ↗</a>
            </div>
          )}
          {paper.summary ? (
            <section>
              <h3 className="kc-kicker">Summary in the library</h3>
              <Markdown text={paper.summary} />
            </section>
          ) : (
            <p className="kc-muted kc-abstract">
              {paper.cited
                ? 'No summary is stored for this paper in the library yet.'
                : "This paper was in the model's context. In the app this pane shows its summary, abstract and figures; the demo keeps them only for the papers an answer cites."}
            </p>
          )}
        </article>
      </div>
    </aside>
  );
}

/* ---------------------------------------------- animations off-screen */

/**
 * Animation cards run in sandboxed iframes; pause the ones that are out of view (or in a
 * hidden tab) and give them back the speed their card shows when they return.
 */
function usePauseOffscreen(root: ShadowRoot) {
  useEffect(() => {
    const visible = new WeakMap<HTMLIFrameElement, boolean>();
    const cardSpeed = (f: HTMLIFrameElement) => {
      const card = f.closest('figure');
      const buttons = Array.from(card?.querySelectorAll<HTMLButtonElement>('header .kc-btn') ?? []);
      if (buttons.some((b) => b.title === 'Play')) return 0;
      const on = buttons.find((b) => b.classList.contains('on') && /×$/.test(b.textContent ?? ''));
      return on ? parseFloat(on.textContent ?? '1') : 1;
    };
    const apply = (f: HTMLIFrameElement) => {
      const speed = visible.get(f) && !document.hidden ? cardSpeed(f) : 0;
      f.contentWindow?.postMessage({ type: 'concept-anim-speed', speed }, '*');
    };
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) { const f = e.target as HTMLIFrameElement; visible.set(f, e.isIntersecting); apply(f); }
    });
    const frames = () => Array.from(root.querySelectorAll<HTMLIFrameElement>('.kc-concept-stage iframe'));
    const seen = new WeakSet<HTMLIFrameElement>();
    const watch = () => frames().forEach((f) => { if (!seen.has(f)) { seen.add(f); io.observe(f); } });
    const mo = new MutationObserver(watch);
    mo.observe(root, { childList: true, subtree: true });
    watch();
    // A card sends its speed when the frame reports ready; correct it right after.
    const onMessage = (ev: MessageEvent) => {
      if (ev.data?.type !== 'concept-anim-ready') return;
      const f = frames().find((x) => x.contentWindow === ev.source);
      if (f) setTimeout(() => apply(f), 60);
    };
    const onVis = () => frames().forEach(apply);
    window.addEventListener('message', onMessage);
    document.addEventListener('visibilitychange', onVis);
    return () => {
      io.disconnect(); mo.disconnect();
      window.removeEventListener('message', onMessage);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [root]);
}

/* ----------------------------------------------------------------- demo */

export default function Demo({ root }: { root: ShadowRoot }) {
  const [tabs, setTabs] = useState<Tab[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [convs, setConvs] = useState<Record<string, Conv>>({});
  const [preview, setPreview] = useState<(Paper & { id: string }) | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const thread = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  usePauseOffscreen(root);

  const load = useCallback((slug: string) => {
    if (convs[slug]) return;
    json<Conv>(`${where.data}${slug}.json`)
      .then((c) => setConvs((x) => ({ ...x, [slug]: c })))
      .catch((e: Error) => setError(`Could not load this conversation (${e.message}).`));
  }, [convs]);

  useEffect(() => {
    json<{ tabs: Tab[] }>(`${where.data}manifest.json`)
      .then((m) => { setTabs(m.tabs); setActive(m.tabs[0]?.slug ?? null); })
      .catch((e: Error) => setError(`Could not load the demo (${e.message}).`));
  }, []);
  // The open tab first, then the rest in the background so switching is instant.
  useEffect(() => {
    if (!tabs || !active) return;
    load(active);
    const t = setTimeout(() => tabs.forEach((t) => load(t.slug)), 400);
    return () => clearTimeout(t);
  }, [tabs, active, load]);

  const open = (slug: string) => {
    if (slug === active) return;
    setActive(slug);
    setPreview(null);
    scroller.current?.scrollTo({ top: 0 });
    // In the chip row (narrow screens) bring the chip into view without scrolling the page.
    const chip = tabRefs.current[slug], row = chip?.parentElement;
    if (chip && row && row.scrollWidth > row.clientWidth) row.scrollTo({ left: chip.offsetLeft - 12, behavior: 'smooth' });
  };

  const conv = active ? convs[active] : undefined;
  const tab = tabs?.find((t) => t.slug === active);

  // A strand opens where it leaves its parent: its first own question near the top.
  useEffect(() => {
    if (!conv || !tab?.fork_at) return;
    const q = thread.current?.querySelector<HTMLElement>(`.msg.user[data-turn="${tab.fork_at}"]`);
    const sc = scroller.current;
    if (q && sc) sc.scrollTo({ top: q.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - 90 });
  }, [conv, tab?.fork_at]);
  const parentTab = tab?.parent ? tabs?.find((t) => t.slug === tab.parent) : undefined;

  const openPaper = useCallback((p: PaperRef) => {
    const c = active ? convs[active] : undefined;
    const known = c?.papers[p.id];
    setPreview({ id: p.id, title: p.title, year: p.year, ...known });
  }, [active, convs]);
  const links: ChatLinks = useMemo(() => ({
    openPaper: (id, title) => openPaper({ id, title }),
    openFigure: () => {},
  }), [openPaper]);

  const onTabKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!tabs || !active) return;
    const i = tabs.findIndex((t) => t.slug === active);
    const d = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const next = tabs[(i + d + tabs.length) % tabs.length];
    open(next.slug);
    tabRefs.current[next.slug]?.focus();
  };

  const asBranch = (t: Tab): Branch => ({ id: t.slug, at: t.fork_at ?? 0, label: t.title, kind: 'strand' });
  const children = (tabs ?? []).filter((t) => t.parent && t.parent === active).map(asBranch);
  const self = tab?.parent ? asBranch(tab) : undefined;
  const questions = conv?.messages.filter((m) => m.role === 'user').length ?? 0;
  let turn = 0;

  return (
    <ChatLinksContext.Provider value={links}>
      <div className={`kchat pmd ${preview ? 'pmd-with-preview' : ''}`}>
        <aside className="kc-rail pmd-rail">
          <div className="kc-brand"><span className="kc-brand-mark" />Knowledge Chat</div>
          <div className="kc-sessions-head"><span className="kc-kicker">Examples</span><span className="pmd-count">{tabs?.length ?? ''}</span></div>
          <div className="pmd-tabs" role="tablist" aria-label="Example conversations" aria-orientation="vertical" onKeyDown={onTabKey}>
            {(tabs ?? []).map((t) => (
              <button
                type="button" role="tab" key={t.slug} id={`pmd-tab-${t.slug}`}
                ref={(b) => { tabRefs.current[t.slug] = b; }}
                aria-selected={t.slug === active} aria-controls="pmd-panel" tabIndex={t.slug === active ? 0 : -1}
                className={`kc-row pmd-tab ${t.slug === active ? 'current' : ''} ${t.parent ? 'branch pmd-strand' : ''}`}
                onClick={() => open(t.slug)}
              >
                <span className="kc-row-title">
                  {t.parent && <span className="kc-branch-glyph" style={{ ['--c' as string]: 'var(--lane-branch)' }}>⑂</span>}
                  <span>{t.title}</span>
                </span>
                {t.hint && <span className="pmd-hint">{t.hint}</span>}
              </button>
            ))}
          </div>
          <p className="pmd-rail-foot">
            Recorded answers from a real library, replayed with the app's own components: cards,
            plots, animations and molecules are live.
          </p>
        </aside>

        <main className="kc-main" id="pmd-panel" role="tabpanel" aria-labelledby={active ? `pmd-tab-${active}` : undefined}>
          <header className="kc-topbar">
            <div className="kc-title">
              {parentTab && (
                <button type="button" className="kc-crumb" onClick={() => open(parentTab.slug)} title="Back to the conversation this strand came from">
                  ↑ {parentTab.title}
                </button>
              )}
              <h1>{tab?.title ?? 'Knowledge Chat'}</h1>
            </div>
            <span className="kc-model-pill" title="Model that wrote these answers">Claude Code</span>
          </header>

          <div className="kc-scroll" ref={scroller}>
            <div className={`thread ${conv ? 'with-lane' : ''}`} ref={thread}>
              {conv && (
                <BranchLane thread={thread} version={conv} turns={questions} running={false} self={self}
                  parentTitle={parentTab?.title} children={children} onOpen={(b) => open(b.id)}
                  onOpenParent={() => parentTab && open(parentTab.slug)} />
              )}
              {error && <div className="kc-note error">{error}</div>}
              {!conv && !error && <div className="kc-working"><span className="kc-spinner" /> loading the conversation…</div>}
              {conv?.messages.map((m, i) => {
                if (m.role === 'user') {
                  const k = turn++;
                  return (
                    <div key={i} className="msg user" data-turn={k}>
                      <div className="bubble-row"><div className="user-text">{m.content}</div></div>
                    </div>
                  );
                }
                return <Answer key={i} msg={m} onPaper={openPaper} />;
              })}
            </div>
          </div>

          <div className="pmd-composer" aria-hidden="true">
            <div className="pmd-composer-shell">
              <span>A recorded conversation. In PaperManager you ask your own library, scoped with
                <code>@project:</code> or <code>@topic:</code> if you like.</span>
              <span className="kc-send pmd-send">Send</span>
            </div>
          </div>
        </main>

        {preview && <Preview paper={preview} onClose={() => setPreview(null)} />}
      </div>
    </ChatLinksContext.Provider>
  );
}
