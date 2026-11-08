<template>
  <div class="generate-questions" v-if="meta">
    <h2>AI 出题</h2>
    <p class="hint">按课标生成，检查题目和答案后入库。出题和判题共用<router-link to="/admin/llm" class="settings-link">模型配置</router-link>。</p>
    <form @submit.prevent="generate">
      <fieldset :disabled="generating">
        <div class="generation-fields">
          <label>科目
            <select v-model="request.subject" required>
              <option v-for="s in meta.subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </label>
          <label>年级
            <select v-model.number="request.grade" required>
              <option disabled value="">选择年级</option>
              <option v-for="g in meta.grades" :key="g.id" :value="g.id">{{ g.name }}</option>
            </select>
          </label>
          <label>题型
            <select v-model="request.type" required>
              <option v-for="t in meta.types" :key="t.id" :value="t.id">{{ t.name }}</option>
            </select>
          </label>
          <label>难度
            <select v-model="request.difficulty" required>
              <option v-for="d in meta.difficulties" :key="d.id" :value="d.id">{{ d.name }}</option>
            </select>
          </label>
          <label>题数
            <input v-model.number="request.count" type="number" min="1" max="5" required />
          </label>
        </div>
        <label class="field-label" for="generation-topic">知识点与要求</label>
        <textarea id="generation-topic" v-model="request.topic" required maxlength="500" placeholder="例如：一次函数的图像与性质，已学过正比例函数；贴近生活，避免复杂计算。"></textarea>
        <button class="btn primary" type="submit" :disabled="!request.topic.trim() || saving">{{ generating ? '正在查课标、出题…' : '生成预览' }}</button>
      </fieldset>
    </form>
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <p v-if="message" class="hint" role="status">{{ message }}</p>

    <details class="card generated-draft" v-for="draft in drafts" :key="draft.item.slug" open>
      <summary>{{ draft.item.title }} · {{ draft.saved ? '已入库' : '待检查' }}</summary>
      <p class="meta">{{ draft.item.subject_name }} · {{ draft.item.grade_name }} · {{ draft.item.type_name }} · {{ draft.item.difficulty_name }}</p>
      <details class="source-notes">
        <summary>查看课标依据</summary>
        <p class="hint">{{ draft.notice }}</p>
        <p v-for="source in draft.sources" :key="source.path" class="meta">{{ source.path.split('/').pop() }} · PDF 第 {{ source.pages.join('、') }} 页</p>
      </details>
      <fieldset :disabled="draft.saved || draft.saving">
        <label class="field-label">题名</label>
        <input v-model="draft.item.title" />
        <label class="field-label">{{ draft.item.type === 'passage' ? '阅读材料' : '题干' }}</label>
        <textarea v-model="draft.item.left_md"></textarea>
        <div class="draft-part" v-for="(part, index) in draft.item.parts" :key="part.id">
          <h3>{{ isContainer(draft.item) ? `第 ${Number(index) + 1} 问` : '答案' }}</h3>
          <label class="field-label">分值</label>
          <input v-model.number="part.points" type="number" min="0.5" step="0.5" />
          <ItemPartEditor v-model="draft.item.parts[index]" :subject="draft.item.subject" :show-stem="isContainer(draft.item)" :allow-photo-toggle="draft.item.type === 'steps'" />
        </div>
        <button class="btn primary" type="button" @click="save(draft)">{{ draft.saving ? '正在入库…' : draft.saved ? '已入库' : '确认这题，入库' }}</button>
      </fieldset>
      <router-link v-if="draft.saved" :to="`/admin/item/${encodeURIComponent(draft.item.slug)}`" class="settings-link">到题库查看</router-link>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { api } from "../api";
import ItemPartEditor from "./ItemPartEditor.vue";

type Choice = { id: string | number; name: string };
type Meta = { subjects: Choice[]; grades: Choice[]; types: Choice[]; difficulties: Choice[] };
type Source = { path: string; pages: number[]; stage: string };
type Draft = { item: any; sources: Source[]; notice: string; saved: boolean; saving: boolean };
const props = defineProps<{ meta: Meta | null }>();
const request = reactive({ subject: "math", grade: "" as number | "", difficulty: "medium", type: "single", count: 3, topic: "" });
const generating = ref(false);
const drafts = ref<Draft[]>([]);
const error = ref("");
const message = ref("");
const saving = computed(() => drafts.value.some((draft) => draft.saving));

watch(() => props.meta, (meta) => {
  if (meta?.subjects.length && !meta.subjects.some((s) => s.id === request.subject)) request.subject = String(meta.subjects[0].id);
}, { immediate: true });

function isContainer(item: any) {
  return item.type === "passage" || item.type === "steps";
}

async function generate() {
  if (generating.value || saving.value) return;
  if (!request.grade) {
    error.value = "请先选择年级";
    return;
  }
  error.value = "";
  message.value = "";
  generating.value = true;
  try {
    const result = await api("/api/parent/items/generate", {
      method: "POST", body: JSON.stringify({ ...request, topic: request.topic.trim() }),
    }) as { items: any[]; sources: Source[]; notice: string };
    drafts.value.unshift(...result.items.map((item) => ({ item, sources: result.sources, notice: result.notice, saved: false, saving: false })));
    message.value = `已生成 ${result.items.length} 道，检查后逐题入库。`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "这次没出成题";
  } finally {
    generating.value = false;
  }
}

async function save(draft: Draft) {
  if (draft.saved || draft.saving) return;
  error.value = "";
  message.value = "";
  draft.saving = true;
  try {
    const item = JSON.parse(JSON.stringify(draft.item));
    item.points = item.parts.reduce((sum: number, part: any) => sum + Number(part.points), 0);
    for (const part of item.parts) {
      if (part.type === "numeric" && String(part.answer ?? "").trim()) part.answer = Number(part.answer);
      part.tolerance = Number(part.tolerance || 0);
    }
    draft.item = await api("/api/parent/items/generated/save", { method: "POST", body: JSON.stringify(item) });
    draft.saved = true;
    message.value = `已入库：${draft.item.title}`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "这题没保存成";
  } finally {
    draft.saving = false;
  }
}
</script>

<style scoped>
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.generation-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 16px; }
.generation-fields label { display: grid; gap: 6px; }
select { width: 100%; border: 1px solid var(--line); background: var(--paper); border-radius: 12px; padding: 12px; }
.settings-link { color: var(--accent); text-decoration: underline; }
.generated-draft { margin-top: 20px; }
summary { cursor: pointer; font-weight: 650; }
.source-notes { margin: 12px 0; }
.source-notes .hint { margin: 10px 0; }
.source-notes .meta { overflow-wrap: anywhere; }
.draft-part { border-top: 1px solid var(--line); margin: 18px 0; padding-top: 8px; }
fieldset:disabled { opacity: 0.7; }
</style>
