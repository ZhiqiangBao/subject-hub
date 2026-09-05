<template>
  <div>
    <p class="hint">科目、年级、难易、题型每题只有一个。知识点可多选，必须同时满足（取交集）。</p>
    <div v-if="showStudents && data.students.length" class="chips">
      <button class="chip" :class="{ on: studentId == null }" type="button" @click="studentId = null">全部学生</button>
      <button
        class="chip"
        v-for="s in data.students"
        :key="s.id"
        :class="{ on: studentId === s.id }"
        type="button"
        @click="studentId = s.id"
      >
        {{ s.name }}
      </button>
    </div>
    <p v-if="groups.length === 0 && loaded" class="hint">还没有按题记下的分数。</p>
    <template v-for="g in exclusiveGroups" :key="g.key">
      <p v-if="g.chips.length">{{ g.title }}</p>
      <div v-if="g.chips.length" class="chips">
        <button class="chip" :class="{ on: exclusive[g.key] == null }" type="button" @click="exclusive[g.key] = null">全部</button>
        <button
          class="chip"
          v-for="c in g.chips"
          :key="c.id"
          :class="{ on: exclusive[g.key] === c.id }"
          type="button"
          @click="exclusive[g.key] = exclusive[g.key] === c.id ? null : c.id"
        >
          {{ c.name }}
        </button>
      </div>
    </template>
    <p v-if="data.topics.length">知识点（可多选）</p>
    <div v-if="data.topics.length" class="chips">
      <button
        class="chip"
        v-for="c in data.topics"
        :key="c.id"
        :class="{ on: topics.includes(c.id) }"
        type="button"
        @click="toggleTopic(c.id)"
      >
        {{ c.name }}
      </button>
    </div>
    <table v-if="rows.length">
      <thead>
        <tr>
          <th v-if="showStudentCol">学生</th>
          <th>题目</th>
          <th>标签</th>
          <th>来源</th>
          <th>状态</th>
          <th>分数</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.user_id + r.slug">
          <td v-if="showStudentCol">{{ r.student }}</td>
          <td>
            <router-link v-if="r.href" :to="r.href">{{ r.title }}</router-link>
            <span v-else>{{ r.title }}</span>
          </td>
          <td>{{ r.subject_name }} · {{ r.type_name }} · {{ r.difficulty_name }}{{ r.tags.length ? " · " + r.tags.join("、") : "" }}</td>
          <td>{{ r.source }}</td>
          <td>{{ r.status }}</td>
          <td>{{ r.score }} / {{ r.max_score }}<span v-if="r.pending">（待评 {{ r.pending }}）</span></td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="loaded && groups.length" class="hint">这个标签组合下还没有题。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { api } from "../api";

type Chip = { id: string; name: string; score: number; max_score: number; count: number; pending: number };
type ItemRow = {
  user_id: number;
  student: string;
  slug: string;
  title: string;
  subject: string;
  subject_name: string;
  type: string;
  type_name: string;
  difficulty: string;
  difficulty_name: string;
  grade: number | null;
  tags: string[];
  score: number;
  max_score: number;
  pending: number;
  status: string;
  source: string;
  href: string | null;
};

const props = defineProps<{ endpoint: string; showStudents?: boolean }>();

const loaded = ref(false);
const studentId = ref<number | null>(null);
const exclusive = reactive<Record<string, string | null>>({
  subjects: null,
  types: null,
  difficulties: null,
  grades: null,
});
const topics = ref<string[]>([]);
const data = ref<{
  students: { id: number; name: string }[];
  subjects: Chip[];
  types: Chip[];
  difficulties: Chip[];
  grades: Chip[];
  topics: Chip[];
  items: ItemRow[];
}>({
  students: [],
  subjects: [],
  types: [],
  difficulties: [],
  grades: [],
  topics: [],
  items: [],
});

const exclusiveGroups = computed(() =>
  [
    { key: "subjects", title: "科目", chips: data.value.subjects },
    { key: "types", title: "题型", chips: data.value.types },
    { key: "difficulties", title: "难易", chips: data.value.difficulties },
    { key: "grades", title: "年级", chips: data.value.grades },
  ].filter((g) => g.chips.length)
);

const groups = computed(() => exclusiveGroups.value.length || data.value.topics.length);

const showStudentCol = computed(() => Boolean(props.showStudents) && studentId.value == null);

const rows = computed(() => {
  return data.value.items.filter((row) => {
    if (exclusive.subjects && row.subject !== exclusive.subjects) return false;
    if (exclusive.types && row.type !== exclusive.types) return false;
    if (exclusive.difficulties && row.difficulty !== exclusive.difficulties) return false;
    if (exclusive.grades && String(row.grade) !== exclusive.grades) return false;
    if (topics.value.length && !topics.value.every((t) => row.tags.includes(t))) return false;
    return true;
  });
});

function toggleTopic(id: string) {
  topics.value = topics.value.includes(id) ? topics.value.filter((x) => x !== id) : [...topics.value, id];
}

async function load() {
  const q = props.showStudents && studentId.value != null ? `?student_id=${studentId.value}` : "";
  data.value = (await api(`${props.endpoint}${q}`)) as typeof data.value;
  loaded.value = true;
}

onMounted(load);
watch(studentId, () => {
  topics.value = [];
  load();
});
</script>
