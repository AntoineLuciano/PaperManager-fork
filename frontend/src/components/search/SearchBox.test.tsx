import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../../api/client";
import type { SearchSuggestions } from "../../types";
import SearchBox, { type PickedSuggestion } from "./SearchBox";
import { suggestionItems } from "./searchUtils";

vi.mock("../../api/client", () => ({
  searchSuggest: vi.fn(),
}));

const SUGGESTIONS: SearchSuggestions = {
  query: "kar",
  papers: [{ id: "p1", title: "Elucidating the Design Space", year: 2022 }],
  authors: [{ id: "a1", name: "Tero Karras", papers: 3 }],
  topics: [{ id: "t1", name: "Diffusion Models", papers: 40 }],
  tags: [],
  projects: [],
};

function Harness({ onCommit, onPick }: { onCommit: (v: string) => void; onPick: (s: PickedSuggestion) => void }) {
  const [value, setValue] = useState("");
  return <SearchBox value={value} onChange={setValue} onCommit={onCommit} onPick={onPick} debounceMs={300} suggestDelayMs={100} />;
}

function setup() {
  const onCommit = vi.fn();
  const onPick = vi.fn();
  render(<Harness onCommit={onCommit} onPick={onPick} />);
  const input = screen.getByRole("combobox");
  return { onCommit, onPick, input };
}

describe("SearchBox", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(client.searchSuggest).mockResolvedValue(SUGGESTIONS);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("commits the query once, debounced, after typing stops", async () => {
    const { onCommit, input } = setup();
    fireEvent.change(input, { target: { value: "d" } });
    fireEvent.change(input, { target: { value: "di" } });
    fireEvent.change(input, { target: { value: "dif" } });
    expect(onCommit).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(310); });
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith("dif");
  });

  it("Enter without a highlighted suggestion commits immediately", async () => {
    const { onCommit, input } = setup();
    fireEvent.change(input, { target: { value: "flow matching" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommit).toHaveBeenCalledWith("flow matching");
    await act(async () => { vi.advanceTimersByTime(400); });
    expect(onCommit).toHaveBeenCalledTimes(1); // the pending debounce was cancelled
  });

  it("shows grouped suggestions and picks one with the keyboard", async () => {
    const { onPick, onCommit, input } = setup();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "kar" } });
    await act(async () => { vi.advanceTimersByTime(120); });
    await waitFor(() => expect(screen.getByRole("listbox")).toBeInTheDocument());
    expect(client.searchSuggest).toHaveBeenCalledWith("kar", 5, expect.any(AbortSignal));
    expect(screen.getByText("Authors")).toBeInTheDocument();
    expect(screen.getByText("Tero Karras")).toBeInTheDocument();
    expect(screen.getByText("3 papers")).toBeInTheDocument();

    fireEvent.keyDown(input, { key: "ArrowDown" }); // paper
    fireEvent.keyDown(input, { key: "ArrowDown" }); // author
    expect(screen.getByRole("option", { name: /Tero Karras/ })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onPick).toHaveBeenCalledWith({ kind: "author", id: "a1", name: "Tero Karras" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await act(async () => { vi.advanceTimersByTime(400); });
    expect(onCommit).not.toHaveBeenCalled(); // picking cancels the debounced commit
  });

  it("picks with the mouse and closes on Escape", async () => {
    const { onPick, input } = setup();
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "kar" } });
    await act(async () => { vi.advanceTimersByTime(120); });
    await waitFor(() => expect(screen.getByRole("listbox")).toBeInTheDocument());
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.mouseDown(screen.getByText("Diffusion Models"));
    expect(onPick).toHaveBeenCalledWith({ kind: "topic", id: "t1", name: "Diffusion Models" });
  });

  it("does not ask for suggestions below two characters", async () => {
    const { input } = setup();
    fireEvent.change(input, { target: { value: "k" } });
    await act(async () => { vi.advanceTimersByTime(200); });
    expect(client.searchSuggest).not.toHaveBeenCalled();
  });

  it("flattens suggestions in display order", () => {
    expect(suggestionItems(SUGGESTIONS).map((i) => i.kind)).toEqual(["paper", "author", "topic"]);
    expect(suggestionItems(null)).toEqual([]);
  });
});
