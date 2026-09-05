<template>
  <div class="page">
    <h1>试卷</h1>
    <p class="hint">点进去写。每题先保存，全部写完后交卷。</p>
    <p class="err">{{ error }}</p>
    <div class="grid" v-if="papers.length">
      <button class="card" v-for="p in papers" :key="p.id" type="button" @click="openPaper(p)">
        <h2>{{ p.title }}</h2>
        <div class="meta">{{ p.subject_name }} · {{ p.status }}<span v-if="p.timed"> · 限时 {{ p.duration_minutes }} 分钟</span></div>
      </button>
    </div>
    <p v-else class="hint">还没有发给你的试卷。管理员组卷后会出现在这里。</p>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api";

const router = useRouter();
const error = ref("");
const papers = ref<any[]>([]);

onMounted(async () => {
  const home = (await api("/api/home")) as { papers?: any[] };
  papers.value = home.papers || [];
});

async function openPaper(p: { id: number }) {
  error.value = "";
  try {
    const data = (await api(`/api/papers/${p.id}/open`, { method: "POST" })) as { attempt_id: number };
    await router.push(`/paper/${data.attempt_id}`);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "打不开这份卷";
  }
}
</script>
