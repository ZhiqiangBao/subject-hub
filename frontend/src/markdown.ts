import { marked } from "marked";
import markedKatex from "marked-katex-extension";

marked.use(
  markedKatex({
    throwOnError: false,
    nonStandard: true,
  }),
);

export function renderMd(md: string): string {
  return marked.parse(md || "", { async: false }) as string;
}
