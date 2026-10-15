import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AnimView from "./AnimView";
import { buildSandboxDoc, SANDBOX_ATTR, SANDBOX_CSP } from "./sandbox";

describe("animation sandbox", () => {
  it("never grants same-origin, top navigation or popups", () => {
    expect(SANDBOX_ATTR).toBe("allow-scripts");
  });

  it("blocks network access in the iframe document", () => {
    expect(SANDBOX_CSP).toContain("default-src 'none'");
    expect(SANDBOX_CSP).not.toMatch(/connect-src|img-src|https?:/);
    expect(buildSandboxDoc()).toContain(`content="${SANDBOX_CSP}"`);
  });

  it("renders the iframe sandboxed, without the model's code in its HTML", () => {
    const code = "return { draw: function () { /* MARKER */ } };";
    const { container } = render(
      <AnimView spec={{ type: "2d-anim", title: "Sampler", caption: "", setup_code: code }} />,
    );
    const frame = container.querySelector("iframe")!;
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("srcdoc")).not.toContain("MARKER");
  });
});
