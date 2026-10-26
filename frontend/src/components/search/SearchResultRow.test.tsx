import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { SearchResult } from "../../types";
import Highlight from "./Highlight";
import SearchResultRow from "./SearchResultRow";
import { matchChips, splitMarks } from "./searchUtils";

const HIT: SearchResult = {
  id: "edm",
  title: "Elucidating the Design Space of Diffusion-Based Generative Models",
  year: 2022,
  created_at: "2026-01-01",
  venue: "NeurIPS",
  score: 9.1,
  matched_in: "note+paper",
  matched_fields: ["title", "author", "note", "fulltext", "semantic"],
  matches: { author: ["Tero Karras"] },
  title_marks: [[32, 41]],
  authors: ["Tero Karras", "Miika Aittala", "Timo Aila", "Samuli Laine"],
  similarity: 0.781,
  snippets: [
    { field: "note", text: "The EDM preconditioning is what AF3 uses", marks: [[4, 7]] },
    { field: "highlight", text: "noise levels follow a log-normal", marks: [[0, 5]], page: 4 },
  ],
};

function renderRow(hit: SearchResult = HIT) {
  return render(
    <MemoryRouter>
      <ul><SearchResultRow hit={hit} /></ul>
    </MemoryRouter>,
  );
}

describe("splitMarks / Highlight", () => {
  it("splits text into marked and plain runs", () => {
    expect(splitMarks("flow matching works", [[0, 4], [5, 13]])).toEqual([
      { text: "flow", marked: true },
      { text: " ", marked: false },
      { text: "matching", marked: true },
      { text: " works", marked: false },
    ]);
  });

  it("clips, sorts and merges malformed ranges instead of throwing", () => {
    expect(splitMarks("abc", [[2, 99], [-5, 1], [1, 1]])).toEqual([
      { text: "a", marked: true },
      { text: "b", marked: false },
      { text: "c", marked: true },
    ]);
    expect(splitMarks("abc", [[0, 2], [1, 3]])).toEqual([{ text: "ab", marked: true }, { text: "c", marked: true }]);
  });

  it("counts offsets in code points, so astral characters do not shift marks", () => {
    // "𝑥" is one code point but two UTF-16 units; Python offsets count it once.
    expect(splitMarks("𝑥 score", [[2, 7]])).toEqual([
      { text: "𝑥 ", marked: false },
      { text: "score", marked: true },
    ]);
  });

  it("renders marks as <mark> elements and markup as text", () => {
    const { container } = render(<Highlight text="<b>bold</b> EDM" marks={[[12, 15]]} />);
    expect(container.querySelector("mark")?.textContent).toBe("EDM");
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toBe("<b>bold</b> EDM");
  });
});

describe("SearchResultRow", () => {
  it("shows why the paper matched", () => {
    renderRow();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/paper/edm");
    expect(screen.getByText("Diffusion").tagName).toBe("MARK");
    expect(screen.getByText("Tero Karras, Miika Aittala, Timo Aila et al.")).toBeInTheDocument();
    expect(screen.getByText("Author: Tero Karras")).toBeInTheDocument();
    expect(screen.getAllByText("Your note")).toHaveLength(2); // chip and snippet label
    expect(screen.getByText("Full text")).toBeInTheDocument();
    expect(screen.getByText("Meaning 0.78")).toBeInTheDocument();
    expect(screen.getByText("EDM").tagName).toBe("MARK");
    expect(screen.getByText("Highlight · p. 4")).toBeInTheDocument();
  });

  it("hides a venue stored as the string null", () => {
    renderRow({ ...HIT, venue: "null" });
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("labels reference stubs", () => {
    renderRow({ ...HIT, is_reference: true, snippets: [], matched_fields: ["title"] });
    expect(screen.getByText("Reference")).toBeInTheDocument();
  });

  it("builds chip labels with entity names", () => {
    const chips = matchChips({ ...HIT, matches: { topic: ["A", "B", "C"] }, matched_fields: ["topic"] });
    expect(chips).toEqual([{ field: "topic", label: "Topic: A, B +1" }]);
  });
});
