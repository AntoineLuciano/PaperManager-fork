/**
 * Loader for the Knowledge Chat demo. The page already holds the whole demo, prerendered in a
 * declarative shadow root (see prerender.tsx), so nothing waits on this script. It
 *  - makes the cards in the open example live (the app chunk, loaded near the viewport),
 *  - opens each example at its highlight (the card), with the question pinned above it,
 *  - drives an optional menu in the host page (`data-pm-chat-menu="<selector>"` on the element,
 *    items marked `data-pm-chat-tab="<index>"`): click, tap, hover and arrow keys pick an example,
 *  - reveals a newly picked example through a mosaic of growing rounded shapes (a clip path on
 *    the closest `[data-pm-chat-clip]` ancestor, else the element; WebKit does not clip a shadow
 *    host itself), then leaves it unclipped and interactive. Off with prefers-reduced-motion.
 * Browsers that do not parse declarative shadow roots get one made here from the same template.
 * If anything fails, the prerendered demo stays as it is.
 */
const base = new URL('.', import.meta.url).href;
const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

function shadowOf(el: HTMLElement): ShadowRoot | null {
  if (el.shadowRoot) return el.shadowRoot;
  const tpl = el.querySelector<HTMLTemplateElement>(':scope > template[shadowrootmode]');
  if (!tpl) return null;
  const root = el.attachShadow({ mode: 'open' });
  root.appendChild(tpl.content);
  tpl.remove();
  return root;
}

const radios = (root: ShadowRoot) => Array.from(root.querySelectorAll<HTMLInputElement>('input.pmd-radio'));
const current = (root: ShadowRoot) => Math.max(0, radios(root).findIndex((r) => r.checked));
const panelOf = (root: ShadowRoot, i: number) => root.querySelector<HTMLElement>(`.pmd-panel[data-i="${i}"]`);

/* --------------------------------------------------------- the highlight */
// Scroll the example's transcript so its best card (a structure, else an animation, a plot, a
// formula) sits just under the pinned question. An answer without cards opens at the top.
const RANK = ['structure', '2d-anim', 'graph', 'formula', '2d-text'];
function toHighlight(panel: HTMLElement | null, onlyIfUntouched = false) {
  const scroller = panel?.querySelector<HTMLElement>('.kc-scroll');
  const rank = (e: HTMLElement) => { const r = RANK.indexOf(e.dataset.type ?? ''); return r < 0 ? 9 : r; };
  const target = Array.from(panel?.querySelectorAll<HTMLElement>('.pmd-island') ?? []).sort((a, b) => rank(a) - rank(b))[0];
  if (!panel || !scroller || !target) return;
  if (onlyIfUntouched && scroller.dataset.touched) return;
  const question = panel.querySelector<HTMLElement>('.msg.user');
  const offset = (question?.offsetHeight ?? 0) + 24;
  const top = target.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop - offset;
  scroller.scrollTop = Math.max(0, top);
}

/** Keep each example at its highlight while its layout settles (stylesheet, fonts, stills, live
 *  cards), until the visitor scrolls it themselves. */
function holdHighlights(root: ShadowRoot) {
  root.querySelectorAll<HTMLElement>('.pmd-panel').forEach((panel) => {
    const scroller = panel.querySelector<HTMLElement>('.kc-scroll'), thread = panel.querySelector<HTMLElement>('.thread');
    if (!scroller || !thread) return;
    const touch = () => { scroller.dataset.touched = '1'; };
    ['wheel', 'touchstart', 'pointerdown', 'keydown'].forEach((e) => scroller.addEventListener(e, touch, { passive: true, once: true }));
    toHighlight(panel);
    if ('ResizeObserver' in window) new ResizeObserver(() => toHighlight(panel, true)).observe(thread);
  });
}

/* ------------------------------------------------------------ the mosaic */
type Tile = [number, number, number, number];   // x, y, w, h as fractions of the box
const PATTERNS: Tile[][] = [
  // stacked bars
  [0, 1, 2, 3, 4].map((k) => [0, k / 5, 1, 0.2] as Tile),
  // a mosaic of rounded rectangles
  [[0, 0, 0.55, 0.38], [0.55, 0, 0.45, 0.22], [0.55, 0.22, 0.45, 0.4], [0, 0.38, 0.3, 0.32], [0.3, 0.38, 0.25, 0.32],
    [0, 0.7, 0.42, 0.3], [0.42, 0.7, 0.58, 0.3], [0.55, 0.62, 0.45, 0.08]],
  // a 3 × 3 grid
  [0, 1, 2].flatMap((r) => [0, 1, 2].map((c) => [c / 3, r / 3, 1 / 3, 1 / 3] as Tile)),
  // columns
  [0, 1, 2, 3, 4, 5].map((k) => [k / 6, 0, 1 / 6, 1] as Tile),
];

const expoOut = (t: number) => (t >= 1 ? 1 : 1 - 2 ** (-10 * t));
const pathOK = typeof CSS !== 'undefined' && !!CSS.supports?.('clip-path', 'path("M0 0H1V1Z")');

function roundRect(x: number, y: number, w: number, h: number, r: number): string {
  r = Math.min(r, w / 2, h / 2);
  const f = (n: number) => n.toFixed(1);
  return `M${f(x + r)} ${f(y)}h${f(w - 2 * r)}a${f(r)} ${f(r)} 0 0 1 ${f(r)} ${f(r)}v${f(h - 2 * r)}a${f(r)} ${f(r)} 0 0 1 ${f(-r)} ${f(r)}`
    + `h${f(-(w - 2 * r))}a${f(r)} ${f(r)} 0 0 1 ${f(-r)} ${f(-r)}v${f(-(h - 2 * r))}a${f(r)} ${f(r)} 0 0 1 ${f(r)} ${f(-r)}z`;
}

