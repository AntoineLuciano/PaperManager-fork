import { describe, expect, it } from "vitest";
import { findAnchorAreas, type TextItemLike } from "./anchors";

// A 200 x 100 page; PDF y grows upwards, viewport y downwards.
const W = 200;
const H = 100;
const flip = ([x1, y1, x2, y2]: [number, number, number, number]) => [x1, H - y1, x2, H - y2];

const line = (str: string, x: number, y: number, width: number): TextItemLike => ({
  str, transform: [10, 0, 0, 10, x, y], width, height: 10,
});

const items = [
  line("We train the denoiser with", 0, 80, 100),
  line("the EDM   loss over noise levels.", 0, 60, 120),
];

describe("findAnchorAreas", () => {
  it("returns a percent box per line the anchor touches", () => {
    const areas = findAnchorAreas(items, W, H, flip, 3, "denoiser with the EDM loss");
    expect(areas).toHaveLength(2);
    expect(areas.every((a) => a.pageIndex === 3)).toBe(true);
    // Second line: "the EDM loss" is the first 12 of its 31 collapsed characters.
    const second = areas[1];
    expect(second.left).toBeCloseTo(0);
    expect(second.width).toBeCloseTo(((12 / 31) * 120 / W) * 100);
    expect(second.top).toBeCloseTo(30); // (H - (60 + 10)) / H
    expect(second.height).toBeCloseTo(10);
  });

  it("ignores case and whitespace differences", () => {
    expect(findAnchorAreas(items, W, H, flip, 0, "THE EDM\nLOSS OVER")).toHaveLength(1);
  });

  it("falls back to the anchor's tail when the head differs", () => {
    const anchor = "garbled-extraction-prefix-that-pdfjs-never-saw the EDM loss over noise levels";
    expect(findAnchorAreas(items, W, H, flip, 0, anchor)).toHaveLength(1);
  });

  it("returns nothing for an absent or too short anchor", () => {
    expect(findAnchorAreas(items, W, H, flip, 0, "completely different sentence here")).toEqual([]);
    expect(findAnchorAreas(items, W, H, flip, 0, "EDM")).toEqual([]);
  });
});
