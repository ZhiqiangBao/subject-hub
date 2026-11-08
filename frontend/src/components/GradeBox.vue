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
      <button v-if="canRegrade(part)" :disabled="regrading" class="btn ghost" type="button" @click="regrade">用模型再评一次</button>
    </div>
    <p v-if="part.subjective && part.status === 'pending' && !part.job_state" class="hint">尚未开始模型评分。请检查模型配置，或直接手动评分。</p>
    <p class="hint" v-if="note">{{ note }}</p>
    <p class="err" v-if="error">{{ error }}</p>
  </div>
  <p v-else class="hint">学生还没交这问，交了才能改判。</p>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";
import { canRegrade } from "../gradingPermissions";

const props = defineProps<{ part: any }>();
const emit = defineEmits<{ saved: [] }>();
const note = ref("");
const error = ref("");
const regrading = ref(false);
let stopped = false;
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
  job_state?: string | null;
}) {
  if ("job_state" in row) props.part.job_state = row.job_state;
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
  try {
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
  } catch (err) { error.value = err instanceof Error ? err.message : "改判失败"; }
}

type GradeResult = {
  status?: string;
  job_state?: string | null;
  llm_score?: number | null;
  llm_comment?: string | null;
  comment?: string | null;
  admin_score?: number | null;
  admin_touched?: boolean;
};

async function pollJob(id: number) {
  for (let i = 0; i < 60 && !stopped; i++) {
    await wait(2000);
    if (stopped) return;
    const row = await api(`/api/parent/answers/${id}/grade-job`) as GradeResult;
    if (stopped) return;
    applyLlm(row);
    if (row.job_state === "done") {
      note.value = "模型已评好，参考分已更新。";
      emit("saved");
      return;
    }
    if (row.job_state === "cancelled") {
      note.value = "评分任务已取消，请刷新查看当前状态。";
      emit("saved");
      return;
    }
    if (row.job_state === "failed") {
      note.value = "";
      error.value = row.llm_comment || "模型评分失败，请检查模型配置或手动评分。";
      emit("saved");
      return;
    }
  }
  if (!stopped) note.value = "模型仍在评分，请稍后刷新查看；也可以手动评分。";
}

async function trackJob(id: number) {
  if (regrading.value) return;
  regrading.value = true;
  try { await pollJob(id); }
  catch (err) { if (!stopped) error.value = err instanceof Error ? err.message : "读取评分状态失败，请稍后刷新查看。"; }
  finally { regrading.value = false; }
}

async function regrade() {
  if (regrading.value || !canRegrade(props.part)) return;
  error.value = "";
  note.value = "正在交给模型…";
  regrading.value = true;
  try {
    const result = await api("/api/parent/grade", {
      method: "POST",
      body: JSON.stringify({ answer_id: answerId.value, regrade: true }),
    }) as GradeResult;
    if (stopped) return;
    applyLlm(result);
    note.value = "模型任务正在等待或评分；如长时间等待，请检查模型配置，也可以手动评分。已有人工分仍是最终分。";
    await pollJob(answerId.value);
  } catch (err) {
    if (!stopped) {
      error.value = err instanceof Error ? `${err.message}。请检查模型配置或手动评分。` : "再评失败，请检查模型配置或手动评分。";
      note.value = "";
    }
  } finally { regrading.value = false; }
}

onMounted(() => {
  if (props.part.job_state === "queued" || props.part.job_state === "running") {
    note.value = "模型任务正在等待或评分；如长时间等待，请检查模型配置，也可以手动评分。已有人工分仍是最终分。";
    void trackJob(answerId.value);
  }
});
onUnmounted(() => { stopped = true; });
</script>
