// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { renderMd } from "../src/markdown";

describe("Markdown safety", () => {
  it("removes executable HTML and unsafe URLs while preserving math", () => {
    const html = renderMd('<img src=x onerror="alert(1)"><script>alert(2)</script> [bad](javascript:alert(3)) $x^2$');
    expect(html).not.toMatch(/onerror|<script|javascript:/i);
    expect(html).toContain('katex');
    expect(html).toContain('x');
  });
});
