<template>
  <div class="part-edit">
    <p v-if="showStem" class="field-label">这一问</p>
    <textarea v-if="showStem" v-model="part.stem" placeholder="这一问问什么"></textarea>
    <p class="hint">{{ typeHint }}</p>

    <template v-if="part.type === 'single' || part.type === 'multiple'">
      <div class="choice-edit" v-for="(c, i) in part.choices" :key="c.id">
        <button class="choice" :class="{ on: isPicked(c.id) }" type="button" @click="toggleCorrect(c.id)">{{ c.id }}</button>
        <input v-model="c.text" :placeholder="'选项 ' + c.id" />
        <button class="btn ghost" type="button" @click="removeChoice(i)">去掉</button>
      </div>
      <button class="btn" type="button" @click="addChoice">再加一个选项</button>
    </template>

    <template v-else-if="part.type === 'blank'">
      <div class="blank-form" v-for="(_form, i) in blankForms" :key="i">
        <FormulaField v-if="showFormula" v-model="blankForms[i]" :subject="subject" placeholder="一种正确写法" />
        <input v-else v-model="blankForms[i]" placeholder="一种正确写法" autocomplete="off" autocapitalize="off" autocorrect="off" :spellcheck="false" />
        <button class="btn ghost" type="button" @click="removeBlank(i)">去掉</button>
      </div>
      <button class="choice add-form" type="button" @click="addBlank">＋ 再加一种写法</button>
    </template>

    <template v-else-if="part.type === 'numeric'">
      <p class="field-label">得数</p>
      <input v-model="part.answer" placeholder="数字答案" />
      <p class="field-label">容差（可空）</p>
      <input v-model="part.tolerance" placeholder="例如 0.01" />
      <p class="field-label">单位（可空）</p>
      <input v-model="part.unit" placeholder="例如 cm" />
    </template>

    <template v-else-if="part.type === 'short' || part.type === 'essay'">
      <p class="field-label">参考答案</p>
      <textarea v-model="part.reference" placeholder="给学生评的时候看的参考"></textarea>
      <p class="field-label">评分细则</p>
      <div class="card" v-for="(row, i) in part.rubric" :key="row.id || i" style="margin-bottom:10px">
        <textarea v-model="row.require" placeholder="这一条要学生做到什么"></textarea>
        <p class="field-label">这一条满分</p>
        <input v-model.number="row.points" type="number" min="0" step="0.5" />
        <button class="btn ghost" type="button" @click="removeRubric(i)">去掉这条</button>
      </div>
      <button class="btn" type="button" @click="addRubric">再加一条细则</button>
      <label class="photo-toggle" v-if="allowPhotoToggle">
        <input type="checkbox" v-model="part.allow_photo" />
        允许拍演算纸
      </label>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import FormulaField from "./FormulaField.vue";
import { usesFormulaBar } from "../formulaSymbols";

const part = defineModel<any>({ required: true });
const props = defineProps<{ showStem?: boolean; allowPhotoToggle?: boolean; subject?: string }>();
const showFormula = computed(() => usesFormulaBar(props.subject));

const typeHint = computed(() => {
  const t = part.value?.type;
  if (t === "single") return "点选项字母设为正确答案。只能选一个。";
  if (t === "multiple") return "点选项字母设为正确答案。可以点多个。";
  if (t === "blank") {
    return showFormula.value
      ? "学生填任意一种写法都给满分。用下面的符号按钮，不要写 LaTeX。"
      : "学生填任意一种写法都给满分。每种写法一个框，可改字，也可再加。";
  }
  if (t === "numeric") return "只判最终得数，允许一点误差。";
  if (t === "short" || t === "essay") return "细则和参考答案与题目一样可以改。";
  return "";
});

const blankForms = computed({
  get(): string[] {
    const ans = part.value?.answer;
    if (Array.isArray(ans)) return ans;
    if (ans === null || ans === undefined || String(ans).trim() === "") return [""];
    return [String(ans)];
  },
  set(value: string[]) {
    part.value.answer = value;
  },
});

function isPicked(id: string) {
  if (part.value.type === "single") return part.value.answer === id;
  const ans = part.value.answer;
  return Array.isArray(ans) && ans.includes(id);
}

function toggleCorrect(id: string) {
  if (part.value.type === "single") {
    part.value.answer = id;
    return;
  }
  const ans: string[] = Array.isArray(part.value.answer) ? [...part.value.answer] : [];
  const idx = ans.indexOf(id);
  if (idx >= 0) ans.splice(idx, 1);
  else ans.push(id);
  part.value.answer = ans;
}

function addChoice() {
  const letters = "ABCDEFGH";
  const used = new Set((part.value.choices || []).map((c: { id: string }) => c.id));
  const id = [...letters].find((L) => !used.has(L)) || String((part.value.choices || []).length + 1);
  if (!part.value.choices) part.value.choices = [];
  part.value.choices.push({ id, text: "" });
}

function removeChoice(i: number) {
  const removed = part.value.choices[i];
  part.value.choices.splice(i, 1);
  if (part.value.type === "single" && part.value.answer === removed?.id) part.value.answer = "";
  if (part.value.type === "multiple" && Array.isArray(part.value.answer)) {
    part.value.answer = part.value.answer.filter((x: string) => x !== removed?.id);
  }
}

function addBlank() {
  blankForms.value = [...blankForms.value, ""];
}

function removeBlank(i: number) {
  const next = blankForms.value.filter((_, idx) => idx !== i);
  blankForms.value = next.length ? next : [""];
}

function addRubric() {
  if (!part.value.rubric) part.value.rubric = [];
  part.value.rubric.push({ id: `r${part.value.rubric.length + 1}`, points: 1, require: "" });
}

function removeRubric(i: number) {
  part.value.rubric.splice(i, 1);
}
</script>
