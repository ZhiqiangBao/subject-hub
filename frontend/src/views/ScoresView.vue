<template>
  <div class="page">
    <h1>我的成绩</h1>
    <p class="hint">闯关、试卷，以及按标签看每道题的得分。</p>
    <div class="chips">
      <button class="chip" :class="{ on: tab === 'runs' }" type="button" @click="tab = 'runs'">闯关与试卷</button>
      <button class="chip" :class="{ on: tab === 'tags' }" type="button" @click="tab = 'tags'">按标签</button>
    </div>
    <p v-if="tab === 'runs' && empty" class="hint">还没有成绩。做完闯关或交卷后会出现。</p>
    <table v-if="tab === 'runs' && rows.length">
      <thead>
        <tr>
          <th>类型</th>
          <th>名称</th>
          <th>状态</th>
          <th>分数</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.kind + r.id">
          <td>{{ r.kind }}</td>
          <td><router-link :to="r.href">{{ r.title }}</router-link></td>
          <td>{{ r.status }}</td>
          <td>{{ r.score }} / {{ r.max_score }}<span v-if="r.pending">（待评 {{ r.pending }}）</span></td>
        </tr>
      </tbody>
    </table>
    <TagScores v-if="tab === 'tags'" endpoint="/api/scores/by-tag" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api } from "../api";
import TagScores from "../components/TagScores.vue";

type Row = {
  id: number;
  kind: string;
  title: string;
  status: string;
  href: string;
  score: number;
  max_score: number;
  pending: number;
};

const tab = ref<"runs" | "tags">("runs");
const challenges = ref<Row[]>([]);
const papers = ref<Row[]>([]);
const rows = computed(() => [...challenges.value, ...papers.value]);
const empty = computed(() => rows.value.length === 0);

onMounted(async () => {
  const data = (await api("/api/scores")) as { challenges: Row[]; papers: Row[] };
  challenges.value = data.challenges;
  papers.value = data.papers;
});
</script>
