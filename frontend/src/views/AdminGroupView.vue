<template>
  <div class="page">
    <p><router-link to="/admin/accounts">← 学生账号</router-link></p>
    <h1>{{ data?.group?.label || "分组" }}</h1>
    <p class="hint" v-if="data?.ungrouped">还没进任何分组的学生。点进去是学生档案，可补真名、年级，并加进分组。一个学生可以同时在多个分组里。</p>
    <p class="hint" v-else>这个分组里的学生。点卡片进学生档案。班级是一种分组；班内还可以再分。</p>
    <p class="err">{{ error }}</p>
    <p class="hint">{{ message }}</p>

    <div class="grid">
      <router-link class="card" v-for="s in data?.students || []" :key="s.id" :to="`/admin/student/${s.id}`">
        <h2>{{ s.display_name || s.username }}</h2>
        <div class="meta">登录名 {{ s.username }}</div>
        <div class="meta">{{ s.class_label }}<span v-if="s.grade_name"> · {{ s.grade_name }}</span></div>
        <div class="meta" v-if="s.self_registered">自己注册</div>
      </router-link>
    </div>
    <p v-if="!data?.students?.length" class="hint">这个分组里还没有人。</p>

    <template v-if="!data?.ungrouped && meta">
      <h2 style="margin-top:28px">把已有学生加进来</h2>
      <p class="hint">不会从别的分组里拿掉。一个学生可以同时在这个分组和班级里。</p>
      <div class="chips">
        <button
          class="chip"
          v-for="s in outsiders"
          :key="s.id"
          type="button"
          @click="addMember(s.id)"
        >{{ s.display_name || s.username }}</button>
      </div>
      <p v-if="!outsiders.length" class="hint">没有可以再加的学生。</p>

      <h2 style="margin-top:28px">代开账号并加入此组</h2>
      <input v-model="kid.display_name" placeholder="真名，不填则等于登录名（学生看不到）" />
      <input v-model="kid.username" placeholder="登录名，中文也可以，学生用这个登录" maxlength="32" />
      <input v-model="kid.password" placeholder="密码" />
      <p class="field-label">年级</p>
      <div class="chips">
        <button class="chip" v-for="g in meta.grades" :key="g.id" :class="{ on: kid.grade === g.id }" type="button" @click="kid.grade = g.id">{{ g.name }}</button>
      </div>
      <button class="btn primary" type="button" @click="addKid">添加并加入</button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";

const route = useRoute();
const data = ref<any>(null);
const meta = ref<any>(null);
const allStudents = ref<any[]>([]);
const error = ref("");
const message = ref("");
const kid = reactive({ username: "", password: "", display_name: "", grade: 7 as number | null });

const ungrouped = computed(() => route.path.endsWith("/ungrouped"));
const outsiders = computed(() => {
  const inside = new Set((data.value?.students || []).map((s: any) => s.id));
  return allStudents.value.filter((s) => !inside.has(s.id));
});

async function load() {
  error.value = "";
  const path = ungrouped.value ? "/api/parent/groups/ungrouped" : `/api/parent/groups/${route.params.groupId}`;
  data.value = await api(path);
  const listed = (await api("/api/parent/students")) as { students: any[] };
  allStudents.value = listed.students || [];
}

async function addMember(studentId: number) {
  error.value = "";
  message.value = "";
  try {
    data.value = await api(`/api/parent/groups/${route.params.groupId}/members`, {
      method: "POST",
      body: JSON.stringify({ student_id: studentId }),
    });
    message.value = "已加入这个分组。";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

async function addKid() {
  error.value = "";
  message.value = "";
  try {
    await api("/api/parent/students", {
      method: "POST",
      body: JSON.stringify({
        ...kid,
        group_ids: [Number(route.params.groupId)],
      }),
    });
    message.value = "学生账号已建好，并加入这个分组。";
    kid.username = "";
    kid.password = "";
    kid.display_name = "";
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

onMounted(async () => {
  meta.value = await api("/api/parent/meta");
  await load();
});
watch(() => [route.params.groupId, route.path], load);
</script>
