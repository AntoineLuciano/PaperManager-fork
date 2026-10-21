/**
 * The host page's accent colour, and the app's violet mapped onto it.
 *
 * PaperManager's UI is violet (violet-600 #7c3aed and its tints and shades). A host page can
 * change the widget's accent: it dispatches `pm:accent` on document with `detail.hex` (and may
 * expose `window.PMAccent.get()`); without either, `?accent=<hex>` in the page URL is read once.
 * Every colour whose hue lies in the violet band is moved to the accent's hue, its saturation
 * scaled and its lightness re-anchored at the accent's, so a light tint stays a light tint.
 * Colours outside the band (greys, blues, ambers, greens, pLDDT bands) are never touched.
 */
import { useSyncExternalStore } from 'react';
import type { ConceptSpec } from '../../src/types';

export const VIOLET = '#7c3aed';
const REF = { h: 262.1, s: 0.832, l: 0.58 };  // violet-600 in HSL

export type HSL = { h: number; s: number; l: number };

export function hexToRgb(hex: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{3,8})$/i.exec(hex.trim());
  if (!m) return null;
  let v = m[1];
  if (v.length === 3 || v.length === 4) v = v.split('').map((c) => c + c).join('');
  if (v.length !== 6 && v.length !== 8) return null;
  return [parseInt(v.slice(0, 2), 16), parseInt(v.slice(2, 4), 16), parseInt(v.slice(4, 6), 16)];
}

export function rgbToHsl(r: number, g: number, b: number): HSL {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min, l = (max + min) / 2;
  if (!d) return { h: 0, s: 0, l };
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return { h: (h * 60 + 360) % 360, s, l };
}

export function hslToRgb({ h, s, l }: HSL): [number, number, number] {
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = l - c / 2;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
}

const smooth = (e0: number, e1: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0)));
  return t * t * (3 - 2 * t);
};

/** How much a colour belongs to the violet band: hue 252°–292° (feathered by 6°), not grey. */
export function violetWeight(c: HSL): number {
  return smooth(246, 252, c.h) * (1 - smooth(292, 298, c.h)) * smooth(0.1, 0.22, c.s);
}

/** A violet-band colour moved to the accent; others returned unchanged. */
export function mapRgb(r: number, g: number, b: number, acc: HSL): [number, number, number] {
  const c = rgbToHsl(r, g, b), w = violetWeight(c);
  if (!w) return [r, g, b];
  const l = c.l <= REF.l ? (c.l * acc.l) / REF.l : acc.l + ((c.l - REF.l) * (1 - acc.l)) / (1 - REF.l);
  const out = hslToRgb({ h: (c.h + acc.h - REF.h + 360) % 360, s: Math.min(1, (c.s * acc.s) / REF.s), l: Math.min(1, Math.max(0, l)) });
  return [Math.round(r + (out[0] - r) * w), Math.round(g + (out[1] - g) * w), Math.round(b + (out[2] - b) * w)];
}

const hex2 = (n: number) => n.toString(16).padStart(2, '0');
export const rgbHex = ([r, g, b]: [number, number, number]) => `#${hex2(r)}${hex2(g)}${hex2(b)}`;

export function isViolet(acc: HSL) {
  return Math.abs(acc.h - REF.h) < 2 && Math.abs(acc.s - REF.s) < 0.03 && Math.abs(acc.l - REF.l) < 0.02;
}

/** Every #hex and rgb()/rgba() colour in a piece of CSS or code, mapped to the accent. */
export function accentize(text: string, acc: HSL): string {
  if (isViolet(acc)) return text;
  return text
    .replace(/#([0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3})\b/gi, (m, v: string) => {
      const rgb = hexToRgb(m);
      if (!rgb) return m;
      const out = rgbHex(mapRgb(...rgb, acc));
      return v.length === 8 ? out + v.slice(6) : out;
    })
    .replace(/rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(,\s*[\d.]+\s*)?\)/gi, (_m, r, g, b, a) => {
      const [R, G, B] = mapRgb(Number(r), Number(g), Number(b), acc);
      return a ? `rgba(${R}, ${G}, ${B}${a})` : `rgb(${R}, ${G}, ${B})`;
    });
}

/** A concept spec with its colours (graph data, animation code) moved to the accent. */
export function accentSpec(spec: ConceptSpec, acc: HSL): ConceptSpec {
  if (isViolet(acc)) return spec;
  if (spec.type === 'graph') return { ...spec, data_json: accentize(spec.data_json, acc) };
  if (spec.type === '2d-anim') return { ...spec, setup_code: accentize(spec.setup_code, acc) };
  return spec;
}

/* ------------------------------------------------------------------ store */

type Listener = () => void;
const listeners = new Set<Listener>();
let current = rgbToHsl(...hexToRgb(VIOLET)!);
let currentHex = VIOLET;
let settled = current;
let timer = 0;

export const getAccent = () => current;
/** The accent after it has stopped changing for a moment: for what is costly to redraw. */
export const getSettledAccent = () => settled;
export const getAccentHex = () => currentHex;
export function subscribeAccent(fn: Listener) { listeners.add(fn); return () => { listeners.delete(fn); }; }

export function setAccent(hex: string) {
  const rgb = hexToRgb(hex);
  if (!rgb) return;
  const next = rgbToHsl(...rgb);
  if (rgbHex(rgb) === currentHex) return;
  currentHex = rgbHex(rgb);
  current = next;
  listeners.forEach((f) => f());
  clearTimeout(timer);
  timer = window.setTimeout(() => { settled = current; listeners.forEach((f) => f()); }, 250);
}

/** Follow the host page: its PMAccent, its pm:accent events, or ?accent= in the URL. */
export function followHost() {
  const w = window as unknown as { PMAccent?: { get?: () => { hex?: string } | null } };
  const initial = w.PMAccent?.get?.()?.hex ?? new URLSearchParams(location.search).get('accent');
  if (initial) { setAccent(initial.startsWith('#') ? initial : `#${initial}`); settled = current; }
  document.addEventListener('pm:accent', (e) => {
    const hex = (e as CustomEvent<{ hex?: string }>).detail?.hex;
    if (hex) setAccent(hex);
  });
}

/** The settled accent in React, and a key that changes with it (to redraw canvases). */
export function useSettledAccent(): [HSL, string] {
  const acc = useSyncExternalStore(subscribeAccent, getSettledAccent);
  return [acc, `${acc.h.toFixed(1)}/${acc.s.toFixed(3)}/${acc.l.toFixed(3)}`];
}
