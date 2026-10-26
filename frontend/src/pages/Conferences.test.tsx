import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "../api/client";
import type { ConfArea, ConfCatalog, ConfOverview, ConfSearch, ConfSearchTopic, ConfTopic } from "../types";
import Conferences from "./Conferences";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    listConferences: vi.fn(),
    getConference: vi.fn(),
    getConferenceStatus: vi.fn(),
    buildConference: vi.fn(),
    conferenceTopic: vi.fn(),
    searchConferences: vi.fn(),
    searchConferencesTopic: vi.fn(),
  };
});

const AREAS: ConfArea[] = [
  { index: 0, name: "Robotics & embodied AI", short: "Robotics", color: "#90be6d", count: 2 },
  { index: 1, name: "Reinforcement learning", short: "RL", color: "#e9c46a", count: 1 },
];

const CATALOG: ConfCatalog = {
  areas: AREAS.map(({ name, short, color }) => ({ name, short, color })),
  defaults: ["corl2025"],
  conferences: [
    { key: "corl2025", name: "CoRL 2025", series: "CoRL", slug: "corl", field: "Robotics", year: 2025, source: "papercopilot", state: "ready", message: "", papers: 3, institutions: 3 },
    { key: "corl2024", name: "CoRL 2024", series: "CoRL", slug: "corl", field: "Robotics", year: 2024, source: "papercopilot", state: "none", message: "" },
  ],
};

const OVERVIEW: ConfOverview = {
  key: "corl2025", name: "CoRL 2025", series: "CoRL", year: 2025, field: "Robotics", source: "papercopilot",
  source_url: "https://example.org", fetched_at: "2026-10-25T00:00:00+00:00", partial: false, expected: 3,
  papers: 3, institutions: 3, with_institution: 3, with_industry: 1, areas_ready: true,
  decisions: [{ label: "Poster", count: 3 }], areas: AREAS,
  top_academia: [{ name: "MIT", slug: "mit", sector: "A", papers: 2, rank: 1 }],
  top_industry: [{ name: "NVIDIA", slug: "nvidia", sector: "I", papers: 1, rank: 3 }],
  status: { key: "corl2025", name: "CoRL 2025", state: "ready" },
};

const TOPIC: ConfTopic = {
  query: "legged robots", mode: "semantic", k: 3, total: 3, with_industry: 1, areas: AREAS,
  academia: [{ name: "MIT", slug: "mit", sector: "A", papers: 2, rank: 1, count: 2, of_own: 1 }],
  industry: [{ name: "NVIDIA", slug: "nvidia", sector: "I", papers: 1, rank: 3, count: 1, of_own: 1 }],
  papers: [{
    id: "p2", title: "Legged locomotion with reinforcement learning", area: 1, decision: "Oral", track: "", session: "",
    url: "https://example.org/p2", forum: "", institutions: [{ name: "MIT", slug: "mit", sector: "A" }],
    more_institutions: 0, authors: 1, match: 0.81, library_id: null,
  }],
};

const CONF = { key: "corl2025", name: "CoRL 2025", series: "CoRL", slug: "corl", field: "Robotics", year: 2025, papers: 3 };
const SPAPER = {
  ...TOPIC.papers[0], conf_key: "corl2025", conf_name: "CoRL 2025", conf_year: 2025,
};

const SEARCH: ConfSearch = {
  query: "Charlotte Deane", kind: "all", suggested: "author", conferences: [CONF], ms: 12,
  papers: { query: "Charlotte Deane", title: [], title_total: 0, semantic: [SPAPER], semantic_ready: true, conferences: [CONF] },
  authors: {
    query: "Charlotte Deane", total: 1, authors: [{
      name: "Charlotte Deane", folded: "charlotte deane", score: 100, papers: 1, conference_count: 1, coauthors: 3,
      institutions: [{ name: "University of Oxford", sector: "A", papers: 1 }], identities: [], more_papers: 0,
      conferences: [{ ...CONF, papers_by_author: [{ ...SPAPER, title: "Antibody docking with diffusion", author_institutions: ["University of Oxford"], author_position: 2 }] }],
    }],
  },
};

