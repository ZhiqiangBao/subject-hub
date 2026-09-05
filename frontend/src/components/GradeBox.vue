<template>
  <div class="grade-box" v-if="answerId">
    <p class="field-label">分数</p>
    <div class="choice-edit">
      <button class="btn" type="button" @click="nudge(-0.5)">少 0.5</button>
      <input
        v-model="scoreText"
        inputmode="decimal"
        placeholder="分数"
        @change="clampScore"
      />
      <span class="hint" style="margin:0;white-space:nowrap">/ {{ part.max_score }}</span>
      <button class="btn" type="button" @click="nudge(0.5)">多 0.5</button>
    </div>
    <p class="hint">可以直接改框里的数字。按钮按半分开降。</p>
    <input v-model="part.comment" placeholder="评语（可空）" />
    <div class="chips">
      <button class="btn primary" type="button" @click="save">记下这个分数</button>
      <button class="btn ghost" type="button" @click="regrade">用模型再评一次</button>
    </div>
    <p class="hint" v-if="note">{{ note }}</p>
    <p class="err" v-if="error">{{ error }}</p>
  </div>
  <p v-else class="hint">学生还没交这问，交了才能改判。</p>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { api } from "../api";

const props = defineProps<{ part: any }>();
const emit = defineEmits<{ saved: [] }>();
const note = ref("");
const error = ref("");
const answerId = computed(() => props.part.answer_id || props.part.id);

const scoreText = computed({
  get() {
    const n = props.part.score;
    if (n === null || n === undefined || n === "") return "";
    return String(n);
  },
  set(value: string) {
    props.part.score = value;
  },
});

function parseScore(raw: unknown) {
  const n = Number(String(raw ?? "").replace("，", ".").trim());
  return Number.isFinite(n) ? n : 0;
}

function clampScore() {
  const max = Number(props.part.max_score || 0);
  let n = parseScore(props.part.score);
  n = Math.min(max, Math.max(0, Math.round(n * 100) / 100));
  props.part.score = n;
}

function nudge(delta: number) {
  const max = Number(props.part.max_score || 0);
  const n = Math.round((parseScore(props.part.score) + delta) * 2) / 2;
  props.part.score = Math.min(max, Math.max(0, n));
}

async function save() {
  error.value = "";
  clampScore();
  await api("/api/parent/grade", {
    method: "POST",
    body: JSON.stringify({
      answer_id: answerId.value,
      score: parseScore(props.part.score),
      comment: props.part.comment || "",
    }),
  });
  props.part.status = "overridden";
  props.part.status_label = "已改判";
  note.value = "已改判。";
  emit("saved");
}

async function regrade() {
  error.value = "";
  note.value = "正在交给模型…";
  await api("/api/parent/grade", {
    method: "POST",
    body: JSON.stringify({ answer_id: answerId.value, score: 0, regrade: true }),
  });
  note.value = "已交给模型再评。";
  emit("saved");
}
</script>
