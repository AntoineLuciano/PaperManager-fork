/**
 * Locate a concept's anchor string in a PDF page's text layer and return
 * highlight areas in the percent coordinates @react-pdf-viewer/highlight uses.
 *
 * The anchor was copied by the model from pypdf's extraction, pdf.js splits
 * text differently, so matching is whitespace- and case-insensitive and falls
 * back to the anchor's tail and head when the full string is not found.
 */
import type { HighlightArea } from "@react-pdf-viewer/highlight";

/** The fields of a pdf.js TextItem this module reads. */
export interface TextItemLike {
  str: string;
  transform: number[];
  width: number;
  height: number;
}

/** Maps a PDF-space rectangle [x1, y1, x2, y2] to viewport pixels at scale 1. */
export type ToViewportRect = (rect: [number, number, number, number]) => number[];

const collapse = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();

interface Span {
  item: number;
  start: number;
  end: number;
}

function buildIndex(items: TextItemLike[]): { text: string; spans: Span[] } {
  let text = "";
  const spans: Span[] = [];
  items.forEach((it, i) => {
    const piece = collapse(it.str);
    if (!piece) return;
    if (text) text += " ";
    spans.push({ item: i, start: text.length, end: text.length + piece.length });
    text += piece;
  });
  return { text, spans };
}

function locate(text: string, anchor: string): [number, number] | null {
  const needle = collapse(anchor);
  if (needle.length < 8) return null;
  const candidates = [needle, needle.slice(-40), needle.slice(0, 40), needle.slice(-24), needle.slice(0, 24)];
  for (const c of candidates) {
    if (c.length < 12 && c !== needle) continue;
    const at = text.indexOf(c);
    if (at >= 0) return [at, at + c.length];
  }
  return null;
}

export function findAnchorAreas(
  items: TextItemLike[],
  viewportWidth: number,
  viewportHeight: number,
  toViewportRect: ToViewportRect,
  pageIndex: number,
  anchor: string,
): HighlightArea[] {
  const { text, spans } = buildIndex(items);
  const hit = locate(text, anchor);
  if (!hit) return [];
  const [from, to] = hit;
  const areas: HighlightArea[] = [];
  for (const span of spans) {
    if (span.end <= from || span.start >= to) continue;
    const it = items[span.item];
    const len = span.end - span.start;
    // Characters are taken as equally wide, so a partial line is trimmed proportionally.
    const f0 = (Math.max(from, span.start) - span.start) / len;
    const f1 = (Math.min(to, span.end) - span.start) / len;
    const x = it.transform[4];
    const y = it.transform[5];
    const h = it.height || Math.abs(it.transform[3]);
    const [ax, ay, bx, by] = toViewportRect([x + f0 * it.width, y, x + f1 * it.width, y + h]);
    const left = Math.min(ax, bx);
    const top = Math.min(ay, by);
    areas.push({
      pageIndex,
      left: (left / viewportWidth) * 100,
      top: (top / viewportHeight) * 100,
      width: (Math.abs(bx - ax) / viewportWidth) * 100,
      height: (Math.abs(by - ay) / viewportHeight) * 100,
    });
  }
  return areas;
}
