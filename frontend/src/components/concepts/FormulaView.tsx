// Adapted from Get It. (github.com/beltromatti/get-it, Apache-2.0); see NOTICE.
import { useEffect, useRef } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import type { FormulaSpec } from "../../types";

function Tex({ tex, display = true }: { tex: string; display?: boolean }) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    try {
      katex.render(tex, ref.current, { throwOnError: false, displayMode: display, strict: "ignore" });
    } catch {
      ref.current.textContent = tex;
    }
  }, [tex, display]);
  return <span ref={ref} />;
}

export default function FormulaView({ spec }: { spec: FormulaSpec }) {
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 overflow-x-auto">
        <Tex tex={spec.main_latex} />
      </div>
      <ol className="space-y-2">
        {spec.steps.map((s, i) => (
          <li key={i} className="rounded-lg border border-gray-100 px-3 py-2">
            <p className="text-[11px] text-gray-500 flex gap-2">
              <span className="font-mono text-violet-500">{i + 1}</span>
              <span>{s.explanation}</span>
            </p>
            <div className="overflow-x-auto text-sm">
              <Tex tex={s.latex} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
