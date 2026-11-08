<template>
  <div class="page" v-if="item">
    <p><router-link to="/admin/bank">← 题库</router-link></p>
    <h1>改题</h1>
    <p class="hint">
      {{ item.subject_name }} · {{ item.type_name }} · {{ item.source_name }}。保存后写到这台电脑，git 更新不会盖掉。
    </p>
    <p class="err">{{ error }}</p>
    <p class="hint">{{ message }}</p>

    <p class="field-label">题目名字</p>
    <input v-model="item.title" placeholder="学生列表里看到的名字" />

    <p class="field-label">科目</p>
    <div class="chips" v-if="meta">
      <button class="chip" v-for="s in meta.subjects" :key="s.id" :class="{ on: item.subject === s.id }" type="button" @click="item.subject = s.id">{{ s.name }}</button>
    </div>
    <p class="field-label">年级</p>
    <div class="chips" v-if="meta">
      <button class="chip" v-for="g in meta.grades" :key="g.id" :class="{ on: item.grade === g.id }" type="button" @click="item.grade = g.id">{{ g.name }}</button>
    </div>
    <p class="field-label">难度</p>
    <div class="chips" v-if="meta">
      <button class="chip" v-for="d in meta.difficulties" :key="d.id" :class="{ on: item.difficulty === d.id }" type="button" @click="item.difficulty = d.id">{{ d.name }}</button>
    </div>

    <p class="field-label">知识点</p>
    <div class="chips">
      <button class="chip on" v-for="t in item.tags" :key="t" type="button" @click="removeTag(t)">{{ t }} ×</button>
    </div>
    <div class="choice-edit">
      <input v-model="newTag" placeholder="加一个知识点，回车" @keydown.enter.prevent="addTag" />
      <button class="btn" type="button" @click="addTag">加上</button>
    </div>

    <p class="field-label">{{ leftLabel }}</p>
    <textarea v-model="item.left_md" :placeholder="leftLabel"></textarea>
    <p class="hint">学生将看到的样子</p>
    <div class="card md" v-html="renderMd(item.left_md || '')"></div>

    <label class="photo-toggle" v-if="item.type === 'steps'">
      <input type="checkbox" v-model="item.allow_photo" />
      这题允许拍演算纸
    </label>

    <div v-for="(p, i) in item.parts" :key="p.id || i" class="card" style="margin-top:16px">
      <h2>{{ isContainer ? `第 ${Number(i) + 1} 问 · ${p.type_name}` : "答案和细则" }}</h2>
      <p class="field-label">这一问满分</p>
      <input v-model.number="p.points" type="number" min="0" step="0.5" />
      <ItemPartEditor v-model="item.parts[i]" :subject="item.subject" :show-stem="isContainer" :allow-photo-toggle="item.type === 'steps'" />
    </div>

    <button class="btn primary big" type="button" style="margin-top:20px" @click="save">保存</button>
  </div>
  <p v-else class="page hint">{{ error || "正在打开题目…" }}</p>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";
import { renderMd } from "../markdown";
import ItemPartEditor from "../components/ItemPartEditor.vue";

const route = useRoute();
const item = ref<any>(null);
const meta = ref<any>(null);
const error = ref("");
const message = ref("");
const newTag = ref("");

const isContainer = computed(() => item.value?.type === "passage" || item.value?.type === "steps");
const leftLabel = computed(() => (item.value?.type === "passage" ? "材料" : "题目"));

function normalize(data: any) {
  for (const p of data.parts || []) {
    if (p.type === "blank") {
      if (!Array.isArray(p.answer) || !p.answer.length) p.answer = p.answer ? [String(p.answer)] : [""];
    }
    if (p.type === "multiple" && !Array.isArray(p.answer)) p.answer = p.answer ? [String(p.answer)] : [];
    if ((p.type === "short" || p.type === "essay") && !Array.isArray(p.rubric)) p.rubric = [];
    if ((p.type === "single" || p.type === "multiple") && !Array.isArray(p.choices)) p.choices = [];
  }
  if (!Array.isArray(data.tags)) data.tags = [];
  return data;
}

async function load() {
  error.value = "";
  message.value = "";
  const slug = String(route.params.slug || "");
  try {
    meta.value = await api("/api/parent/meta");
    item.value = normalize(await api(`/api/parent/items/${encodeURIComponent(slug)}`));
  } catch (err) {
    error.value = err instanceof Error ? err.message : "打不开这道题";
    item.value = null;
  }
}

function addTag() {
  const name = newTag.value.trim();
  if (!name) return;
  if (!item.value.tags.includes(name)) item.value.tags.push(name);
  newTag.value = "";
}

function removeTag(name: string) {
  item.value.tags = item.value.tags.filter((t: string) => t !== name);
}

async function save() {
  error.value = "";
  message.value = "";
  try {
    item.value = normalize(
      await api(`/api/parent/items/${encodeURIComponent(item.value.slug)}`, {
        method: "PUT",
        body: JSON.stringify({
          title: item.value.title,
          subject: item.value.subject,
          grade: item.value.grade,
          difficulty: item.value.difficulty,
          tags: item.value.tags,
          points: item.value.points,
          left_md: item.value.left_md,
          allow_photo: item.value.allow_photo,
          parts: item.value.parts,
        }),
      }),
    );
    message.value = "已保存到这台电脑。";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没保存成";
  }
}

onMounted(load);
watch(() => route.params.slug, load);
</script>
