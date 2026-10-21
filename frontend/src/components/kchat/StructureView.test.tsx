import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StructureView } from "./structure/StructureView";

/* A stand-in for 3Dmol.js: records what the card asks of the viewer. */
type Atom = Record<string, unknown>;
function fake3Dmol() {
  const atoms: Atom[] = [
    { x: 0, y: 0, z: 0, chain: "A", resi: 319, resn: "ARG", atom: "CA", elem: "C", hetflag: false, b: 92, serial: 1 },
    { x: 1, y: 0, z: 0, chain: "A", resi: 320, resn: "VAL", atom: "CA", elem: "C", hetflag: false, b: 45, serial: 2 },
    { x: 2, y: 1, z: 0, chain: "B", resi: 10, resn: "GLY", atom: "CA", elem: "C", hetflag: false, b: 70, serial: 3 },
  ];
  const viewer = {
    hover: null as null | ((a: Atom) => void),
    addModel: vi.fn(() => ({ selectedAtoms: () => atoms })),
    setStyle: vi.fn(), addStyle: vi.fn(), addSurface: vi.fn(), removeAllSurfaces: vi.fn(), removeAllLabels: vi.fn(),
    addLabel: vi.fn(), zoomTo: vi.fn(), render: vi.fn(), resize: vi.fn(), clear: vi.fn(), spin: vi.fn(),
    setHoverable: vi.fn((_s: unknown, _on: boolean, enter: (a: Atom) => void) => { viewer.hover = enter; }),
    setHoverDuration: vi.fn(), setClickable: vi.fn(), pngURI: vi.fn(() => "data:image/png;base64,AAAA"),
  };
  return { lib: { createViewer: vi.fn(() => viewer) }, viewer };
}

let mol: ReturnType<typeof fake3Dmol>;
beforeEach(() => {
  mol = fake3Dmol();
  (window as unknown as { $3Dmol: unknown }).$3Dmol = mol.lib;
  globalThis.ResizeObserver ??= class { observe() {} disconnect() {} unobserve() {} } as unknown as typeof ResizeObserver;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url.includes("9ZZZ")) return new Response(JSON.stringify({ detail: "RCSB has no entry 9ZZZ" }), { status: 404 });
    return new Response(JSON.stringify({ name: url.includes("afdb") ? "AF-P69905" : "6VXX", format: "cif", data: "data_x" }));
  }));
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("StructureView (3Dmol mocked)", () => {
  it("loads coordinates through the backend proxy and draws the model", async () => {
    render(<StructureView spec={{ title: "Spike", models: [{ pdb: "6VXX" }], caption: "Look at the RBD." }} />);
    await waitFor(() => expect(mol.viewer.addModel).toHaveBeenCalledWith("data_x", "cif"));
    const url = (fetch as unknown as { mock: { calls: string[][] } }).mock.calls[0][0];
    expect(url).toMatch(/\/knowledge-chat\/structures\?pdb=6VXX$/);
    expect(screen.getByText("Spike")).toBeInTheDocument();
    expect(screen.getByText("Look at the RBD.")).toBeInTheDocument();
    expect(mol.viewer.zoomTo).toHaveBeenCalled();
    expect(await screen.findByTitle("RCSB entry")).toHaveAttribute("href", "https://www.rcsb.org/structure/6VXX");
  });

  it("lists highlights as chips, zooms to one and toggles it", async () => {
    render(<StructureView spec={{ models: [{ pdb: "6VXX" }], highlights: [{ label: "RBD", chain: "A", resi: "319-541", color: "warm" }] }} />);
    const chip = await screen.findByText("RBD");
    mol.viewer.zoomTo.mockClear();
    fireEvent.click(chip);
    expect(mol.viewer.zoomTo).toHaveBeenCalledWith({ dvis: true, dhl: 0 }, 500);
    const box = chip.closest(".structure-chip")!.querySelector("input")!;
    fireEvent.click(box);
    expect(chip.closest(".structure-chip")).toHaveClass("off");
  });

  it("spins, adds a surface, saves a PNG", async () => {
    render(<StructureView spec={{ models: [{ pdb: "6VXX" }] }} />);
    await screen.findByTitle("RCSB entry");
    fireEvent.click(screen.getByText("spin"));
    expect(mol.viewer.spin).toHaveBeenLastCalledWith("y", 0.6);
    fireEvent.click(screen.getByText("surface"));
    expect(mol.viewer.addSurface).toHaveBeenCalled();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByText("png"));
    expect(mol.viewer.pngURI).toHaveBeenCalled();
    expect(click).toHaveBeenCalled();
  });

  it("names the residue under the pointer", async () => {
    render(<StructureView spec={{ models: [{ pdb: "6VXX", label: "spike" }] }} />);
    await screen.findByTitle("RCSB entry");
    act(() => mol.viewer.hover!({ chain: "A", resn: "ARG", resi: 319, atom: "CA", b: 92, dm: 0 }));
    expect(screen.getByText(/spike · A ARG 319 · CA/)).toBeInTheDocument();
  });

  it("shows a pLDDT legend for AlphaFold models", async () => {
    render(<StructureView spec={{ models: [{ afdb: "P69905", color: "plddt" }] }} />);
    expect(await screen.findByText("pLDDT")).toBeInTheDocument();
    expect(screen.getByTitle("AlphaFold DB entry")).toHaveAttribute("href", "https://alphafold.ebi.ac.uk/entry/P69905");
  });

  it("shows the proxy's error instead of a viewer", async () => {
    render(<StructureView spec={{ models: [{ pdb: "9ZZZ" }] }} />);
    expect(await screen.findByText("RCSB has no entry 9ZZZ")).toBeInTheDocument();
  });
});
