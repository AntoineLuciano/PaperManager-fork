import { splitMarks } from "./searchUtils";

/**
 * Text with matched ranges wrapped in <mark>. The ranges come from the search API as
 * [start, end) offsets in code points; the text is rendered as React text nodes, never as HTML.
 */
export default function Highlight({ text, marks, className }: {
  text: string;
  marks?: [number, number][];
  className?: string;
}) {
  const parts = splitMarks(text, marks ?? []);
  return (
    <span className={className}>
      {parts.map((p, i) =>
        p.marked
          ? <mark key={i} className="bg-amber-100 text-ink rounded-sm px-0.5">{p.text}</mark>
          : <span key={i}>{p.text}</span>,
      )}
    </span>
  );
}
