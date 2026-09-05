<template>
  <div class="page">
    <h1>试卷</h1>
    <p class="hint">到答题时间才能点进去。默认北京时间，可在顶栏下拉改时区。开始之前只能看见这张卡片，看不到题目。</p>
    <p class="err">{{ error }}</p>
    <div class="grid" v-if="papers.length">
      <template v-for="p in papers" :key="p.id">
        <button v-if="p.can_enter" class="card" type="button" @click="openPaper(p)">
          <h2>{{ p.title }}</h2>
          <div class="meta">{{ p.subject_name }} · {{ p.flow_label }}</div>
          <div class="meta" v-if="p.opens_at">{{ fmtTime(p.opens_at) }} 至 {{ fmtTime(p.closes_at) }}（{{ zoneLabel }}）</div>
        </button>
        <div v-else class="card locked">
          <h2>{{ p.title }}</h2>
          <div class="meta">{{ p.subject_name }} · {{ p.flow_label }}</div>
          <div class="meta" v-if="p.window === 'waiting'">{{ fmtTime(p.opens_at) }}（{{ zoneLabel }}）开始，现在还不能作答</div>
          <div class="meta" v-else-if="p.window === 'closed'">{{ fmtTime(p.closes_at) }}（{{ zoneLabel }}）已截止</div>
        </div>
      </template>
    </div>
    <p v-else class="hint">还没有发给你的试卷。管理员发布后会出现在这里。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api";
import { displayZone, fmtInZone, zoneName } from "../timeZone";

const router = useRouter();
const error = ref("");
const papers = ref<any[]>([]);
const zoneLabel = computed(() => zoneName(displayZone.value));

function fmtTime(iso?: string | null) {
  return fmtInZone(iso);
}

onMounted(async () => {
  const home = (await api("/api/home")) as { papers?: any[] };
  papers.value = home.papers || [];
});

async function openPaper(p: { id: number; can_enter?: boolean }) {
  error.value = "";
  if (!p.can_enter) return;
  try {
    const data = (await api(`/api/papers/${p.id}/open`, { method: "POST" })) as { attempt_id: number };
    await router.push(`/paper/${data.attempt_id}`);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "打不开这份卷";
  }
}
</script>
