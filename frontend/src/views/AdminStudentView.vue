<template>
  <div class="page" v-if="data">
    <p>
      <router-link to="/admin/students">← 学生</router-link>
      <span v-if="data.student.groups?.length">
        ·
        <template v-for="(g, i) in data.student.groups" :key="g.id">
          <span v-if="i">、</span>
          <router-link :to="`/admin/accounts/group/${g.id}`">{{ g.label }}</router-link>
        </template>
      </span>
      <span v-else> · <router-link to="/admin/accounts/ungrouped">未分组</router-link></span>
    </p>
    <h1>{{ data.student.display_name || data.student.username }}</h1>
    <p class="hint">登录名 {{ data.student.username }}（学生自己页面只看到这个，改不了）。真名只有老师这边能看。闯关可以点进去看题。试卷要等「测验」里发布成绩后，才能看这一次的作答。改判只在测验的匿名答卷里。</p>
    <p class="err">{{ error }}</p>
    <p class="hint">{{ message }}</p>

    <div class="card" style="margin:16px 0">
      <p class="field-label">真名（学生看不到）</p>
      <input v-model="edit.display_name" placeholder="默认等于登录名" />
      <p class="field-label">年级</p>
      <div class="chips" v-if="meta">
        <button class="chip" v-for="g in meta.grades" :key="g.id" :class="{ on: edit.grade === g.id }" type="button" @click="edit.grade = g.id">{{ g.name }}</button>
      </div>
      <p class="field-label">分组（可多选）</p>
      <div class="chips">
        <button class="chip" v-for="g in groups" :key="g.id" :class="{ on: edit.group_ids.includes(g.id) }" type="button" @click="toggleGroup(g.id)">{{ g.label }}</button>
      </div>
      <button class="btn primary" type="button" @click="saveProfile">保存档案</button>
    </div>

    <p v-if="empty" class="hint">这个学生在你负责的科目里还没有作答。</p>
    <div class="grid">
      <template v-for="r in rows" :key="r.kind + r.id">
        <router-link v-if="r.kind === 'challenge'" class="card" :to="`/admin/review/challenge/${r.id}`">
          <h2>{{ r.title }}</h2>
          <div class="meta">闯关 · {{ r.status }}</div>
          <div class="meta">{{ r.score }} / {{ r.max_score }} 分<span v-if="r.pending"> · 待评 {{ r.pending }}</span></div>
        </router-link>
        <router-link v-else-if="r.scores_released" class="card" :to="`/admin/student/${data.student.id}/paper/${r.id}`">
          <h2>{{ r.title }}</h2>
          <div class="meta">试卷 · {{ r.status }}</div>
          <div class="meta">{{ r.score }} / {{ r.max_score }} 分<span v-if="r.pending"> · 待评 {{ r.pending }}</span></div>
        </router-link>
        <div v-else class="card locked">
          <h2>{{ r.title }}</h2>
          <div class="meta">试卷 · {{ r.status }}</div>
          <div class="meta">成绩未发布，还不能看这一次的作答</div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";

const route = useRoute();
const data = ref<any>(null);
const meta = ref<any>(null);
const groups = ref<any[]>([]);
const error = ref("");
const message = ref("");
const edit = reactive({ display_name: "", grade: null as number | null, group_ids: [] as number[] });
const rows = computed(() => [...(data.value?.challenges || []), ...(data.value?.papers || [])]);
const empty = computed(() => rows.value.length === 0);

function toggleGroup(id: number) {
  const i = edit.group_ids.indexOf(id);
  if (i >= 0) edit.group_ids.splice(i, 1);
  else edit.group_ids.push(id);
}

async function load() {
  data.value = await api(`/api/parent/students/${route.params.studentId}/work`);
  const s = data.value.student;
  edit.display_name = s.display_name || "";
  edit.grade = s.grade ?? null;
  edit.group_ids = [...(s.group_ids || [])];
}

async function saveProfile() {
  error.value = "";
  message.value = "";
  try {
    const saved = await api(`/api/parent/students/${route.params.studentId}`, {
      method: "PUT",
      body: JSON.stringify(edit),
    });
    data.value.student = saved;
    message.value = "档案已保存。";
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

onMounted(async () => {
  meta.value = await api("/api/parent/meta");
  const listed = (await api("/api/parent/groups")) as { groups: any[] };
  groups.value = listed.groups || [];
  await load();
});
watch(() => route.params.studentId, load);
</script>
