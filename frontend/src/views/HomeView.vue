<template>
  <div class="page">
    <h1>今天做什么</h1>
    <p class="hint">选标签再开始。不点的那一项等于全选。从题库里随机抽 {{ size }} 题，写一题交一题。</p>
    <p class="hint" v-if="home?.challenge">有一次闯关还没做完，可以接着，也可以按新标签重开（上次未完成的会结束）。</p>
    <p class="err">{{ error }}</p>

    <p>科目</p>
    <div class="chips">
      <button class="chip" :class="{ on: filter.subject == null }" type="button" @click="filter.subject = null">全部</button>
      <button class="chip" v-for="s in home?.subjects || []" :key="s.id" :class="{ on: filter.subject === s.id }" type="button" @click="filter.subject = s.id">{{ s.name }}</button>
    </div>
    <p>年级</p>
    <div class="chips">
      <button class="chip" :class="{ on: filter.grade == null }" type="button" @click="filter.grade = null">全部</button>
      <button class="chip" v-for="g in home?.grades || []" :key="g.id" :class="{ on: filter.grade === g.id }" type="button" @click="filter.grade = g.id">{{ g.name }}</button>
    </div>
    <p>难度</p>
    <div class="chips">
      <button class="chip" :class="{ on: filter.difficulty == null }" type="button" @click="filter.difficulty = null">全部</button>
      <button class="chip" v-for="d in home?.difficulties || []" :key="d.id" :class="{ on: filter.difficulty === d.id }" type="button" @click="filter.difficulty = d.id">{{ d.name }}</button>
    </div>
    <p v-if="topics.length">知识点（可多选，必须同时有）</p>
    <div class="chips" v-if="topics.length">
      <button class="chip" v-for="t in topics" :key="t" :class="{ on: filter.tags.includes(t) }" type="button" @click="toggleTag(t)">{{ t }}</button>
    </div>
    <p class="hint">符合条件 {{ poolCount }} 道，开始后随机 {{ take }} 题。</p>
    <div class="chips">
      <button v-if="home?.challenge" class="btn" type="button" @click="resume">接着上次</button>
      <button class="btn primary" type="button" @click="start">开始闯关</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api";

const router = useRouter();
const error = ref("");
const home = ref<any>(null);
const poolCount = ref(0);
const take = ref(20);
const topics = ref<string[]>([]);
const filter = reactive({
  subject: null as string | null,
  grade: null as number | null,
  difficulty: null as string | null,
  tags: [] as string[],
});
const size = computed(() => home.value?.challenge_size || 20);
let poolTimer: number | undefined;

onMounted(async () => {
  home.value = await api("/api/home");
  await loadPool();
});

watch(filter, () => {
  window.clearTimeout(poolTimer);
  poolTimer = window.setTimeout(loadPool, 120);
}, { deep: true });

function toggleTag(name: string) {
  const i = filter.tags.indexOf(name);
  if (i >= 0) filter.tags.splice(i, 1);
  else filter.tags.push(name);
}

async function loadPool() {
  const params = new URLSearchParams();
  if (filter.subject) params.set("subject", filter.subject);
  if (filter.grade) params.set("grade", String(filter.grade));
  if (filter.difficulty) params.set("difficulty", filter.difficulty);
  for (const t of filter.tags) params.append("tags", t);
  const data = (await api(`/api/challenge/pool?${params}`)) as { count: number; take: number; topics: string[] };
  poolCount.value = data.count;
  take.value = data.take;
  topics.value = data.topics || [];
  const pruned = filter.tags.filter((t) => topics.value.includes(t));
  if (pruned.length !== filter.tags.length) {
    filter.tags.splice(0, filter.tags.length, ...pruned);
  }
}

async function go(body: Record<string, unknown>) {
  error.value = "";
  try {
    const data = (await api("/api/challenge/start", {
      method: "POST",
      body: JSON.stringify(body),
    })) as { id: number; index: number };
    await router.push(`/play/challenge/${data.id}/${data.index}`);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

function resume() {
  return go({ resume: true });
}

function start() {
  return go({
    subject: filter.subject,
    grade: filter.grade,
    difficulty: filter.difficulty,
    tags: filter.tags,
  });
}
</script>
