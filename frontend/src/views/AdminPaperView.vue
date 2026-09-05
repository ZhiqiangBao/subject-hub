<template>
  <div class="page" v-if="data">
    <p><router-link to="/admin/quizzes">← 测验</router-link></p>
    <h1>{{ data.title }}</h1>
    <p class="hint">
      {{ data.subject_name }} · {{ data.count }} 题 · {{ data.flow_label }}
    </p>
    <p class="hint" v-if="data.opens_at">答题时间（{{ zoneLabel }}）：{{ fmtTime(data.opens_at) }} 至 {{ fmtTime(data.closes_at) }}</p>

    <div v-if="!data.released || data.window === 'waiting'" class="card" style="margin:16px 0">
      <p class="field-label">开始作答（{{ zoneLabel }}）</p>
      <input v-model="opensLocal" type="datetime-local" />
      <p class="field-label">结束作答（{{ zoneLabel }}）</p>
      <input v-model="closesLocal" type="datetime-local" />
      <p class="field-label">测验对象（分组，可多选）</p>
      <div class="chips">
        <button class="chip" v-for="g in groups" :key="g.id" type="button" :class="{ on: selected.includes(g.id) }" @click="toggleGroup(g.id)">{{ g.label }}</button>
      </div>
      <p class="hint" v-if="!groups.length">还没有分组。先去「学生账号」建班级或分组。</p>
      <p class="hint">班级也是分组。选中的组才能看见这份卷；没选中的看不见。组里没作答的人，截止后记缺考 0 分。某个组可单独填时间，不填就用上面的时间。</p>
      <div v-for="g in selectedGroups" :key="'t' + g.id" class="card" style="margin:10px 0">
        <h2>{{ g.label }} 单独时间（可空）</h2>
        <input v-model="groupTimes[g.id].opens" type="datetime-local" />
        <input v-model="groupTimes[g.id].closes" type="datetime-local" />
      </div>
      <p class="hint">默认北京时间，可在顶栏下拉改时区。填写的是你选的时区；开考以主机时钟为准。发布后学生能看到卡片，开始之前点不进去，也看不到题目。</p>
      <div class="chips">
        <button v-if="!data.released" class="btn primary" type="button" @click="release">发布试卷</button>
        <button v-else class="btn" type="button" @click="saveWindow">改答题时间</button>
      </div>
    </div>

    <div class="chips">
      <button v-if="data.released" class="btn primary" type="button" :disabled="!data.can_start_grade" @click="act('start-grade')">{{ data.grading ? "再评一次" : "开始评分" }}</button>
      <button v-if="data.grading" class="btn ghost" type="button" @click="retryPending">重试未评</button>
      <button
        v-if="data.grading && !data.scores_released"
        class="btn"
        type="button"
        :disabled="!data.can_release_scores"
        @click="act('release-scores')"
      >发布成绩</button>
    </div>
    <p class="hint" v-if="!data.released">设好时间再发布。限时就是上面这段答题时间。</p>
    <p class="hint" v-else-if="!data.can_start_grade">答题截止后才能开始评分。截止前交卷只收答案，不判分。</p>
    <p class="hint" v-else-if="!data.grading">可以开始评分。客观题本机判，主观题交给模型。改过题库客观答案后可再评一次。</p>
    <p class="hint" v-else-if="!data.scores_released && data.ungraded">还有 {{ data.ungraded }} 问没出分（含模型排队）。本机和模型都判完，才能点「发布成绩」。</p>
    <p class="hint" v-else-if="!data.scores_released">分数已出齐。在下面匿名答卷里改判主观题。点「发布成绩」后，学生页才能看该生这一次的作答。</p>
    <p class="err">{{ error }}</p>
    <p class="hint">{{ message }}</p>
    <h2>匿名答卷</h2>
    <p class="hint">不显示答题人。点进去改判主观题。模型分只是参考，已手改的分数不会被模型覆盖。</p>
    <div class="grid">
      <router-link class="card" v-for="s in data.scripts" :key="s.attempt_id" :to="`/admin/review/paper/${s.attempt_id}`">
        <h2>{{ s.label }}</h2>
        <div class="meta">{{ s.status }} · {{ s.score }} / {{ s.max_score }}</div>
        <div class="meta" v-if="s.complete">第 {{ s.rank }} 名</div>
        <div class="meta" v-else-if="s.pending">待评 {{ s.pending }}</div>
      </router-link>
    </div>
    <p v-if="!data.scripts?.length" class="hint">指定分组里还没有答卷。发布后卡片只出现在选中分组的学生那边；截止后未作答记缺考 0 分。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";
import { displayZone, fmtInZone, toZoneInput, zoneLocalToIso, zoneName } from "../timeZone";

