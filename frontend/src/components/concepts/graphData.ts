// Adapted from Get It. (github.com/beltromatti/get-it, Apache-2.0); see NOTICE.
/** Parse a graph spec's data_json into drawable data. Data only: nothing is evaluated. */
import type { GraphSpec } from "../../types";

export const COLORS = ["#7c3aed", "#0284c7", "#d97706", "#059669", "#e11d48", "#5b66f1"];

type Pt = [number, number];
export type GraphData =
  | { kind: "series"; series: { name: string; color: string; points: Pt[] }[] }
  | { kind: "bars"; bars: { label: string; value: number }[] };

const isPt = (p: unknown): p is Pt =>
  Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]);

/** Parse data_json into drawable data; throws a readable error on bad shapes. Data only, never code. */
export function parseGraphData(spec: GraphSpec): GraphData {
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(spec.data_json);
  } catch (e) {
    throw new Error(`Could not parse graph data_json: ${(e as Error).message}`);
  }
  if (spec.chart_type === "bars") {
    const bars = Array.isArray(data.bars) ? data.bars : [];
    const clean = bars
      .filter((b): b is { label: unknown; value: number } => !!b && Number.isFinite((b as { value: unknown }).value))
      .map((b) => ({ label: String(b.label ?? ""), value: b.value }));
    if (!clean.length) throw new Error("Bar chart has no bars");
    return { kind: "bars", bars: clean };
  }
  const raw =
    spec.chart_type === "points"
      ? [{ name: spec.title, points: data.points }]
      : Array.isArray(data.series) ? data.series : [];
  const series = (raw as { name?: unknown; color?: unknown; points?: unknown }[]).map((s, i) => ({
    name: String(s.name ?? ""),
    color: typeof s.color === "string" && /^#[0-9a-f]{3,8}$/i.test(s.color) ? s.color : COLORS[i % COLORS.length],
    points: (Array.isArray(s.points) ? s.points : []).filter(isPt),
  })).filter((s) => s.points.length);
  if (!series.length) throw new Error("Chart has no data points");
  return { kind: "series", series };
}
