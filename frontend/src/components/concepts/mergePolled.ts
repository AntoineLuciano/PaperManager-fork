import type { Concept } from "../../types";

/**
 * Take newly finished visualisations from a poll without replacing concepts
 * that did not change: a new object would restart a running animation.
 */
export function mergePolled(prev: Concept[], next: Concept[]): Concept[] {
  const byId = new Map(next.map((c) => [c.id, c]));
  if (prev.length !== next.length || prev.some((c) => !byId.has(c.id))) return next;
  return prev.map((c) => {
    const n = byId.get(c.id)!;
    return !c.spec && (n.spec || n.spec_error !== c.spec_error) ? n : c;
  });
}
