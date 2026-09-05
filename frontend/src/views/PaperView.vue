<template>
  <div class="page" v-if="data">
    <h1>{{ data.title }}</h1>
    <p class="hint" v-if="data.timed && data.status !== 'submitted'">
      限时答题，剩余 {{ clock }}。时间以主机为准，到点会自动交卷。
    </p>
    <p class="hint" v-else>点题号进去写，每题先保存。全部写完后在这里或题目里点交卷。试卷不能一题一交。</p>
    <p v-if="data.status === 'submitted' && data.pending" class="hint">已交卷，还有主观题待评。</p>
    <div v-for="(sec, si) in catalog" :key="si">
      <h2 v-if="sec.heading" style="margin: 24px 0 12px">{{ sec.heading }}</h2>
      <div class="grid">
        <router-link class="card" v-for="it in sec.items" :key="it.slug" :to="`/play/paper/${data.attempt_id}/${it.slug}`">
          <h2>{{ it.n }}. {{ it.title }}</h2>
          <div class="meta">{{ it.points }} 分</div>
        </router-link>
      </div>
    </div>
    <p class="err">{{ error }}</p>
    <p v-if="data.status === 'submitted'" class="score good">已交卷 · {{ data.score }} / {{ data.max_score }} 分</p>
    <button v-else class="btn primary big" style="margin-top:24px;max-width:320px" type="button" @click="submit">交卷</button>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";

const route = useRoute();
const data = ref<any>(null);
const error = ref("");
const left = ref<number | null>(null);
let timer: number | undefined;
const catalog = computed(() => {
  const rows = data.value?.sections;
  const items = data.value?.items || [];
  let n = 0;
  const number = (it: any) => {
    n += 1;
    return { ...it, n };
  };
  if (Array.isArray(rows) && rows.some((s: any) => s.heading || (s.items && s.items.length))) {
    return rows
      .filter((s: any) => (s.items || []).length)
      .map((s: any) => ({ heading: s.heading || "", items: (s.items || []).map(number) }));
  }
  return [{ heading: "", items: items.map(number) }];
});
const clock = computed(() => {
  const s = left.value ?? 0;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
});

async function load() {
  data.value = await api(`/api/papers/attempts/${route.params.attemptId}`);
  left.value = data.value.remaining_sec ?? null;
}

async function submit() {
  error.value = "";
  try {
    data.value = await api(`/api/papers/attempts/${route.params.attemptId}/submit`, { method: "POST" });
    left.value = null;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

onMounted(async () => {
  await load();
  if (data.value?.timed && data.value.status !== "submitted") {
    timer = window.setInterval(async () => {
      if (left.value == null) return;
      if (left.value <= 0) {
        window.clearInterval(timer);
        await submit();
        return;
      }
      left.value -= 1;
    }, 1000);
  }
});

onUnmounted(() => {
  if (timer) window.clearInterval(timer);
});
</script>
