import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import { SettingsProvider } from "../contexts/SettingsContext";
import type { SearchResponse } from "../types";
import Library from "./Library";
import { buildSearchParams } from "../components/search/searchUtils";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, apiFetch: vi.fn(), searchLibrary: vi.fn(), searchSuggest: vi.fn() };
});

const RESPONSE: SearchResponse = {
  results: [
    { id: "a", title: "Flow Matching for Generative Modeling", created_at: "2026-01-01", year: 2023, score: 9, matched_in: "paper",
      matched_fields: ["title"], title_marks: [[0, 4], [5, 13]], snippets: [], authors: ["Yaron Lipman"] },
    { id: "b", title: "Zeta paper", created_at: "2026-02-01", year: 2019, score: 3, matched_in: "note",
      matched_fields: ["note"], snippets: [{ field: "note", text: "compare flow matching", marks: [[8, 12]] }] },
  ],
  total: 2,
  mode: "hybrid",
  relaxed: false,
  took_ms: 42,
};

function renderAt(url: string) {
  return render(
    <SettingsProvider>
      <MemoryRouter initialEntries={[url]}>
        <Library />
      </MemoryRouter>
    </SettingsProvider>,
  );
}

describe("buildSearchParams", () => {
  it("adds ranking options and paging for a query", () => {
    const p = buildSearchParams(new URLSearchParams("q=diffusion&tag=x&mode=semantic&refs=1&sort=year_desc"), 3, 20);
    expect(Object.fromEntries(p)).toEqual({
      q: "diffusion", tag: "x", mode: "semantic", sort: "year_desc", include_references: "true",
      skip: "40", limit: "20",
    });
  });

  it("defaults to hybrid relevance without references, and lists all for filters only", () => {
    const p = buildSearchParams(new URLSearchParams("q=edm"), 1, 0);
    expect(p.get("mode")).toBe("hybrid");
    expect(p.get("sort")).toBe("relevance");
    expect(p.get("include_references")).toBe("false");
    expect(p.get("limit")).toBe("200");
    const f = buildSearchParams(new URLSearchParams("topic=Diffusion%20Models&sort=year_desc"), 1, 20);
    expect(Object.fromEntries(f)).toEqual({ topic: "Diffusion Models", include_references: "false", limit: "2000" });
  });
});

describe("Library search", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.apiFetch).mockImplementation(async (path: string) => {
      if (path === "/projects") return [];
      if (path === "/stats") return null;
      if (path === "/papers") return [];
      return null;
    });
    vi.mocked(client.searchLibrary).mockResolvedValue(RESPONSE);
  });

  it("runs the query from the URL and keeps the server's relevance order", async () => {
    renderAt("/?q=flow%20matching");
    await waitFor(() => expect(screen.getAllByTestId("search-hit")).toHaveLength(2));
    const params = vi.mocked(client.searchLibrary).mock.calls[0][0];
    expect(params.get("q")).toBe("flow matching");
    expect(params.get("mode")).toBe("hybrid");
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    // "Zeta paper" stays second although a title sort would put "Flow…" first anyway and
    // a year sort would not: the client does not re-sort ranked hits.
    expect(titles).toEqual(["Flow Matching for Generative Modeling", "Zeta paper"]);
    expect(screen.getAllByText("Your note").length).toBeGreaterThan(0);
    expect(screen.getByPlaceholderText(/Search titles/)).toHaveValue("flow matching");
    expect(screen.getByLabelText("Sort results")).toHaveValue("relevance");
  });

  it("shows an empty state with ways out", async () => {
    vi.mocked(client.searchLibrary).mockResolvedValue({ ...RESPONSE, results: [], total: 0 });
    renderAt("/?q=xyzzy&tag=foo");
    await waitFor(() => expect(screen.getByText(/No papers match “xyzzy” with these filters/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Search cited references too" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Search by meaning" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove filters" })).toBeInTheDocument();
  });

  it("says when meaning search is still indexing", async () => {
    vi.mocked(client.searchLibrary).mockResolvedValue({
      ...RESPONSE, mode: "lexical",
      semantic: { state: "building", done: 100, todo: 8000, indexed: 100, papers: 8000, enabled: true, model_loaded: true },
    });
    renderAt("/?q=diffusion");
    await waitFor(() => expect(screen.getByText(/still indexing \(100 \/ 8000 papers\)/)).toBeInTheDocument());
  });
});
