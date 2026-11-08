<template>
  <div class="page" v-if="data">
    <p>
      <router-link v-if="data.anonymous && data.paper_id" :to="`/admin/quiz/${data.paper_id}`">← 测验</router-link>
      <router-link v-else-if="data.student_id" :to="`/admin/student/${data.student_id}`">← {{ data.student }}</router-link>
    </p>
    <h1>{{ data.title }}</h1>
    <p class="hint">
      <span v-if="data.anonymous">匿名答卷</span>
      <span v-else>{{ data.student }}</span>
      · {{ data.status }} · {{ data.score }} / {{ data.max_score }} 分
      <span v-if="data.pending"> · 待评 {{ data.pending }}</span>
    </p>
    <p class="hint" v-if="data.anonymous">改判只在这里。模型分只是参考，已手改的分数不会被模型覆盖。</p>
    <article class="card" v-for="item in data.items" :key="item.slug" :id="'item-' + item.slug" style="margin-bottom:16px">
      <h2>{{ item.index + 1 }}. {{ item.title }}</h2>
      <p class="meta">{{ item.score }} / {{ item.max_score }} 分<span v-if="item.tags.length"> · {{ item.tags.join("、") }}</span></p>
      <div class="md" v-if="item.left_md" v-html="renderMd(item.left_md)"></div>
      <div class="part" v-for="part in item.parts" :key="part.part_id" :id="'answer-' + part.answer_id">
        <p>
          <strong>{{ part.type_name }}</strong> · {{ part.status_label }}
          · 管理员 {{ part.admin_score ?? "未手改" }} / {{ part.max_score }}
          · 模型 {{ part.llm_score ?? "—" }}
        </p>
        <div class="md" v-if="part.stem" v-html="renderMd(part.stem)"></div>
        <p>作答：{{ part.value_text }}</p>
        <img v-for="p in part.photos" :key="p" :src="'/api/uploads/file/' + p" style="max-height:160px;margin:8px 8px 0 0" />
        <p class="hint" v-if="part.reference">参考：{{ part.reference }}</p>
        <p class="hint" v-if="part.comment">评语：{{ part.comment }}</p>
        <p class="hint" v-else-if="part.llm_comment">模型评语：{{ part.llm_comment }}</p>
        <GradeBox v-if="canOverride(data.can_grade, part)" :part="part" @saved="reload" />
      </div>
    </article>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";
import { renderMd } from "../markdown";
import GradeBox from "../components/GradeBox.vue";
import { canOverride } from "../gradingPermissions";

const route = useRoute();
const data = ref<any>(null);

async function reload() {
  if (route.params.studentId && route.params.attemptId) {
    data.value = await api(`/api/parent/students/${route.params.studentId}/work/paper/${route.params.attemptId}`);
  } else {
    const kind = String(route.params.kind);
    const id = route.params.id;
    data.value = await api(`/api/parent/review/${kind}/${id}`);
  }
  const hash = window.location.hash;
  if (hash) {
    requestAnimationFrame(() => document.querySelector(hash)?.scrollIntoView());
  }
}

onMounted(reload);
watch(() => [route.params.kind, route.params.id, route.params.studentId, route.params.attemptId], reload);
</script>
