import type { ConfArea } from "../../types";

const pct = (x: number, d = 0) => `${(x * 100).toFixed(d)}%`;

/**
 * Stacked bar of research areas with a legend of the largest ones. With `compare`, a thin
 * second bar shows the whole conference's mix underneath, and the legend marks areas the
 * first bar over-represents (twice the conference share or more).
 */
export default function AreaBar({
  areas,
  caption,
  compare,
  legend = 8,
  onPick,
  height = "h-3.5",
}: {
  areas: ConfArea[];
  caption?: string;
  compare?: ConfArea[];
  legend?: number;
  onPick?: (area: ConfArea) => void;
  height?: string;
}) {
  const total = areas.reduce((a, b) => a + b.count, 0) || 1;
  const shown = areas.filter((a) => a.count > 0);
  const bySize = [...shown].sort((a, b) => b.count - a.count);
  const cmpTotal = compare ? compare.reduce((a, b) => a + b.count, 0) || 1 : 1;
  const cmpShare = (i: number) => (compare ? compare[i].count / cmpTotal : 0);

  if (!shown.length) return <p className="text-xs text-ink-3">Research areas appear once the conference is indexed.</p>;

  return (
    <div className="space-y-2">
      {caption && <div className="text-[11px] font-medium text-ink-3 uppercase tracking-wide">{caption}</div>}
      <div className={`flex ${height} w-full overflow-hidden rounded-full bg-line-s`} role="img" aria-label={caption ?? "Research areas"}>
        {shown.map((a) => (
          <div
            key={a.index}
            title={`${a.name}: ${a.count} (${pct(a.count / total)})`}
            style={{ flex: a.count, background: a.color }}
            className={onPick ? "cursor-pointer hover:opacity-80" : ""}
            onClick={onPick ? () => onPick(a) : undefined}
          />
        ))}
      </div>
      {compare && (
        <div className="flex h-1.5 w-full overflow-hidden rounded-full opacity-60" title="Whole conference">
          {compare.filter((a) => a.count > 0).map((a) => (
            <div key={a.index} style={{ flex: a.count, background: a.color }} title={`Conference · ${a.name}: ${pct(a.count / cmpTotal, 1)}`} />
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-2">
        {bySize.slice(0, legend).map((a) => {
          const share = a.count / total;
          const over = compare && cmpShare(a.index) > 0 && share >= 2 * cmpShare(a.index) && a.count >= 3;
          return (
            <button
              key={a.index}
              type="button"
              onClick={onPick ? () => onPick(a) : undefined}
              title={`${a.name}: ${a.count}${compare ? ` · conference ${pct(cmpShare(a.index), 1)}` : ""}`}
              className={`inline-flex items-center gap-1.5 ${onPick ? "hover:text-accent" : "cursor-default"}`}
            >
              <i className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: a.color }} />
              <b className="font-semibold text-ink">{a.short}</b>
              <span>{share > 0 && share < 0.01 ? "<1%" : pct(share)}</span>
              {over && <span className="text-[10px] font-semibold text-accent">×{(share / cmpShare(a.index)).toFixed(1)}</span>}
            </button>
          );
        })}
        {bySize.length > legend && <span className="text-ink-3">+{bySize.length - legend} more</span>}
      </div>
    </div>
  );
}
