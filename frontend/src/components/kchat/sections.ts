/**
 * Split an answer at `## ` headings outside fenced code blocks.
 *
 * Mirrors `split_sections` in backend/services/chat_concepts.py: section 0 is
 * the text before the first heading (possibly empty), every later section
 * starts with its heading line. Concept cards are stored with the index of the
 * section they explain and render at its end, so both sides must agree.
 */
const FENCE = /^\s{0,3}(`{3,}|~{3,})/;
const HEADING = /^##\s/;

export function splitSections(text: string): string[] {
  const sections: string[] = [];
  let lines: string[] = [];
  let fence: string | null = null;
  for (const line of text.split("\n")) {
    const m = FENCE.exec(line);
    if (m) {
      const mark = m[1];
      if (fence === null) fence = mark;
      else if (mark[0] === fence[0] && mark.length >= fence.length && !line.trim().slice(mark.length).trim()) fence = null;
    } else if (fence === null && HEADING.test(line)) {
      sections.push(lines.join("\n"));
      lines = [];
    }
    lines.push(line);
  }
  sections.push(lines.join("\n"));
  return sections;
}

/** Library papers cited in an answer as `[title](/paper/<id>)`, in order of first mention. */
export const PAPER_LINK = /^\/paper\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/?$/i;

export function citedPapers(text: string): { id: string; title: string }[] {
  const out = new Map<string, string>();
  const re = /\[([^\]\n]+)\]\((\/paper\/[0-9a-f-]{36})\/?\)/gi;
  for (const m of text.matchAll(re)) {
    const id = PAPER_LINK.exec(m[2])?.[1];
    if (id && !out.has(id)) out.set(id, m[1].replace(/[*_`]/g, "").trim());
  }
  return [...out].map(([id, title]) => ({ id, title }));
}
