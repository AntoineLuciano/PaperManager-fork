import { describe, expect, it } from "vitest";
import { citedPapers, splitSections } from "./sections";

describe("splitSections (mirrors backend split_sections)", () => {
  it("keeps the preamble and starts each section with its heading", () => {
    expect(splitSections("Intro line.\n\n## First\nBody one.\n## Second\nBody two.")).toEqual([
      "Intro line.\n", "## First\nBody one.", "## Second\nBody two.",
    ]);
  });

  it("ignores headings inside fenced code", () => {
    const s = splitSections("## A\n```python\n## not a heading\n```\ntext\n## B\nend");
    expect(s).toHaveLength(3);
    expect(s[1]).toContain("## not a heading");
  });

  it("does not split at ### or without a space", () => {
    expect(splitSections("Prose\n### Small\n##Tight")).toHaveLength(1);
  });

  it("closes a long fence only on a matching fence", () => {
    expect(splitSections("````md\n```\n## inside\n```\n````\n## Out\nx")).toHaveLength(2);
  });

  it("joins back to the original text", () => {
    const text = "a\n## b\nc\n```\n## d\n```\n## e";
    expect(splitSections(text).join("\n")).toBe(text);
  });
});

describe("citedPapers", () => {
  const id = "c7d9ec3d-0df1-4c18-970f-7f6dc34e5e3e";
  it("collects /paper/<id> links once, with their titles", () => {
    const text = `See [**RFdiffusion**](/paper/${id}) and again [it](/paper/${id}); [web](https://x.org).`;
    expect(citedPapers(text)).toEqual([{ id, title: "RFdiffusion" }]);
  });
});
