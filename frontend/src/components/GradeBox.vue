<template>
  <div class="grade-box" v-if="answerId">
    <p class="hint">模型分 {{ llmLabel }} <span v-if="part.admin_touched">· 只作参考，不会改你已手改的分数</span></p>
    <p class="field-label">管理员分</p>
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
    <p class="hint">改这里才是最终分。可以直接改数字，按钮按半分开降。</p>
    <input v-model="part.comment" placeholder="评语（可空）" />
    <p class="hint" v-if="part.llm_comment">模型评语：{{ part.llm_comment }}</p>
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
const llmLabel = computed(() => {
  const n = props.part.llm_score ?? props.part.raw_score;
  if (n === null || n === undefined || n === "") return "—";
  return `${n} / ${props.part.max_score}`;
});

const scoreText = computed({
  get() {
    const n = props.part.admin_score ?? props.part.score;
    if (n === null || n === undefined || n === "") return "";
    return String(n);
  },
  set(value: string) {
    props.part.score = value;
    props.part.admin_score = value;
  },
});

function parseScore(raw: unknown) {
  const n = Number(String(raw ?? "").replace("，", ".").trim());
  return Number.isFinite(n) ? n : 0;
}

function clampScore() {
  const max = Number(props.part.max_score || 0);
  let n = parseScore(props.part.admin_score ?? props.part.score);
  n = Math.min(max, Math.max(0, Math.round(n * 100) / 100));
  props.part.score = n;
  props.part.admin_score = n;
}

function nudge(delta: number) {
  const max = Number(props.part.max_score || 0);
  const n = Math.round((parseScore(props.part.admin_score ?? props.part.score) + delta) * 2) / 2;
  const next = Math.min(max, Math.max(0, n));
  props.part.score = next;
  props.part.admin_score = next;
}

function applyLlm(row: {
  status?: string;
  llm_score?: number | null;
  llm_comment?: string | null;
  comment?: string | null;
  admin_score?: number | null;
  admin_touched?: boolean;
}) {
  if ("llm_score" in row) props.part.llm_score = row.llm_score;
  if ("llm_comment" in row) props.part.llm_comment = row.llm_comment;
  if (!props.part.admin_touched && row.llm_comment) props.part.comment = row.llm_comment;
  if (row.admin_touched || props.part.admin_touched) {
    if (row.admin_score !== undefined) props.part.admin_score = row.admin_score;
  } else if (row.llm_score !== undefined) {
    props.part.score = row.llm_score;
  }
  if (row.status) {
    props.part.status = row.status;
    props.part.status_label = { pending: "待评分", graded: "已评分", overridden: "已改判" }[row.status] || row.status;
  }
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function save() {
  error.value = "";
  clampScore();
  await api("/api/parent/grade", {
    method: "POST",
    body: JSON.stringify({
      answer_id: answerId.value,
      score: parseScore(props.part.admin_score ?? props.part.score),
      comment: props.part.comment || "",
    }),
  });
  props.part.status = "overridden";
  props.part.status_label = "已改判";
  props.part.admin_touched = true;
  note.value = "已改判。";
  emit("saved");
}

async function regrade() {
  error.value = "";
  const kept = props.part.admin_touched;
  if (!kept) {
    props.part.comment = "";
    props.part.score = null;
  }
  props.part.llm_comment = "";
  props.part.llm_score = null;
  if (!kept) {
    props.part.status = "pending";
    props.part.status_label = "待评分";
  }
  note.value = "正在交给模型…";
  try {
    await api("/api/parent/grade", {
      method: "POST",
      body: JSON.stringify({ answer_id: answerId.value, regrade: true }),
    });
    note.value = kept ? "模型还在评，评完只更新模型分，不会改你的分数。" : "模型还在评，分数和评语稍后出现。";
    const id = answerId.value;
    for (let i = 0; i < 60; i++) {
      await wait(2000);
      const row = (await api(`/api/parent/answers/${id}`)) as {
        status?: string;
        llm_score?: number | null;
        llm_comment?: string | null;
        comment?: string | null;
        admin_score?: number | null;
        admin_touched?: boolean;
      };
      applyLlm(row);
      const fail = String(row.llm_comment || row.comment || "").startsWith("模型这次没评上");
      const done = row.llm_score != null || fail;
      if (done) {
        if (fail) {
          error.value = row.llm_comment || row.comment || "模型这次没给出分数和评语。";
          note.value = "";
        } else {
          note.value = kept ? "模型已评好，可作参考。" : row.llm_comment ? "模型已评好，评语已写入。" : "模型已评好。";
        }
        emit("saved");
        return;
      }
    }
    error.value = "模型还没给出分数和评语，可以手改或再点一次。";
    emit("saved");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "再评失败";
    note.value = "";
  }
}
</script>
