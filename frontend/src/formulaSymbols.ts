export type FormulaAction =
  | { kind: "text"; label: string; insert: string }
  | { kind: "wrap"; label: string; before: string; after: string };

export const FORMULA_SUBJECTS = new Set(["math", "physics", "chemistry", "biology"]);

export function usesFormulaBar(subject?: string | null) {
  return Boolean(subject && FORMULA_SUBJECTS.has(subject));
}

const MATH_COMMON: FormulaAction[] = [
  { kind: "wrap", label: "√()", before: "√(", after: ")" },
  { kind: "wrap", label: "∫()dx", before: "∫(", after: ")dx" },
  { kind: "wrap", label: "分数", before: "(", after: ")/()" },
  { kind: "text", label: "²", insert: "²" },
  { kind: "text", label: "³", insert: "³" },
  { kind: "text", label: "π", insert: "π" },
  { kind: "text", label: "±", insert: "±" },
  { kind: "text", label: "×", insert: "×" },
  { kind: "text", label: "÷", insert: "÷" },
  { kind: "text", label: "≠", insert: "≠" },
  { kind: "text", label: "≤", insert: "≤" },
  { kind: "text", label: "≥", insert: "≥" },
  { kind: "text", label: "∞", insert: "∞" },
  { kind: "text", label: "°", insert: "°" },
];

const CHEM_COMMON: FormulaAction[] = [
  { kind: "text", label: "⇌", insert: "⇌" },
  { kind: "text", label: "→", insert: "→" },
  { kind: "text", label: "⟶", insert: "⟶" },
  { kind: "text", label: "↑", insert: "↑" },
  { kind: "text", label: "↓", insert: "↓" },
  { kind: "text", label: "△", insert: "△" },
  { kind: "text", label: "℃", insert: "℃" },
  { kind: "text", label: "⁺", insert: "⁺" },
  { kind: "text", label: "⁻", insert: "⁻" },
];

const MATH: FormulaAction[] = [
  { kind: "wrap", label: "√()", before: "√(", after: ")" },
  { kind: "wrap", label: "∫()dx", before: "∫(", after: ")dx" },
  { kind: "wrap", label: "∑()", before: "∑(", after: ")" },
  { kind: "wrap", label: "分数", before: "(", after: ")/()" },
  { kind: "text", label: "∂", insert: "∂" },
  { kind: "text", label: "′", insert: "′" },
  { kind: "text", label: "″", insert: "″" },
  { kind: "text", label: "∏", insert: "∏" },
  { kind: "text", label: "∠", insert: "∠" },
  { kind: "text", label: "⊥", insert: "⊥" },
  { kind: "text", label: "∥", insert: "∥" },
  { kind: "text", label: "∽", insert: "∽" },
  { kind: "text", label: "≅", insert: "≅" },
  { kind: "text", label: "∈", insert: "∈" },
  { kind: "text", label: "∉", insert: "∉" },
  { kind: "text", label: "∪", insert: "∪" },
  { kind: "text", label: "∩", insert: "∩" },
  { kind: "text", label: "∅", insert: "∅" },
  { kind: "text", label: "≈", insert: "≈" },
  { kind: "text", label: "∴", insert: "∴" },
  { kind: "text", label: "∵", insert: "∵" },
];

const CHEM: FormulaAction[] = [
  { kind: "text", label: "⇌", insert: "⇌" },
  { kind: "text", label: "→", insert: "→" },
  { kind: "text", label: "⟶", insert: "⟶" },
  { kind: "text", label: "↑", insert: "↑" },
  { kind: "text", label: "↓", insert: "↓" },
  { kind: "text", label: "△", insert: "△" },
  { kind: "text", label: "℃", insert: "℃" },
  { kind: "text", label: "⁺", insert: "⁺" },
  { kind: "text", label: "⁻", insert: "⁻" },
  { kind: "text", label: "₀", insert: "₀" },
  { kind: "text", label: "₁", insert: "₁" },
  { kind: "text", label: "₂", insert: "₂" },
  { kind: "text", label: "₃", insert: "₃" },
  { kind: "text", label: "₄", insert: "₄" },
  { kind: "text", label: "₅", insert: "₅" },
  { kind: "text", label: "₆", insert: "₆" },
  { kind: "text", label: "₇", insert: "₇" },
  { kind: "text", label: "₈", insert: "₈" },
  { kind: "text", label: "₉", insert: "₉" },
];

const GREEK: FormulaAction[] = [
  { kind: "text", label: "π", insert: "π" },
  { kind: "text", label: "α", insert: "α" },
  { kind: "text", label: "β", insert: "β" },
  { kind: "text", label: "γ", insert: "γ" },
  { kind: "text", label: "θ", insert: "θ" },
  { kind: "text", label: "λ", insert: "λ" },
  { kind: "text", label: "μ", insert: "μ" },
  { kind: "text", label: "ω", insert: "ω" },
  { kind: "text", label: "Δ", insert: "Δ" },
  { kind: "text", label: "σ", insert: "σ" },
  { kind: "text", label: "φ", insert: "φ" },
];

export function formulaTabsFor(subject?: string | null): { id: string; name: string; items: FormulaAction[] }[] {
  if (subject === "chemistry") {
    return [
      { id: "common", name: "常用", items: CHEM_COMMON },
      { id: "chem", name: "化学", items: CHEM },
      { id: "greek", name: "希腊", items: GREEK },
    ];
  }
  if (subject === "biology") {
    return [
      { id: "common", name: "常用", items: [...CHEM_COMMON, { kind: "wrap", label: "√()", before: "√(", after: ")" }] },
      { id: "chem", name: "化学", items: CHEM },
      { id: "greek", name: "希腊", items: GREEK },
    ];
  }
  if (subject === "physics" || subject === "math") {
    return [
      { id: "common", name: "常用", items: MATH_COMMON },
      { id: "math", name: "数学", items: MATH },
      { id: "greek", name: "希腊", items: GREEK },
    ];
  }
  return [];
}
