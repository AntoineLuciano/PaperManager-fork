import { describe, expect, it } from "vitest";
import type { GraphSpec } from "../../types";
import { parseGraphData } from "./graphData";

const spec = (chart_type: GraphSpec["chart_type"], data: unknown): GraphSpec => ({
  type: "graph", title: "T", caption: "", chart_type, x_label: "t", y_label: "σ",
  data_json: typeof data === "string" ? data : JSON.stringify(data),
});

describe("parseGraphData", () => {
  it("reads line series and keeps only finite points", () => {
    const d = parseGraphData(spec("lines", { series: [{ name: "σ(t)", color: "#123456", points: [[0, 1], [1, "x"], [2, 3]] }] }));
    expect(d).toEqual({ kind: "series", series: [{ name: "σ(t)", color: "#123456", points: [[0, 1], [2, 3]] }] });
  });

  it("replaces a non-hex colour with the palette", () => {
    const d = parseGraphData(spec("lines", { series: [{ name: "a", color: "url(javascript:1)", points: [[0, 1]] }] }));
    expect(d.kind === "series" && d.series[0].color).toBe("#7c3aed");
  });

  it("reads points and bars", () => {
    expect(parseGraphData(spec("points", { points: [[1, 2]] })).kind).toBe("series");
    expect(parseGraphData(spec("bars", { bars: [{ label: "A", value: 2 }] }))).toEqual({
      kind: "bars", bars: [{ label: "A", value: 2 }],
    });
  });

  it("throws readable errors for bad data", () => {
    expect(() => parseGraphData(spec("lines", "{nope"))).toThrow(/Could not parse/);
    expect(() => parseGraphData(spec("lines", { series: [] }))).toThrow(/no data points/);
    expect(() => parseGraphData(spec("bars", { bars: [{ label: "A" }] }))).toThrow(/no bars/);
  });

  it("never evaluates an expression", () => {
    // The old Get It. "function" shape carried JS; here it is just missing data.
    expect(() => parseGraphData(spec("lines", { fn: "alert(1)" }))).toThrow(/no data points/);
  });
});
