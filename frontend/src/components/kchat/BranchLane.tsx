// Ported from the thesis desk's branch lane (050_system/src/components/BranchLane.tsx).
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type RefObject } from 'react';

/** A fork of a conversation as the lane draws it: after `at` questions, named by its first new question. */
export type Branch = { id: string; at: number; label: string; kind: 'strand' | 'edit' };

/** Lane colour of a conversation: the trunk is the app's violet, strands and edits get their own. */
export const laneColour = (b?: Pick<Branch, 'kind'> | null) => (!b ? 'var(--lane-trunk)' : b.kind === 'edit' ? 'var(--lane-edit)' : 'var(--lane-branch)');

const X = 14;          // the session's own line, at rest
const BX = 40;         // where a branch leaves to
const BEND = 24;       // vertical run of the curve from the line to the branch node
/* The line is not ruled: like the thread on the website's team page it wavers
 * slowly as it runs down, a few pixels either side over a few hundred. */
const SWAY = 2.6;
const WAVE = 340;
const lx = (y: number) => X + SWAY * Math.sin((2 * Math.PI * y) / WAVE) + 0.6 * SWAY * Math.sin((2 * Math.PI * y) / (WAVE * 2.7) + 1.3);
type Pt = [number, number];
/** The line's course from y1 to y2, sampled on a fixed 5 px grid so pieces that overlap agree exactly. */
function strandPts(y1: number, y2: number, x: (y: number) => number = lx): Pt[] {
  if (y2 <= y1) return [];
  const pts: Pt[] = [[x(y1), y1]];
  for (let y = Math.floor(y1 / 5) * 5 + 5; y < y2; y += 5) pts.push([x(y), y]);
  pts.push([x(y2), y2]);
  return pts;
}

/* The line is elastic: the pointer pulls it sideways in a bump about RADIUS px
 * tall, and let go it eases back with a single small overshoot. */
const RADIUS = 140, REACH = 2.5 * RADIUS;   // past REACH the bump is under 0.03 px
const PULL = 1.6, MAX_PULL = 15;
const STIFF = 0.10, DAMP = 0.75;    // one small overshoot, settled in about 0.6 s
const still = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
type Bend = { y: number; a: number };
const bent = (b: Bend) => (y: number) => lx(y) + (b.a ? b.a * Math.exp(-(((y - b.y) / RADIUS) ** 2)) : 0);
const reaches = (b: Bend, y1: number, y2: number) => b.a !== 0 && b.y + REACH > y1 && b.y - REACH < y2;

/** A cubic Bézier, sampled. */
function bezierPts(p0: Pt, p1: Pt, p2: Pt, p3: Pt, n = 16): Pt[] {
  const out: Pt[] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, u = 1 - t;
    out.push([
      u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
      u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
    ]);
  }
  return out;
}


/*
 * The ink pen of the website's old /manifesto page (Website/src/pages/Manifesto.jsx):
 * the line is not a stroke but a filled ribbon whose half-width swells towards
 * its middle (there 4.4 + 2.75·sin(πy/H) px; here at about 40 %), filled through
 * the 0 → 72 % → 72 % → 0 fade. The website roughens its edge with an SVG
 * displacement filter; over a chat tens of thousands of pixels tall that filter
 * re-runs on every repaint and stalls scrolling, so here the rough edge is part
 * of the outline itself: each edge vertex is pushed in or out by a fixed noise
 * keyed on its height, so the same stretch always looks the same.
 */
const HALF = 2.4, SWELL = 1.4;
const ROUGH = 1.25;    // how far the ragged edge strays, px
const hash = (n: number) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return 2 * (x - Math.floor(x)) - 1; };
/** Edge noise in [-1, 1]: a fine grain over a slower ragged swell, per side. */
const grain = (y: number, side: number) => {
  const k = Math.round(y / 5), c = Math.floor(y / 20), f = y / 20 - c;
  return 0.6 * hash(k * 2 + side) + 0.4 * ((1 - f) * hash(c * 2 + side + 9001) + f * hash((c + 1) * 2 + side + 9001));
};
type Width = (y: number) => number;
function ribbon(pts: Pt[], half: Width): string {
  if (pts.length < 2) return '';
  const L: string[] = [], R: string[] = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(pts.length - 1, i + 1)];
    const dx = b[0] - a[0], dy = b[1] - a[1], d = Math.hypot(dx, dy) || 1;
    const y = pts[i][1], w = half(y);
    const wr = Math.max(0.6, w + ROUGH * grain(y, 0)), wl = Math.max(0.6, w + ROUGH * grain(y, 1));
    R.push(`${(pts[i][0] - (-dy / d) * wr).toFixed(1)} ${(pts[i][1] - (dx / d) * wr).toFixed(1)}`);
    L.push(`${(pts[i][0] + (-dy / d) * wl).toFixed(1)} ${(pts[i][1] + (dx / d) * wl).toFixed(1)}`);
  }
  return `M ${R.join(' L ')} L ${L.reverse().join(' L ')} Z`;
}
/** The pen swells towards the middle of the line from y1 to y2. */
const swellOver = (y1: number, y2: number): Width => (y) => HALF + SWELL * Math.sin((Math.PI * (y - y1)) / Math.max(1, y2 - y1));
const even: Width = () => HALF + SWELL * 0.5;

