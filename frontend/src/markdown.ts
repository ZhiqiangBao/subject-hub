import DOMPurify from "dompurify";
import { marked } from "marked";
import markedKatex from "marked-katex-extension";

marked.use(markedKatex({ throwOnError: false, nonStandard: true }));

export function renderMd(md: string): string {
  return DOMPurify.sanitize(marked.parse(md || "", { async: false }) as string);
}
