import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Conversation } from "../../types";
import { ConversationList } from "./ConversationList";

const conv = (id: string, title: string, extra: Partial<Conversation> = {}): Conversation => ({
  id, title, created_at: "2026-10-20T10:00:00Z", updated_at: "2026-10-20T10:00:00Z", compacted: false, message_count: 4, ...extra,
});
const LIST = [
  conv("a", "Diffusion models"),
  conv("b", "Diffusion models", { parent_id: "a", fork_at: 1, fork_kind: "strand", branch_label: "What about flow matching?" }),
  conv("c", "Protein design", { compacted: true }),
];

function setup(list = LIST, current: string | null = null) {
  const props = { onPick: vi.fn(), onNew: vi.fn(), onRename: vi.fn(), onDelete: vi.fn() };
  render(<ConversationList conversations={list} current={current} {...props} />);
  return props;
}

describe("ConversationList", () => {
  it("lists conversations with forks nested under their parent, labelled by their question", () => {
    setup();
    const strand = screen.getByText("What about flow matching?").closest(".kc-row")!;
    expect(strand).toHaveClass("branch");
    expect(strand.closest(".kc-kids")).not.toBeNull();
    expect(within(strand as HTMLElement).getByText(/strand · after 1/)).toBeInTheDocument();
    expect(screen.getByText(/compacted/)).toBeInTheDocument();
    expect(screen.getAllByText(/2 q/).length).toBeGreaterThan(0);
  });

  it("marks the open conversation and opens one on click", () => {
    const p = setup(LIST, "c");
    expect(screen.getByText("Protein design").closest(".kc-row")).toHaveClass("current");
    fireEvent.click(screen.getByText("Diffusion models"));
    expect(p.onPick).toHaveBeenCalledWith(LIST[0]);
  });

  it("starts a new conversation", () => {
    const p = setup();
    fireEvent.click(screen.getByText("+ New"));
    expect(p.onNew).toHaveBeenCalled();
  });

  it("searches titles and fork questions, keeping a matching fork's parent", () => {
    setup();
    fireEvent.change(screen.getByLabelText("Search conversations"), { target: { value: "flow" } });
    expect(screen.getByText("What about flow matching?")).toBeInTheDocument();
    expect(screen.getByText("Diffusion models")).toBeInTheDocument();
    expect(screen.queryByText("Protein design")).toBeNull();
    fireEvent.change(screen.getByLabelText("Search conversations"), { target: { value: "zzz" } });
    expect(screen.getByText("No conversation matches.")).toBeInTheDocument();
  });

  it("renames on Enter and cancels on Escape", () => {
    const p = setup();
    const row = screen.getByText("Protein design").closest(".kc-row") as HTMLElement;
    fireEvent.click(within(row).getByText("rename"));
    const input = screen.getByLabelText("Conversation title");
    fireEvent.change(input, { target: { value: "Binder design" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(p.onRename).toHaveBeenCalledWith(LIST[2], "Binder design");

    fireEvent.click(within(row).getByText("rename"));
    fireEvent.change(screen.getByLabelText("Conversation title"), { target: { value: "Nope" } });
    fireEvent.keyDown(screen.getByLabelText("Conversation title"), { key: "Escape" });
    expect(p.onRename).toHaveBeenCalledTimes(1);
    expect(p.onPick).not.toHaveBeenCalled();
  });

  it("deletes only after confirming", () => {
    const p = setup();
    const row = screen.getByText("Protein design").closest(".kc-row") as HTMLElement;
    fireEvent.click(within(row).getByTitle("Delete this conversation"));
    fireEvent.click(within(row).getByText("keep"));
    expect(p.onDelete).not.toHaveBeenCalled();
    fireEvent.click(within(row).getByTitle("Delete this conversation"));
    fireEvent.click(within(row).getByText("delete"));
    expect(p.onDelete).toHaveBeenCalledWith(LIST[2]);
  });

  it("shows a fork whose parent was deleted as a top-level row", () => {
    setup([conv("b", "x", { parent_id: "gone", branch_label: "Orphan" })]);
    expect(screen.getByText("Orphan").closest(".kc-kids")).toBeNull();
  });

  it("says when there are no conversations", () => {
    setup([]);
    expect(screen.getByText("No conversations yet.")).toBeInTheDocument();
  });
});