const clipOf = (el: HTMLElement) => el.closest<HTMLElement>('[data-pm-chat-clip]') ?? el;

let playing = 0;
/** Reveal `el` through the pattern's shapes, each growing from its centre (expo out, random stagger). */
function mosaic(el: HTMLElement, pattern: number) {
  cancelAnimationFrame(playing);
  el.style.clipPath = '';
  if (still()) return;
  const W = el.offsetWidth, H = el.offsetHeight;
  if (!W || !H) return;
  if (!pathOK) {
    el.animate([{ opacity: 0, transform: 'scale(.985)' }, { opacity: 1, transform: 'none' }], { duration: 450, easing: 'cubic-bezier(.16,1,.3,1)' });
    return;
  }
  const tiles = PATTERNS[pattern % PATTERNS.length];
  const delays = tiles.map(() => Math.random() * 380);
  const DUR = 820, R = 22, t0 = performance.now();
  const frame = (now: number) => {
    let done = true;
    const d = tiles.map(([x, y, w, h], k) => {
      const t = Math.min(1, Math.max(0, (now - t0 - delays[k]) / DUR));
      if (t < 1) done = false;
      const s = expoOut(t);
      if (s <= 0.001) return '';
      // tiles overlap by a pixel and lose their rounding at full size, so the union is the whole box
      const tw = (w * W + 1) * s, th = (h * H + 1) * s;
      return roundRect(x * W + (w * W - tw) / 2, y * H + (h * H - th) / 2, tw, th, R * (1 - s * s));
    }).join('');
    if (done) { el.style.clipPath = ''; return; }
    el.style.clipPath = `path("${d || 'M0 0'}")`;
    playing = requestAnimationFrame(frame);
  };
  el.style.clipPath = 'path("M0 0")';
  playing = requestAnimationFrame(frame);
}

/* -------------------------------------------------------------- the menu */
function wireMenu(el: HTMLElement, root: ShadowRoot): () => void {
  const menu = el.dataset.pmChatMenu ? document.querySelector<HTMLElement>(el.dataset.pmChatMenu) : null;
  const items = menu ? Array.from(menu.querySelectorAll<HTMLElement>('[data-pm-chat-tab]')) : [];
  if (!menu || !items.length) return () => {};
  el.setAttribute('data-menu', '');
  menu.setAttribute('role', 'tablist');
  el.setAttribute('role', 'tabpanel');
  const select = (i: number) => {
    const r = radios(root)[i];
    if (!r || r.checked) return;
    r.checked = true;
    r.dispatchEvent(new Event('change', { bubbles: true }));
  };
  let hover = 0;
  items.forEach((it, k) => {
    const i = Number(it.dataset.pmChatTab);
    it.setAttribute('role', 'tab');
    if (it.parentElement?.tagName === 'LI') it.parentElement.setAttribute('role', 'presentation');
    if (!it.id) it.id = `pm-chat-tab-${k}`;
    if (el.id) it.setAttribute('aria-controls', el.id);
    it.addEventListener('click', () => select(i));
    // Hovering picks too (mouse only, after a moment, so passing over an item does not).
    it.addEventListener('pointerenter', (e) => {
      if (e.pointerType !== 'mouse') return;
      clearTimeout(hover);
      hover = window.setTimeout(() => select(i), 160);
    });
    it.addEventListener('pointerleave', () => clearTimeout(hover));
    it.addEventListener('keydown', (e) => {
      const n = items.length;
      const to = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? (k + 1) % n
        : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? (k + n - 1) % n
          : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : -1;
      if (to < 0) return;
      e.preventDefault();
      items[to].focus();
      select(Number(items[to].dataset.pmChatTab));
    });
  });
  return () => {
    const i = current(root);
    items.forEach((it) => {
      const on = Number(it.dataset.pmChatTab) === i;
      it.setAttribute('aria-selected', String(on));
      it.tabIndex = on ? 0 : -1;
      if (on) el.setAttribute('aria-labelledby', it.id);
    });
  };
}

/* ------------------------------------------------------------------ boot */
function boot(el: HTMLElement) {
  if (el.dataset.pmChatDemoBooted) return;
  el.dataset.pmChatDemoBooted = '1';
  const root = shadowOf(el);
  if (!root) return;
  const data = new URL(el.dataset.pmChatDemo || './', document.baseURI).href;
  let started = false;
  const start = () => {
    if (started) return;
    started = true;
    import('./app').then((m) => m.start(root, { base, data })).catch(() => { /* the static demo stays */ });
  };

  const sync = wireMenu(el, root);
  root.addEventListener('pmd-mounted', () => toHighlight(panelOf(root, current(root)), true));
  root.addEventListener('change', () => {
    const i = current(root);
    sync();
    toHighlight(panelOf(root, i), true);
    mosaic(clipOf(el), i);
    // In the chip row (narrow screens) bring the chosen tab into view, without moving the page.
    const tab = root.querySelector<HTMLElement>(`.pmd-tab[data-i="${i}"]`), row = tab?.parentElement;
    if (tab && row && row.scrollWidth > row.clientWidth) row.scrollTo({ left: tab.offsetLeft - row.offsetLeft - 14, behavior: 'smooth' });
  });
  sync();
  holdHighlights(root);

  if (!('IntersectionObserver' in window)) { start(); return; }
  const near = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { near.disconnect(); start(); }
  }, { rootMargin: '600px 0px' });
  near.observe(el);
  const seen = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { seen.disconnect(); mosaic(clipOf(el), current(root)); }
  }, { threshold: 0.15 });
  seen.observe(el);
}

function scan() {
  document.querySelectorAll<HTMLElement>('[data-pm-chat-demo]').forEach(boot);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan);
else scan();
