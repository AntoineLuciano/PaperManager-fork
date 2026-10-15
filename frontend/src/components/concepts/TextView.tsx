// Adapted from Get It. (github.com/beltromatti/get-it, Apache-2.0); see NOTICE.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { TextSpec } from "../../types";

function host(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

export default function TextView({ spec }: { spec: TextSpec }) {
  return (
    <div className="space-y-3">
      <article className="prose prose-sm max-w-none text-gray-700">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{spec.body_markdown}</ReactMarkdown>
      </article>
      {spec.citations.length > 0 && (
        <ol className="border-t border-gray-100 pt-2 space-y-1.5 text-xs">
          {spec.citations.map((c, i) => (
            <li key={i} className="flex gap-2">
              <span className="font-mono text-violet-500">[{i + 1}]</span>
              <span className="min-w-0">
                <span className="text-gray-800">{c.label}</span>
                <span className="text-gray-400"> · {c.source}</span>
                {host(c.url) && (
                  <a href={c.url} target="_blank" rel="noopener noreferrer"
                     className="block text-violet-600 hover:underline truncate">{host(c.url)}</a>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
