<template>
  <div class="page">
    <p class="err" v-if="error">{{ error }}</p>
    <template v-if="data">
    <h1>{{ data.title }}</h1>
    <p class="hint" v-if="data.timed && data.status !== 'submitted'">
      限时答题，剩余 {{ clock }}。时间以主机为准，到点会自动交卷。
    </p>
    <p class="hint" v-else-if="data.status !== 'submitted'">
      点题号进去写，输入会自动保存。单选题选完会跳到下一题；其它题点「下一题」。全部保存后才能交卷。
    </p>
    <p v-if="data.status === 'submitted' && !data.scores_visible" class="hint">已交卷，成绩还没公布。</p>
    <p v-else-if="data.status === 'submitted' && data.pending" class="hint">已交卷，还有主观题待评。</p>
    <SheetNav v-if="sheet.length" :items="sheet" @pick="openItem" />
    <div v-for="(sec, si) in catalog" :key="si">
      <h2 v-if="sec.heading" style="margin: 24px 0 12px">{{ sec.heading }}</h2>
      <div class="grid">
        <router-link class="card" v-for="it in sec.items" :key="it.slug" :to="playUrl(it.slug)">
          <h2>{{ it.n }}. {{ it.title }}</h2>
          <div class="meta">{{ it.points }} 分<span v-if="it.saved"> · 已保存</span></div>
        </router-link>
      </div>
    </div>
    <p v-if="data.status === 'submitted' && data.scores_visible" class="score good">已交卷 · {{ data.score }} / {{ data.max_score }} 分</p>
    <p v-else-if="data.status === 'submitted'" class="score">已交卷</p>
    <template v-else>
      <p class="hint" v-if="!data.can_submit">还有 {{ missing }} 题没保存，不能交卷。限时到点会自动交卷。</p>
      <button class="btn primary big" style="margin-top:24px;max-width:320px" type="button" :disabled="!data.can_submit" @click="submit">交卷</button>
    </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api";
import SheetNav from "../components/SheetNav.vue";

const route = useRoute();
const router = useRouter();
const data = ref<any>(null);
const error = ref("");
const left = ref<number | null>(null);
let timer: number | undefined;
const sheet = computed(() => (data.value?.sheet || []) as { n: number; slug: string; saved?: boolean }[]);
const missing = computed(() => (data.value?.missing_slugs || []).length);
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

function playUrl(slug: string) {
  return `/play/paper/${data.value.attempt_id}/${encodeURIComponent(slug)}`;
}

async function openItem(slug: string) {
  await router.push(playUrl(slug));
}

async function load() {
  error.value = "";
  try {
    data.value = await api(`/api/papers/attempts/${route.params.attemptId}`);
    left.value = data.value.remaining_sec ?? null;
  } catch (err) {
    data.value = null;
    error.value = err instanceof Error ? err.message : "打不开这份卷";
  }
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
