/** Folded word forms to mark, as the backend returns them (search.py `_highlight`). */
export type HighlightTerms = { words: string[]; prefixes: string[] };

/** Lower case without accents, as the backend folds words (institutions.fold). */
export const foldWord = (s: string) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();

/** `text` with every word that matched the query wrapped in a <mark>. Splits into plain
 *  React text nodes and spans; never injects HTML. */
export default function Highlight({ text, terms }: { text: string; terms?: HighlightTerms | null }) {
  if (!terms || (terms.words.length === 0 && terms.prefixes.length === 0)) return <>{text}</>;
  const words = new Set(terms.words);
  // Odd indices are the words, even ones the separators between them.
  const parts = text.split(/([\p{L}\p{N}]+)/u);
  return (
    <>
      {parts.map((part, i) => {
        if (i % 2 === 1) {
          const f = foldWord(part);
          if (words.has(f) || terms.prefixes.some((p) => f.startsWith(p))) {
            return <mark key={i} className="bg-amber-100 text-inherit rounded-sm">{part}</mark>;
          }
        }
        return part;
      })}
    </>
  );
}