const STOPIC: ConfSearchTopic = {
  query: "legged robots", k: 2, threshold: 0.71, total: 3,
  conferences: [{ ...CONF, count: 2, per_1k: 666.67, best: 0.8, top: [SPAPER] }],
  skipped: [], trend: [{ series: "CoRL", slug: "corl", points: [
    { year: 2024, key: "corl2024", count: 1, per_1k: 4.2, papers: 240 },
    { year: 2025, key: "corl2025", count: 2, per_1k: 666.67, papers: 3 },
  ] }],
  areas: AREAS, with_industry: 1, with_institution: 2,
  academia: [{ name: "MIT", sector: "A", count: 2, papers: 2, of_own: 1, conferences: [{ key: "corl2025", count: 2, slug: "mit" }] }],
  industry: [],
  papers: [SPAPER],
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/conferences" element={<Conferences />} />
        <Route path="/conferences/:key" element={<Conferences />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Conferences", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.listConferences).mockResolvedValue(CATALOG);
    vi.mocked(client.getConference).mockResolvedValue(OVERVIEW);
    vi.mocked(client.conferenceTopic).mockResolvedValue(TOPIC);
    vi.mocked(client.buildConference).mockResolvedValue({ key: "corl2024", name: "CoRL 2024", state: "queued" });
    vi.mocked(client.searchConferences).mockResolvedValue(SEARCH);
    vi.mocked(client.searchConferencesTopic).mockResolvedValue(STOPIC);
  });

  it("lists conference-years and loads a missing one on click", async () => {
    const user = userEvent.setup();
    renderAt("/conferences");
    await user.click(await screen.findByRole("button", { name: /^2024/ }));
    expect(client.buildConference).toHaveBeenCalledWith("corl2024");
  });

  it("shows the overview with top institutions", async () => {
    renderAt("/conferences/corl2025");
    expect(await screen.findByRole("heading", { name: "CoRL 2025" })).toBeInTheDocument();
    expect(screen.getByText("MIT")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA")).toBeInTheDocument();
  });

  it("answers a topic query from the URL", async () => {
    renderAt("/conferences/corl2025?view=topics&q=legged%20robots");
    await waitFor(() => expect(client.conferenceTopic).toHaveBeenCalledWith("corl2025", "legged robots", 100));
    expect(await screen.findByText("Legged locomotion with reinforcement learning")).toBeInTheDocument();
    expect(screen.getByText(/Who publishes on/)).toBeInTheDocument();
  });

  it("searches all conferences from the URL and opens the suggested author tab", async () => {
    renderAt("/conferences?q=Charlotte%20Deane");
    await waitFor(() => expect(client.searchConferences).toHaveBeenCalledWith(
      "Charlotte Deane", { kind: "all", series: "", field: "", year_min: null, year_max: null },
    ));
    expect(await screen.findByRole("heading", { name: "Charlotte Deane" })).toBeInTheDocument();
    expect(screen.getByText("Antibody docking with diffusion")).toBeInTheDocument();
    expect(screen.getByText(/Author 2, at University of Oxford/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Authors/ })).toHaveAttribute("aria-selected", "true");
    expect(client.searchConferencesTopic).not.toHaveBeenCalled();
  });

  it("shows where a topic is published across conferences", async () => {
    renderAt("/conferences?q=legged%20robots&kind=topic");
    await waitFor(() => expect(client.searchConferencesTopic).toHaveBeenCalledWith(
      "legged robots", { k: 300, series: "", field: "", year_min: null, year_max: null },
    ));
    expect(await screen.findByText(/is published/)).toBeInTheDocument();
    expect(screen.getByText("2 · 666.7 per 1,000")).toBeInTheDocument();
    expect(screen.getByText("Universities & institutes, all conferences")).toBeInTheDocument();
    expect(screen.getByText("Legged locomotion with reinforcement learning")).toBeInTheDocument();
  });

  it("searches while typing", async () => {
    const user = userEvent.setup();
    renderAt("/conferences");
    const box = await screen.findByRole("textbox", { name: "Search all conferences" });
    await user.type(box, "flow matching");
    await waitFor(() => expect(client.searchConferences).toHaveBeenCalledWith("flow matching", expect.objectContaining({ kind: "all" })));
    expect(client.searchConferences).toHaveBeenCalledTimes(1);   // debounced: one request for the whole word
  });
});
