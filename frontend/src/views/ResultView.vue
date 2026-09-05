<template>
  <div class="page" v-if="data">
    <h1>闯关结束</h1>
    <p class="hint">{{ data.subject_name }} · 共 {{ data.total }} 题</p>
    <p class="score good" style="font-size: 28px">{{ data.score }} / {{ data.max_score }} 分</p>
    <p v-if="data.pending">还有 {{ data.pending }} 问待评分</p>
    <router-link class="btn primary" to="/">回首页</router-link>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";

const route = useRoute();
const data = ref<any>(null);

onMounted(async () => {
  data.value = await api(`/api/challenge/${route.params.runId}`);
});
</script>