const route = useRoute();
const data = ref<any>(null);
const error = ref("");
const message = ref("");
const opensLocal = ref("");
const closesLocal = ref("");
const groups = ref<any[]>([]);
const selected = ref<number[]>([]);
const groupTimes = reactive<Record<number, { opens: string; closes: string }>>({});
const zoneLabel = computed(() => zoneName(displayZone.value));
const selectedGroups = computed(() => groups.value.filter((g) => selected.value.includes(g.id)));
let poll: number | undefined;

function fmtTime(iso?: string | null) {
  return fmtInZone(iso);
}

function ensureTime(id: number) {
  if (!groupTimes[id]) groupTimes[id] = { opens: "", closes: "" };
}

function toggleGroup(id: number) {
  const i = selected.value.indexOf(id);
  if (i >= 0) selected.value.splice(i, 1);
  else {
    selected.value.push(id);
    ensureTime(id);
  }
}

function windowBody() {
  const audiences = selected.value.map((id) => {
    const t = groupTimes[id] || { opens: "", closes: "" };
    const row: Record<string, unknown> = { group_id: id };
    if (t.opens && t.closes) {
      row.opens_at = zoneLocalToIso(t.opens);
      row.closes_at = zoneLocalToIso(t.closes);
    }
    return row;
  });
  return {
    opens_at: zoneLocalToIso(opensLocal.value),
    closes_at: zoneLocalToIso(closesLocal.value),
    audiences,
  };
}

function fillInputs() {
  const minutes = Number(data.value?.duration_minutes || 40);
  opensLocal.value = toZoneInput(data.value?.opens_at, data.value?.opens_at ? 0 : 5);
  closesLocal.value = toZoneInput(data.value?.closes_at, data.value?.closes_at ? 0 : 5 + minutes);
}

function stopPoll() {
  if (poll) {
    window.clearInterval(poll);
    poll = undefined;
  }
}

function armPoll() {
  stopPoll();
  if (data.value?.grading && !data.value?.scores_released && data.value?.ungraded) {
    poll = window.setInterval(() => {
      load();
    }, 4000);
  }
}

async function load() {
  data.value = await api(`/api/parent/papers/${route.params.paperId}`);
  fillInputs();
  if (!data.value?.grading) {
    selected.value = (data.value?.audiences || []).map((a: any) => a.group_id);
    for (const a of data.value?.audiences || []) {
      ensureTime(a.group_id);
      groupTimes[a.group_id].opens = a.opens_at ? toZoneInput(a.opens_at, 0) : "";
      groupTimes[a.group_id].closes = a.closes_at ? toZoneInput(a.closes_at, 0) : "";
    }
  }
  armPoll();
}

async function release() {
  error.value = "";
  message.value = "";
  if (!opensLocal.value || !closesLocal.value) {
    error.value = "请填写开始和结束时间";
    return;
  }
  if (!selected.value.length) {
    error.value = "请至少选一个分组作为测验对象";
    return;
  }
  try {
    data.value = await api(`/api/parent/papers/${route.params.paperId}/release`, {
      method: "POST",
      body: JSON.stringify(windowBody()),
    });
    message.value = "已发布。选中分组的学生现在能看到卡片，到开始时间才能作答。";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

async function saveWindow() {
  error.value = "";
  message.value = "";
  try {
    data.value = await api(`/api/parent/papers/${route.params.paperId}/window`, {
      method: "POST",
      body: JSON.stringify(windowBody()),
    });
    message.value = "答题时间已改。";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

async function act(kind: "start-grade" | "release-scores") {
  error.value = "";
  message.value = "";
  if (kind === "start-grade" && !data.value?.can_start_grade) {
    error.value = "答题还没截止，不能开始评分";
    return;
  }
  if (kind === "release-scores" && !data.value?.can_release_scores) {
    error.value = "还有问没出分，出齐才能发布成绩";
    return;
  }
  try {
    data.value = await api(`/api/parent/papers/${route.params.paperId}/${kind}`, { method: "POST" });
    armPoll();
    if (kind === "start-grade") message.value = "已开始评分。";
    else message.value = "成绩已发给学生。学生页现在可以点进这一次看作答。";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

async function retryPending() {
  error.value = "";
  message.value = "";
  try {
    const data = (await api("/api/parent/grade/retry-pending", { method: "POST" })) as { count: number };
    message.value = data.count ? `已重新排队 ${data.count} 问。` : "没有待评，或还没配置模型。";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

onMounted(async () => {
  const listed = (await api("/api/parent/groups")) as { groups: any[] };
  groups.value = listed.groups || [];
  await load();
});
onUnmounted(stopPoll);
watch(() => route.params.paperId, load);
watch(displayZone, () => {
  if (data.value) fillInputs();
});
</script>
