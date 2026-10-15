import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../../api/client";
import type { Concept } from "../../types";
import ConceptsPanel from "./ConceptsPanel";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, detectConcepts: vi.fn(), generateConceptViz: vi.fn(), repairConceptViz: vi.fn() };
});

// jsdom has no ResizeObserver or canvas
globalThis.ResizeObserver = class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
HTMLCanvasElement.prototype.getContext = () => null;

const concept = (over: Partial<Concept>): Concept => ({
  id: "c1", page: 0, position: 0, label: "EDM loss", type: "formula", anchor: "the EDM loss",
  anchor_found: true, context: "The EDM training loss.", spec: null, spec_error: null, ...over,
});

const FORMULA = { type: "formula" as const, title: "EDM loss", caption: "Weighted denoising loss.", main_latex: "L", steps: [] };
const BAD_GRAPH = { type: "graph" as const, title: "Schedule", caption: "", chart_type: "lines" as const,
  x_label: "t", y_label: "σ", data_json: "{broken" };

function Harness({ initial, onActivate = () => {} }: { initial: Concept[]; onActivate?: (c: Concept | null) => void }) {
  const [concepts, setConcepts] = useState(initial);
  const [activeId, setActiveId] = useState<string | null>(null);
  return (
    <ConceptsPanel
      paperId="p1" hasPdf concepts={concepts} backend="claude-code" onConceptsChange={setConcepts}
      activeId={activeId} onActivate={(c) => { setActiveId(c?.id ?? null); onActivate(c); }}
    />
  );
}

describe("ConceptsPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists concepts by page and names the model", () => {
    render(<Harness initial={[concept({}), concept({ id: "c2", page: 4, label: "PF ODE", type: "2d-anim" })]} />);
    expect(screen.getByText("Page 1")).toBeInTheDocument();
    expect(screen.getByText("Page 5")).toBeInTheDocument();
    expect(screen.getByText("anim")).toBeInTheDocument();
    expect(screen.getByText(/Claude Code · Sonnet/)).toBeInTheDocument();
  });

  it("scans the PDF when asked", async () => {
    vi.mocked(client.detectConcepts).mockResolvedValue({
      concepts: [concept({})], backend: "claude-code", pages_total: 120, pages_scanned: 80,
    });
    render(<Harness initial={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Find concepts" }));
    expect(await screen.findByText("EDM loss")).toBeInTheDocument();
    expect(screen.getByText("Scanned the first 80 of 120 pages.")).toBeInTheDocument();
  });

  it("generates a visualisation the first time a concept is opened", async () => {
    vi.mocked(client.generateConceptViz).mockResolvedValue(concept({ spec: FORMULA }));
    const onActivate = vi.fn();
    render(<Harness initial={[concept({})]} onActivate={onActivate} />);
    await userEvent.click(screen.getByText("EDM loss"));
    expect(onActivate).toHaveBeenCalledWith(expect.objectContaining({ id: "c1", page: 0 }));
    expect(await screen.findByText("Weighted denoising loss.")).toBeInTheDocument();
    expect(client.generateConceptViz).toHaveBeenCalledWith("p1", "c1");
  });

  it("does not regenerate a concept that already has a spec", async () => {
    render(<Harness initial={[concept({ spec: FORMULA })]} />);
    await userEvent.click(screen.getByText("EDM loss"));
    expect(await screen.findByText("Weighted denoising loss.")).toBeInTheDocument();
    expect(client.generateConceptViz).not.toHaveBeenCalled();
  });

  it("repairs a visualisation that fails to render, then gives up", async () => {
    // Every repair returns another broken graph.
    vi.mocked(client.repairConceptViz).mockImplementation(async () =>
      concept({ type: "graph", spec: { ...BAD_GRAPH, data_json: `{broken ${Math.random()}` } }),
    );
    render(<Harness initial={[concept({ type: "graph", label: "Schedule", spec: BAD_GRAPH })]} />);
    await userEvent.click(screen.getByText("Schedule"));
    await waitFor(() => expect(screen.getByText(/gave up after 2 repair attempts/)).toBeInTheDocument());
    expect(client.repairConceptViz).toHaveBeenCalledTimes(2);
    expect(vi.mocked(client.repairConceptViz).mock.calls[0][2]).toMatch(/Could not parse graph data_json/);
  });
});
