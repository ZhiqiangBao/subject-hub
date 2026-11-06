<template>
  <div class="formula-field">
    <input
      ref="el"
      :value="model"
      :disabled="disabled"
      :placeholder="placeholder"
      autocomplete="off"
      autocapitalize="off"
      autocorrect="off"
      :spellcheck="false"
      @input="onInput"
    />
    <div class="chips" v-if="!disabled">
      <button class="chip" type="button" :class="{ on: tab === t.id }" v-for="t in tabs" :key="t.id" @click="tab = t.id">{{ t.name }}</button>
      <button class="chip" type="button" @click="help = true">使用帮助</button>
    </div>
    <div class="chips formula-keys" v-if="!disabled">
      <button class="chip" type="button" @click="digitsToSub">数字改成下标</button>
      <button class="chip" type="button" @click="digitsToSup">数字改成上标</button>
      <button class="chip" type="button" v-for="(item, i) in current" :key="tab + i" @click="apply(item)">{{ item.label }}</button>
    </div>
    <div class="formula-help-mask" v-if="help" @click.self="help = false">
      <div class="card formula-help">
        <h2>公式怎么填</h2>
        <p>先点框里要插入的位置，再点按钮。不要写 LaTeX。</p>
        <template v-if="subject === 'chemistry' || subject === 'biology'">
          <p><strong>化学</strong>可逆用 ⇌，反应箭头用 → 或 ⟶（长箭头）。气体 ↑，沉淀 ↓。化学式先写 H2O，再点「数字改成下标」变成 H₂O。</p>
        </template>
        <template v-else>
          <p><strong>根号</strong>点「√()」，括号里才是根下的内容。写 √(2+1)，不要写 √2+1。</p>
          <p><strong>积分</strong>点「∫()dx」，被积式写在括号里。写 ∫(x+1)dx。</p>
          <p><strong>分数</strong>点「分数」得到 ( )/()。简单的也可以直接写 1/2。</p>
        </template>
        <p>普通键盘也能输入：1/2、x^2、sqrt(2)。系统会识别常见等价写法；括号决定公式的作用范围。</p>
        <button class="btn primary" type="button" @click="help = false">知道了</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { formulaTabsFor, type FormulaAction } from "../formulaSymbols";

const model = defineModel<string>({ default: "" });
const props = defineProps<{ disabled?: boolean; placeholder?: string; subject?: string }>();
const emit = defineEmits<{ change: [] }>();

const el = ref<HTMLInputElement | null>(null);
const tab = ref("common");
const help = ref(false);
const tabs = computed(() => formulaTabsFor(props.subject));
const current = computed(() => tabs.value.find((t) => t.id === tab.value)?.items || tabs.value[0]?.items || []);

watch(
  tabs,
  (next) => {
    if (!next.some((t) => t.id === tab.value)) tab.value = next[0]?.id || "common";
  },
  { immediate: true },
);

const digitSub: Record<string, string> = {
  "0": "₀",
  "1": "₁",
  "2": "₂",
  "3": "₃",
  "4": "₄",
  "5": "₅",
  "6": "₆",
  "7": "₇",
  "8": "₈",
  "9": "₉",
};
const digitSup: Record<string, string> = {
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
};

function onInput(ev: Event) {
  model.value = (ev.target as HTMLInputElement).value;
  emit("change");
}

function put(next: string, cursor: number) {
  model.value = next;
  emit("change");
  nextTick(() => {
    el.value?.focus();
    el.value?.setSelectionRange(cursor, cursor);
  });
}

function range() {
  const node = el.value;
  const text = model.value || "";
  const start = node?.selectionStart ?? text.length;
  const end = node?.selectionEnd ?? text.length;
  return { text, start, end, sel: text.slice(start, end) };
}

function apply(item: FormulaAction) {
  const { text, start, end, sel } = range();
  if (item.kind === "text") {
    const next = text.slice(0, start) + item.insert + text.slice(end);
    put(next, start + item.insert.length);
    return;
  }
  const next = text.slice(0, start) + item.before + sel + item.after + text.slice(end);
  const cursor = sel
    ? start + item.before.length + sel.length + (item.after.startsWith(")/(") ? 3 : 0)
    : start + item.before.length;
  put(next, cursor);
}

function mapDigits(table: Record<string, string>) {
  const { text, start, end, sel } = range();
  const src = sel || text;
  const mapped = src.replace(/[0-9]/g, (d) => table[d] || d);
  if (sel) {
    const next = text.slice(0, start) + mapped + text.slice(end);
    put(next, start + mapped.length);
    return;
  }
  put(mapped, mapped.length);
}

function digitsToSub() {
  mapDigits(digitSub);
}

function digitsToSup() {
  mapDigits(digitSup);
}
</script>
