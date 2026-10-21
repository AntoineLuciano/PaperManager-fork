/**
 * The browser side of the prerendered demo. The page already shows everything (tabs, papers,
 * questions, answers, still images of the cards); this makes the cards in the open tab live:
 * formula, graph and note cards at once, animations in their sandboxed frame, structures in
 * 3Dmol.js once its script and coordinates have loaded. Whatever fails keeps its still image.
 * It also moves the widget's violet to the host page's accent colour.
 */
import { StrictMode, Suspense } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { ConceptSpec } from '../../src/types';
import './palette';
import { accentize, followHost, getAccent, subscribeAccent } from './accent';
import { where } from './config';
import { stillUrl } from './keys';
import { LiveConcept, LiveStructure, Still } from './Live';


const mounted = new WeakMap<HTMLElement, Root>();

function mountIsland(el: HTMLElement) {
  if (mounted.has(el)) return;
  const key = el.dataset.key ?? '';
  const payload = el.dataset.payload ?? '';
  const still = stillUrl(key);
  let node: React.ReactNode;
  try {
    if (el.dataset.kind === 'structure') {
      node = (
        <Suspense fallback={<Still src={still} note="loading the 3D view …" />}>
          <LiveStructure source={payload} still={still} />
        </Suspense>
      );
    } else {
      const { spec, label, foot } = JSON.parse(payload) as { spec: ConceptSpec; label?: string; foot?: boolean };
      node = <LiveConcept spec={spec} label={label} foot={foot} still={still} />;
    }
  } catch { return; }
  const root = createRoot(el);
  mounted.set(el, root);
  root.render(<StrictMode>{node}</StrictMode>);
}

/** Pause animation frames that are out of view, and restore the speed their card shows. */
function pauseOffscreen(root: ShadowRoot) {
  const visible = new WeakMap<HTMLIFrameElement, boolean>();
  const cardSpeed = (f: HTMLIFrameElement) => {
    const buttons = Array.from(f.closest('figure')?.querySelectorAll<HTMLButtonElement>('header .kc-btn') ?? []);
    if (buttons.some((b) => b.title === 'Play')) return 0;
    const on = buttons.find((b) => b.classList.contains('on') && /×$/.test(b.textContent ?? ''));
    return on ? parseFloat(on.textContent ?? '1') : 1;
  };
  const apply = (f: HTMLIFrameElement) => {
    const shown = f.closest<HTMLElement>('.pmd-panel') ? getComputedStyle(f.closest<HTMLElement>('.pmd-panel')!).visibility !== 'hidden' : true;
    const speed = visible.get(f) && shown && !document.hidden ? cardSpeed(f) : 0;
    f.contentWindow?.postMessage({ type: 'concept-anim-speed', speed }, '*');
  };
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) { const f = e.target as HTMLIFrameElement; visible.set(f, e.isIntersecting); apply(f); }
  });
  const frames = () => Array.from(root.querySelectorAll<HTMLIFrameElement>('.kc-concept-stage iframe'));
  const seen = new WeakSet<HTMLIFrameElement>();
  new MutationObserver(() => frames().forEach((f) => { if (!seen.has(f)) { seen.add(f); io.observe(f); } }))
    .observe(root, { childList: true, subtree: true });
  window.addEventListener('message', (ev) => {
    if (ev.data?.type !== 'concept-anim-ready') return;
    const f = frames().find((x) => x.contentWindow === ev.source);
    if (f) setTimeout(() => apply(f), 60);
  });
  document.addEventListener('visibilitychange', () => frames().forEach(apply));
  root.addEventListener('change', () => frames().forEach(apply));
}

/** The stylesheet the prerender linked, replaced by the same text with violet moved to the accent. */
async function followAccent(root: ShadowRoot) {
  followHost();
  const link = root.querySelector<HTMLLinkElement>('link[rel=stylesheet]');
  if (!link) return;
  const css = await fetch(link.href).then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))));
  const style = document.createElement('style');
  let frame = 0;
  const paint = () => { frame = 0; style.textContent = accentize(css, getAccent()); };
  paint();
  link.after(style);
  link.remove();
  subscribeAccent(() => { if (!frame) frame = requestAnimationFrame(paint); });
}

export function start(root: ShadowRoot, at: { base: string; data: string }) {
  Object.assign(where, at);
  followAccent(root).catch(() => { /* the violet sheet stays */ });
  pauseOffscreen(root);
  const openPanel = () => {
    const radios = Array.from(root.querySelectorAll<HTMLInputElement>('input.pmd-radio'));
    const i = Math.max(0, radios.findIndex((r) => r.checked));
    root.querySelector<HTMLElement>(`.pmd-panel[data-i="${i}"]`)
      ?.querySelectorAll<HTMLElement>('.pmd-island').forEach(mountIsland);
    // tell the loader once the cards have rendered (it re-centres the highlight)
    setTimeout(() => root.dispatchEvent(new Event('pmd-mounted')), 120);
    setTimeout(() => root.dispatchEvent(new Event('pmd-mounted')), 1500);
  };
  root.addEventListener('change', openPanel);
  openPanel();
}