/*
 * A chat's line is tens of thousands of pixels and vertices long. It is cut into
 * pieces at fixed heights, cached, so a re-render rebuilds none of it and a bend
 * rebuilds only the one or two pieces it reaches. Neighbouring pieces overlap by
 * one sample and are drawn opaque inside a group that carries the opacity, so the
 * overlaps never show as darker seams.
 */
const PIECE = 200;
const outlines = new Map<string, string>();
function pieces(tag: string, y1: number, y2: number, half: Width, bend: Bend): { key: number; d: string }[] {
  const out: { key: number; d: string }[] = [];
  if (outlines.size > 2000) outlines.clear();
  for (let t = Math.floor(y1 / PIECE) * PIECE; t < y2; t += PIECE) {
    const a = Math.max(y1, t), b = Math.min(y2, t + PIECE + 5);
    if (b <= a) continue;
    let d: string | undefined;
    if (reaches(bend, a, b)) d = ribbon(strandPts(a, b, bent(bend)), half);
    else {
      const key = `${tag}|${y1}|${y2}|${t}`;
      d = outlines.get(key);
      if (d === undefined) outlines.set(key, (d = ribbon(strandPts(a, b), half)));
    }
    out.push({ key: t, d });
  }
  return out;
}


type Props = {
  /** The thread element holding the `.msg.user[data-turn]` bubbles. */
  thread: RefObject<HTMLDivElement | null>;
  /** Re-measure when the transcript changes. */
  version: unknown;
  turns: number;
  running: boolean;
  /** This session's own registry entry, when it is itself a branch. */
  self?: Branch;
  parentTitle?: string;
  children: Branch[];
  onOpen: (b: Branch) => void;
  onOpenParent: () => void;
};

/**
 * The git-style lane beside the transcript: one dot per question of yours,
 * a curve leaving the line wherever a branch or side question was forked,
 * and, in a branch, the inherited stretch drawn in the parent's colour.
 */
