<template>
  <div class="page" v-if="data">
    <p><router-link to="/admin/quizzes">← 测验</router-link></p>
    <h1>{{ data.title }}</h1>
    <p class="hint">{{ data.subject_name }} · {{ data.count }} 题<span v-if="data.timed"> · 限时 {{ data.duration_minutes }} 分钟</span></p>
    <h2>排名</h2>
    <p class="hint">待评完才计入正式名次。未评完的人仍列在下面。</p>
    <table v-if="complete.length">
      <thead>
        <tr>
          <th>名次</th>
          <th>学生</th>
          <th>分数</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in complete" :key="'c' + r.user_id">
          <td>第 {{ r.rank }} / {{ r.rank_total }} 名</td>
          <td>{{ r.name }}</td>
          <td>{{ r.score }} / {{ r.max_score }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="hint">还没有评完的答卷。</p>
    <h2 style="margin-top:28px">参加的学生</h2>
    <div class="grid">
      <router-link class="card" v-for="s in data.students" :key="s.user_id" :to="`/admin/review/paper/${s.attempt_id}`">
        <h2>{{ s.name }}</h2>
        <div class="meta">{{ s.status }} · {{ s.score }} / {{ s.max_score }}</div>
        <div class="meta" v-if="s.complete">第 {{ s.rank }} 名</div>
        <div class="meta" v-else-if="s.pending">待评 {{ s.pending }}，暂不进榜</div>
      </router-link>
    </div>
    <p v-if="!data.students?.length" class="hint">还没有学生打开这份卷。让他们在 8090 首页点这张试卷。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";

const route = useRoute();
const data = ref<any>(null);
const complete = computed(() => (data.value?.ranking || []).filter((r: any) => r.complete));

async function load() {
  data.value = await api(`/api/parent/papers/${route.params.paperId}`);
}

onMounted(load);
watch(() => route.params.paperId, load);
</script>
