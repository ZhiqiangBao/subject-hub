<template>
  <div class="page" v-if="data">
    <p><router-link to="/admin/students">← 学生</router-link></p>
    <h1>{{ data.student.display_name }}</h1>
    <p class="hint">{{ data.student.grade_name }} · {{ data.student.username }}。点测验卡片看这一次每一题，主观题可以改判。</p>
    <p v-if="empty" class="hint">这个学生在你负责的科目里还没有作答。</p>
    <div class="grid">
      <router-link class="card" v-for="r in rows" :key="r.kind + r.id" :to="`/admin/review/${r.kind}/${r.id}`">
        <h2>{{ r.title }}</h2>
        <div class="meta">{{ r.kind === "challenge" ? "闯关" : "试卷" }} · {{ r.status }}</div>
        <div class="meta">{{ r.score }} / {{ r.max_score }} 分<span v-if="r.pending"> · 待评 {{ r.pending }}</span></div>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";

const route = useRoute();
const data = ref<any>(null);
const rows = computed(() => [...(data.value?.challenges || []), ...(data.value?.papers || [])]);
const empty = computed(() => rows.value.length === 0);

async function load() {
  data.value = await api(`/api/parent/students/${route.params.studentId}/work`);
}

onMounted(load);
watch(() => route.params.studentId, load);
</script>