export function BranchLane({ thread, version, turns, running, self, parentTitle, children, onOpen, onOpenParent }: Props) {
  const [ys, setYs] = useState<number[]>([]);
  const [height, setHeight] = useState(0);
  /** The turn under the pointer, and where along the line the pointer is. */
  const [hot, setHot] = useState<{ i: number; y: number } | null>(null);
  /** The bend: where along the line it is pulled, and how far sideways. */
  const [bend, setBend] = useState<Bend>({ y: 0, a: 0 });
  const spring = useRef({ y: 0, ty: 0, a: 0, v: 0, target: 0, raf: 0, scrolled: 0 });
  const step = () => {
    const sp = spring.current;
    sp.v = (sp.v + (sp.target - sp.a) * STIFF) * DAMP;
    sp.a += sp.v;
    sp.y += (sp.ty - sp.y) * 0.25;             // the bump glides after the pointer along the line
    const done = Math.abs(sp.v) < 0.02 && Math.abs(sp.target - sp.a) < 0.05 && Math.abs(sp.ty - sp.y) < 0.5;
    if (done) sp.a = sp.target;
    setBend({ y: sp.y, a: sp.a });
    sp.raf = done ? 0 : requestAnimationFrame(step);
  };
  const pull = (y: number, target: number) => {
    const sp = spring.current;
    if (still || performance.now() - sp.scrolled < 150) return;
    if (!sp.a && !sp.raf) sp.y = y;            // a fresh pull starts where the pointer is
    sp.ty = y;
    sp.target = target;
    if (!sp.raf) sp.raf = requestAnimationFrame(step);
  };
  useEffect(() => () => cancelAnimationFrame(spring.current.raf), []);
  // While the chat scrolls the line lies straight: scrolling under a resting pointer
  // would otherwise pluck it on every step.
  useEffect(() => {
    const scroller = thread.current?.parentElement;
    if (!scroller) return;
    const onScroll = () => {
      const sp = spring.current;
      sp.scrolled = performance.now();
      if (!sp.a && !sp.raf) return;
      cancelAnimationFrame(sp.raf);
      Object.assign(sp, { a: 0, v: 0, target: 0, raf: 0 });
      setBend({ y: sp.y, a: 0 });
    };
    scroller.addEventListener('scroll', onScroll, { passive: true });
    return () => scroller.removeEventListener('scroll', onScroll);
  }, [thread]);

  // Measure against the thread's own box. The lane is absolutely placed with
  // `inset: 0`, so it follows that box and can never enlarge the scroll area.
  useLayoutEffect(() => {
    const el = thread.current;
    if (!el) return;
    const measure = () => {
      const top = el.getBoundingClientRect().top;
      const next = Array.from(el.querySelectorAll<HTMLElement>('.msg.user[data-turn] .user-text'))
        .map((b) => Math.round(b.getBoundingClientRect().top - top + 21));
      setYs((cur) => (cur.length === next.length && cur.every((v, i) => v === next[i]) ? cur : next));
      setHeight(el.offsetHeight);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [thread, version, turns]);

  // The hovered stretch lights its question's bubble in the transcript.
  useEffect(() => {
    const el = hot ? thread.current?.querySelectorAll<HTMLElement>('.msg.user[data-turn]')[hot.i] : undefined;
    el?.classList.add('lane-hot');
    el?.style.setProperty('--lane-c', hot && hot.i < (self ? self.at : 0) ? 'var(--lane-trunk)' : laneColour(self));
    return () => { el?.classList.remove('lane-hot'); el?.style.removeProperty('--lane-c'); };
  }, [hot?.i, thread, self]);

  if (!ys.length || !height) return null;
  const last = ys[ys.length - 1];
  const floor = height - 30;                       // nothing is drawn below this
  // The line runs through the last answer too, not just to the last question.
  const end = Math.max(last, floor);
  // A fork after `at` turns sits just above bubble `at`, or below the last one when it is the tip.
  const forkY = (at: number) => (at < ys.length ? ys[at] - 62 : Math.min(Math.max(last + 30, height - 80), floor - BEND));

  const bx = bent(bend);
  const own = laneColour(self);
  const parent = self ? laneColour(null) : own;
  const inherited = self ? Math.min(self.at, ys.length) : 0;
  const switchY = self ? forkY(self.at) : 0;
  const from = self && inherited > 0 ? switchY : ys[0];

  // Branches forked at the same point share one curve and one node.
  const groups = new Map<number, Branch[]>();
  for (const b of children) groups.set(b.at, [...(groups.get(b.at) ?? []), b]);

  const scrollTo = (i: number) => bubble(i)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  // Hover cards near the end open upwards, so they never reach past it either.
  const up = (y: number) => (y > height - 140 ? 'up' : '');
  const curvePts = (y: number, toLine: boolean): Pt[] => {
    const x0 = bx(y);
    return toLine
      ? bezierPts([BX, y - BEND], [BX, y - 8], [x0, y - 14], [x0, y])
      : bezierPts([x0, y], [x0, y + 14], [BX, y + 8], [BX, y + BEND]);
  };
  const lineFrom = self && inherited > 0 ? from : Math.max(0, ys[0] - 40);
  // the gradient's fades, as fractions of the line: in over its first 40 px, out over its last 30
  const span = Math.max(1, end - lineFrom);
  const fadeIn = self && inherited > 0 ? 0.0001 : Math.min(0.45, 40 / span);
  const fadeOut = running ? 0 : Math.min(0.45, 30 / span);

  // Turn i owns the line from just above its question to just above the next one.
  const segTop = (i: number) => (i === 0 ? lineFrom : ys[i] - 30);
  const segBot = (i: number) => (i + 1 < ys.length ? ys[i + 1] - 30 : end);
  const turnAt = (y: number) => { let i = 0; while (i + 1 < ys.length && y >= ys[i + 1] - 30) i++; return i; };
  const bubble = (i: number) => thread.current?.querySelectorAll<HTMLElement>('.msg.user[data-turn]')[i];
  // One fixed column takes every pointer event for the line and its dots.
  // Nothing that moves with the bend takes the pointer, so it cannot slide out from under it.
  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const box = e.currentTarget.parentElement!.getBoundingClientRect();
    const y = e.clientY - box.top;
    pull(y, Math.max(-MAX_PULL, Math.min(MAX_PULL, (e.clientX - box.left - lx(y)) * PULL)));
    const i = turnAt(y);
    setHot((h) => (h && h.i === i && Math.abs(h.y - y) < 2 ? h : { i, y }));
  };
  const onLeave = () => { setHot(null); pull(spring.current.ty, 0); };
  const hotText = hot ? bubble(hot.i)?.querySelector('.user-text')?.textContent?.replace(/\s+/g, ' ').trim() ?? '' : '';

  return (
    <div className="lane">
      <svg width="64" height={height} className="lane-svg" style={{ color: own }} aria-hidden>
        <defs>
          <linearGradient id="lane-fade" x1="0" y1={lineFrom} x2="0" y2={Math.max(end, lineFrom + 1)} gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="currentColor" stopOpacity="0" />
            <stop offset={fadeIn} stopColor="currentColor" stopOpacity="1" />
            <stop offset={1 - fadeOut} stopColor="currentColor" stopOpacity="1" />
            <stop offset="1" stopColor="currentColor" stopOpacity={running ? 1 : 0} />
          </linearGradient>
        </defs>
        {self && inherited > 0 && (
          <g className="lane-inherited">
            {pieces('inh', Math.max(0, ys[0] - 40), Math.min(switchY, end), even, bend).map((p) => <path key={p.key} d={p.d} fill={parent} />)}
          </g>
        )}
        <g opacity=".72">
          {pieces('own', lineFrom, end, swellOver(lineFrom, end), bend).map((p) => <path key={p.key} d={p.d} fill="url(#lane-fade)" />)}
        </g>
        <g>
          {self && <path d={ribbon(curvePts(switchY, true), even)} fill={own} fillOpacity=".72" />}
          {[...groups].map(([at, bs]) => (
            <path key={at} d={ribbon(curvePts(forkY(at), false), even)} fill={laneColour(bs[bs.length - 1])} fillOpacity=".72" />
          ))}
        </g>
        {hot && <path key={hot.i} d={ribbon(strandPts(segTop(hot.i), segBot(hot.i), bx), (y) => 1.4 * swellOver(lineFrom, end)(y))} fill={hot.i < inherited ? parent : own} className="lane-press" />}
        {/* hairlines tying each dot to its bubble */}
        {ys.map((y, i) => <line key={i} x1={-10} x2={bx(y) - 10} y1={y} y2={y} stroke={i < inherited ? parent : own} strokeWidth="1" opacity={hot?.i === i ? 0.9 : 0.3} />)}
        {running && <circle cx={bx(end)} cy={end} r="3.5" fill={own} className="lane-pulse" />}
      </svg>

      <div className="lane-grab" style={{ top: Math.max(0, ys[0] - 40), height: Math.max(0, end - Math.max(0, ys[0] - 40)) }}
        onMouseMove={onMove} onMouseLeave={onLeave} onClick={() => hot && scrollTo(hot.i)} />

      {ys.map((y, i) => (
        <button
          type="button"
          key={i}
          className={`lane-dot ${i < inherited ? 'inherited' : ''} ${hot?.i === i ? 'hot' : ''}`}
          style={{ top: y, left: bx(y), ['--c' as string]: i < inherited ? parent : own }}
          onClick={() => scrollTo(i)}
          tabIndex={-1}
          aria-label={`Your question ${i + 1}`}
        />
      ))}

      {/* at a dot the ringed bubble beside it already says what the card would */}
      {hot && Math.abs(hot.y - ys[hot.i]) > 24 && (
        <div className="lane-tip" style={{ top: hot.y, left: lx(hot.y), ['--c' as string]: hot.i < inherited ? parent : own }}>
          <div className="lane-card-kicker">
            question {hot.i + 1} of {ys.length}{hot.i < inherited ? ` · from ${parentTitle || 'the parent chat'}` : self ? ' · this strand' : ''}
          </div>
          <div className="lane-tip-text">{hotText || '…'}</div>
        </div>
      )}

      {self && (
        <div className={`lane-node origin ${up(switchY - BEND)}`} style={{ top: switchY - BEND, left: BX, ['--c' as string]: parent }}>
          <button type="button" className="lane-knob" onClick={onOpenParent} aria-label="Open the parent chat">↑</button>
          <div className="lane-card">
            <div className="lane-card-kicker">forked from</div>
            <button type="button" className="lane-card-row" onClick={onOpenParent}>
              <span className="lane-swatch" style={{ background: parent }} />
              <span className="lane-card-title">{parentTitle || 'parent chat'}</span>
              <span className="lane-card-meta">after {self.at} turn{self.at === 1 ? '' : 's'}</span>
            </button>
          </div>
        </div>
      )}

      {[...groups].map(([at, bs]) => {
        const latest = bs[bs.length - 1];
        return (
          <div key={at} className={`lane-node ${up(forkY(at) + BEND)}`} style={{ top: forkY(at) + BEND, left: BX, ['--c' as string]: laneColour(latest) }}>
            <button type="button" className={`lane-knob k-${latest.kind}`} onClick={() => onOpen(latest)} aria-label="Open strand">
              {bs.length > 1 ? bs.length : '⑂'}
            </button>
            <div className="lane-card">
              <div className="lane-card-kicker">{bs.length > 1 ? `${bs.length} strands` : latest.kind === 'edit' ? 'edit' : 'strand'} · after question {at}</div>
              {bs.map((b) => (
                <button type="button" key={b.id} className="lane-card-row" onClick={() => onOpen(b)}>
                  <span className="lane-swatch" style={{ background: laneColour(b) }} />
                  <span className="lane-card-title">{b.label || '(nothing asked yet)'}</span>
                  <span className="lane-card-meta">{b.kind}</span>
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
