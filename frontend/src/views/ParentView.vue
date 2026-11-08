<template>
  <div class="page">
    <h1>{{ pageTitle }}</h1>
    <p class="hint">{{ pageHint }}</p>
    <p class="err">{{ error }}</p>
    <p class="hint">{{ message }}</p>

    <section v-if="tab === 'progress'">
      <div class="grid">
        <router-link class="card" v-for="s in progress?.students || []" :key="s.id" :to="`/admin/student/${s.id}`">
          <h2>{{ s.display_name || s.username }}</h2>
          <div class="meta">登录名 {{ s.username }}</div>
          <div class="meta">{{ s.class_label || s.grade_name }}</div>
          <div class="meta">{{ s.score ?? 0 }} / {{ s.max_score ?? 0 }} 分<span v-if="s.pending"> · 待评 {{ s.pending }}</span></div>
        </router-link>
      </div>
      <p v-if="!progress?.students?.length" class="hint">还没有学生注册。</p>
      <h2 style="margin-top:28px">按标签看题</h2>
      <TagScores endpoint="/api/parent/scores/by-tag" :show-students="true" />
    </section>

    <section v-if="tab === 'quizzes'">
      <div class="grid">
        <router-link class="card" v-for="p in papers" :key="p.id" :to="`/admin/quiz/${p.id}`">
          <h2>{{ p.title }}</h2>
          <div class="meta">{{ p.subject_name }} · {{ p.flow_label }} · {{ p.submitted }}/{{ p.joined }} 人已交</div>
          <div class="meta" v-if="p.audiences?.length">{{ (p.audiences || []).map((a: { label: string }) => a.label).join("、") }}</div>
          <div class="meta" v-if="p.opens_at">{{ fmtTime(p.opens_at) }} 至 {{ fmtTime(p.closes_at) }}（{{ zoneLabel }}）<span v-if="p.window === 'waiting'"> · 未到答题时间</span></div>
          <div class="meta" v-if="p.ungraded">待评 {{ p.ungraded }}</div>
        </router-link>
      </div>
      <p v-if="!papers.length" class="hint">还没有组过卷。去「组卷」生成一份。</p>
    </section>

    <section v-if="tab === 'assemble' && meta">
      <p>科目</p>
      <div class="chips">
        <button class="chip" v-for="s in meta.subjects" :key="s.id" :class="{ on: assemble.subject === s.id }" type="button" @click="assemble.subject = s.id">{{ s.name }}</button>
      </div>
      <p>年级</p>
      <div class="chips">
        <button class="chip" :class="{ on: assemble.grade == null }" type="button" @click="assemble.grade = null">全部</button>
        <button class="chip" v-for="g in meta.grades" :key="g.id" :class="{ on: assemble.grade === g.id }" type="button" @click="assemble.grade = g.id">{{ g.name }}</button>
      </div>
      <p>难度</p>
      <div class="chips">
        <button class="chip" :class="{ on: assemble.difficulty == null }" type="button" @click="assemble.difficulty = null">全部</button>
        <button class="chip" v-for="d in meta.difficulties" :key="d.id" :class="{ on: assemble.difficulty === d.id }" type="button" @click="assemble.difficulty = d.id">{{ d.name }}</button>
      </div>
      <p>知识点（可多选，同时符合。不点=不限）</p>
      <div class="chips">
        <button class="chip" :class="{ on: assemble.tags.length === 0 }" type="button" @click="assemble.tags = []">不限</button>
        <button class="chip" v-for="t in assembleTopics" :key="t" :class="{ on: assemble.tags.includes(t) }" type="button" @click="toggleAssembleTag(t)">{{ t }}</button>
      </div>
      <p v-if="!assembleTopics.length" class="hint">这个条件下题库还没有知识点标签。</p>
      <p>题型与大题说明</p>
      <p class="hint">每类写数量。说明里的 {count} 是题数，{points} 是每题分，{total} 是本大题总分。</p>
      <div class="card" v-for="sec in assemble.sections" :key="sec.id" style="margin-bottom:10px">
        <h2>{{ sec.name }} · 可选 {{ sec.available }} 道</h2>
        <p>数量 {{ sec.count }}</p>
        <div class="chips">
          <button class="chip" type="button" @click="sec.count = Math.max(0, sec.count - 1)">少一题</button>
          <button class="chip" type="button" @click="sec.count += 1">多一题</button>
        </div>
        <p class="field-label">大题说明</p>
        <input v-model="sec.heading" :placeholder="sec.name + '（本题共{count}小题，每小题{points}分）'" />
      </div>
      <p>类型</p>
      <div class="chips">
        <button class="chip" :class="{ on: assemble.kind === 'homework' }" type="button" @click="assemble.kind = 'homework'">作业（可再改）</button>
        <button class="chip" :class="{ on: assemble.kind === 'exam' }" type="button" @click="assemble.kind = 'exam'">考试（交一次）</button>
      </div>
      <p>限时</p>
      <div class="chips">
        <button class="chip" :class="{ on: assemble.duration_minutes === 0 }" type="button" @click="assemble.duration_minutes = 0">不限时</button>
        <button class="chip" :class="{ on: assemble.duration_minutes === 20 }" type="button" @click="assemble.duration_minutes = 20">20 分钟</button>
        <button class="chip" :class="{ on: assemble.duration_minutes === 40 }" type="button" @click="assemble.duration_minutes = 40">40 分钟</button>
        <button class="chip" :class="{ on: assemble.duration_minutes === 60 }" type="button" @click="assemble.duration_minutes = 60">60 分钟</button>
      </div>
      <button class="btn primary" type="button" @click="doAssemble">生成并发给学生</button>
    </section>

    <section v-if="tab === 'bank' && meta">
      <p>科目</p>
      <div class="chips">
        <button class="chip" :class="{ on: bankFilter.subject == null }" type="button" @click="bankFilter.subject = null">全部</button>
        <button class="chip" v-for="s in meta.subjects" :key="s.id" :class="{ on: bankFilter.subject === s.id }" type="button" @click="bankFilter.subject = s.id">{{ s.name }}</button>
      </div>
      <p>年级</p>
      <div class="chips">
        <button class="chip" :class="{ on: bankFilter.grade == null }" type="button" @click="bankFilter.grade = null">全部</button>
        <button class="chip" v-for="g in meta.grades" :key="g.id" :class="{ on: bankFilter.grade === g.id }" type="button" @click="bankFilter.grade = g.id">{{ g.name }}</button>
      </div>
      <p>难度</p>
      <div class="chips">
        <button class="chip" :class="{ on: bankFilter.difficulty == null }" type="button" @click="bankFilter.difficulty = null">全部</button>
        <button class="chip" v-for="d in meta.difficulties" :key="d.id" :class="{ on: bankFilter.difficulty === d.id }" type="button" @click="bankFilter.difficulty = d.id">{{ d.name }}</button>
      </div>
      <p>题型</p>
      <div class="chips">
        <button class="chip" :class="{ on: bankFilter.type == null }" type="button" @click="bankFilter.type = null">全部</button>
        <button class="chip" v-for="t in meta.types" :key="t.id" :class="{ on: bankFilter.type === t.id }" type="button" @click="bankFilter.type = t.id">{{ t.name }}</button>
      </div>
      <p v-if="bankTopics.length">知识点（可多选，必须同时有）</p>
      <div class="chips" v-if="bankTopics.length">
        <button class="chip" v-for="t in bankTopics" :key="t" :class="{ on: bankFilter.tags.includes(t) }" type="button" @click="toggleBankTag(t)">{{ t }}</button>
      </div>
      <p class="hint">共 {{ bankItems.length }} 道</p>
      <div class="grid">
        <router-link class="card" v-for="it in bankItems" :key="it.slug" :to="`/admin/item/${encodeURIComponent(it.slug)}`">
          <h2>{{ it.title }}</h2>
          <div class="meta">{{ it.subject_name }} · {{ it.type_name }} · {{ it.grade_name }} · {{ it.difficulty_name }}</div>
          <div class="meta" v-if="it.tags?.length">{{ it.tags.join("、") }}</div>
          <div class="meta">{{ it.source_name }}</div>
        </router-link>
      </div>
      <p v-if="!bankItems.length" class="hint">这个标签组合下还没有题。</p>
    </section>

    <section v-if="tab === 'add'">
      <GenerateQuestions :meta="meta" />
      <details class="card" style="margin-top:28px">
      <summary>从聊天导入</summary>
      <p class="hint">先复制出题说明，贴到任意聊天人工智能里，用普通人说话。回来把回复全文贴上，或上传 `.yaml` / `.yml`，或多个 yaml 打成的 `.zip`。不要传 Word、PDF。</p>
      <button class="btn" type="button" @click="copySkill">复制出题说明</button>
      <textarea v-model="paste" placeholder="把人工智能的回复整段贴在这里" @input="cancelImport"></textarea>
      <button class="btn primary" type="button" :disabled="importBusy" @click="doPaste">预览题目</button>
      <label class="btn">选择文件
        <input type="file" hidden :disabled="importBusy" @change="doFile" />
      </label>
      <div v-if="importPreview">
        <h3>请检查 {{ importPreview.items.length }} 道题</h3>
        <article v-for="(candidate, index) in importPreview.items" :key="index" class="card">
          <h4>{{ candidate.title }}</h4>
          <div class="md" v-html="renderMd(candidate.left_md || '')"></div>
          <div v-for="(part, partIndex) in candidate.parts" :key="partIndex">
            <p>第 {{ partIndex + 1 }} 问 · {{ part.points }} 分</p>
            <div class="md" v-html="renderMd(part.stem || '')"></div>
            <p v-for="choice in part.choices || []" :key="choice.id">{{ choice.id }}. {{ choice.text }}</p>
            <p>答案：{{ formatImportValue(part.answer) }}</p>
            <p>参考：{{ formatImportValue(part.reference) }}</p>
          </div>
        </article>
        <button class="btn primary" type="button" :disabled="importBusy" @click="confirmImport">确认入库</button>
        <button class="btn" type="button" :disabled="importBusy" @click="cancelImport">取消</button>
      </div>
      </details>
      <details class="card" style="margin-top:16px">
      <summary>自己出一题</summary>
      <p class="field-label">科目</p>
      <div class="chips" v-if="meta">
        <button class="chip" v-for="s in meta.subjects" :key="s.id" :class="{ on: plain.subject === s.id }" type="button" @click="plain.subject = s.id">{{ s.name }}</button>
      </div>
      <p class="field-label">题型</p>
      <div class="chips">
        <button class="chip" v-for="t in plainTypes" :key="t.id" :class="{ on: plain.type === t.id }" type="button" @click="plain.type = t.id">{{ t.name }}</button>
      </div>
      <p class="field-label">年级</p>
      <div class="chips" v-if="meta">
        <button class="chip" v-for="g in meta.grades" :key="g.id" :class="{ on: plain.grade === g.id }" type="button" @click="plain.grade = g.id">{{ g.name }}</button>
      </div>
      <p class="field-label">难度</p>
      <div class="chips" v-if="meta">
        <button class="chip" v-for="d in meta.difficulties" :key="d.id" :class="{ on: plain.difficulty === d.id }" type="button" @click="plain.difficulty = d.id">{{ d.name }}</button>
      </div>
      <p class="field-label">知识点（可多选）</p>
      <div class="chips">
        <button class="chip" v-for="t in plainTagChoices" :key="t" :class="{ on: plain.tags.includes(t) }" type="button" @click="togglePlainTag(t)">{{ t }}</button>
      </div>
      <p v-if="!plainTagChoices.length" class="hint">这个科目年级下还没有现成知识点，可以在下面打一个加上。</p>
      <div class="choice-edit">
        <input v-model="plainTagDraft" placeholder="没有的知识点，打字回车加上" @keydown.enter.prevent="addPlainTag" />
        <button class="btn" type="button" @click="addPlainTag">加上</button>
      </div>
      <input v-model="plain.title" placeholder="题目名字（可空）" />
      <textarea v-model="plain.stem" placeholder="题干。选择题可写成 A. … B. …"></textarea>
      <input v-model="plain.answer" placeholder="答案，例如 B，或 12，或填空文字" />
      <button class="btn primary" type="button" @click="doPlain">加到题库</button>
      <button class="btn ghost" type="button" @click="updateBank">重新读取本机题库</button>
      </details>
    </section>

    <section v-if="tab === 'kids' && meta">
      <h2>已有分组</h2>
      <p class="hint">班级也是分组。点进去看这个组里的学生，再点学生进档案。</p>
      <div class="grid">
        <router-link class="card" v-for="g in groups" :key="g.id" :to="`/admin/accounts/group/${g.id}`">
          <h2>{{ g.label }}</h2>
          <div class="meta">{{ g.is_class ? "班级" : g.parent_label ? "班内分组" : "分组" }} · {{ g.count }} 人</div>
        </router-link>
        <router-link class="card" v-if="ungrouped" to="/admin/accounts/ungrouped">
          <h2>未分组</h2>
          <div class="meta">{{ ungrouped }} 人 · 自己注册的可在这里补真名、加进分组</div>
        </router-link>
      </div>
      <p v-if="!groups.length && !ungrouped" class="hint">还没有分组。先在下面新建一个。</p>

      <h2 style="margin-top:28px">新建分组</h2>
      <p class="hint">班级一定是分组；分组还可以是班里的一小队，或跨班的组。保存后会出现在上面。</p>
      <div class="chips">
        <button class="chip" type="button" :class="{ on: newGroup.mode === 'class' }" @click="newGroup.mode = 'class'">这是一个班级</button>
        <button class="chip" type="button" :class="{ on: newGroup.mode === 'inner' }" @click="newGroup.mode = 'inner'">班内分组</button>
        <button class="chip" type="button" :class="{ on: newGroup.mode === 'loose' }" @click="newGroup.mode = 'loose'">其它分组</button>
      </div>
      <template v-if="newGroup.mode === 'class'">
        <p class="field-label">年级</p>
        <div class="chips">
          <button class="chip" v-for="g in meta.grades" :key="g.id" :class="{ on: newGroup.grade === g.id }" type="button" @click="newGroup.grade = g.id">{{ g.name }}</button>
        </div>
        <input v-model="newGroup.name" placeholder="班名，例如 1班" />
      </template>
      <template v-else-if="newGroup.mode === 'inner'">
        <p class="field-label">挂在哪个班级下面</p>
        <div class="chips">
          <button class="chip" v-for="g in classGroups" :key="g.id" :class="{ on: newGroup.parent_id === g.id }" type="button" @click="newGroup.parent_id = g.id">{{ g.label }}</button>
        </div>
        <p v-if="!classGroups.length" class="hint">还没有班级，先建一个班级分组。</p>
        <input v-model="newGroup.name" placeholder="分组名字，例如 竞赛组" />
      </template>
      <template v-else>
        <input v-model="newGroup.name" placeholder="分组名字" />
      </template>
      <button class="btn primary" type="button" @click="saveGroup">保存分组</button>

      <h2 style="margin-top:28px">代开账号</h2>
      <input v-model="kid.display_name" placeholder="真名，不填则等于登录名（学生看不到）" />
      <input v-model="kid.username" placeholder="登录名，中文也可以，学生用这个登录" maxlength="32" />
      <input v-model="kid.password" placeholder="密码" />
      <p class="field-label">年级</p>
      <div class="chips">
        <button class="chip" v-for="g in meta.grades" :key="g.id" :class="{ on: kid.grade === g.id }" type="button" @click="kid.grade = g.id">{{ g.name }}</button>
      </div>
      <p class="field-label">加入分组（可多选）</p>
      <div class="chips">
        <button class="chip" v-for="g in groups" :key="g.id" :class="{ on: kid.group_ids.includes(g.id) }" type="button" @click="toggleKidGroup(g.id)">{{ g.label }}</button>
      </div>
      <p class="hint">学生也可以自己在 8090 注册。登录名注册后改不了，学生自己页面只看到登录名。真名默认等于登录名，只有老师能改、学生看不到。自己注册的先出现在「未分组」，再补真名、加进分组。一个学生可以同时在多个分组里。</p>
      <button class="btn primary" type="button" @click="addKid">添加学生</button>
    </section>

    <section v-if="tab === 'llm'">
      <p class="hint" v-if="llm.from_env">正在用的地址是启动时定的，这里保存改不了。让装机的人改启动配置。</p>
      <p class="field-label">接口地址</p>
      <input v-model="llm.base_url" placeholder="http://127.0.0.1:8080/v1" />
      <p class="field-label">模型</p>
      <div class="chips" v-if="llm.models.length">
        <button class="chip" v-for="m in llm.models" :key="m" :class="{ on: llm.model === m }" type="button" @click="llm.model = m">{{ m }}</button>
      </div>
      <input v-model="llm.model" placeholder="模型名，可点上面的按钮" />
      <p class="field-label">密钥（本机接口可空）</p>
      <input v-model="llm.api_key" type="password" :placeholder="llm.has_key ? '已保存，不改就留空' : '可空'" autocomplete="off" />
      <p class="field-label">思考</p>
      <div class="chips">
        <button class="chip" type="button" :class="{ on: thinkingMode === 'off' }" @click="setThinking('off')">关掉（更快）</button>
        <button class="chip" type="button" :class="{ on: thinkingMode === 'low' }" @click="setThinking('low')">低推理</button>
        <button class="chip" type="button" :class="{ on: thinkingMode === 'on' }" @click="setThinking('on')">打开</button>
      </div>
      <p class="hint">关掉用 OpenAI 标准参数 reasoning_effort=none，同时带上阿里的 enable_thinking=false。低推理把力度调到 low。评作业一般关掉即可。</p>
      <div class="chips">
        <button class="btn" type="button" @click="loadLlm">读取列表</button>
        <button class="btn" type="button" @click="testLlm">试连一次</button>
        <button class="btn primary" type="button" @click="saveLlm">保存并接入</button>
      </div>
      <p class="hint">只评简答、作文、过程步骤。选择、填空、终值仍在本机对答案。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api";
import { renderMd } from "../markdown";
import { displayZone, fmtInZone, zoneName } from "../timeZone";
import TagScores from "../components/TagScores.vue";
import GenerateQuestions from "../components/GenerateQuestions.vue";

const route = useRoute();
const router = useRouter();
const tab = computed(() => {
  const p = route.path;
  if (p === "/admin/quizzes") return "quizzes";
  if (p === "/admin/assemble") return "assemble";
  if (p === "/admin/bank") return "bank";
  if (p === "/admin/add") return "add";
  if (p === "/admin/llm") return "llm";
  if (p === "/admin/accounts") return "kids";
  return "progress";
});
const pageTitle = computed(() =>
  ({
    progress: "学生",
    quizzes: "测验",
    assemble: "组卷",
    bank: "题库",
    add: "加题",
    kids: "学生账号",
    llm: "模型",
  })[tab.value] || "管理",
);
const pageHint = computed(() =>
  ({
    progress: "点用户卡片看该生成绩。试卷成绩发布前看不到这一次的作答；改判请去「测验」。老师只看见自己科目。",
    quizzes: "组卷后这里会出现本次测验。点进去选分组、设答题时间再发布。没选中的分组看不见试卷。",
    assemble: "按题型和知识点抽题。生成后到「测验」里设答题时间再发布。",
    bank: "按标签选出题目，点进去改题干和答案。保存写到这台电脑，git 更新不会盖掉。",
    add: "按年级和知识点生成练习，检查后入库。也可以导入已有题目。",
    kids: "班级是一种分组；还可以在班里再分组，或建跨班的组。一个学生可以同时在多个分组里。点分组看里面的人，再进学生档案。也可以代开账号。",
    llm: "统一管理出题和判题使用的模型。地址、密钥和思考设置保存后同时生效。",
  })[tab.value] || "",
);
const error = ref("");
const message = ref("");
const meta = ref<any>(null);
const progress = ref<any>(null);
const paste = ref("");
type ImportPart = { stem?: string; points?: number; choices?: { id: string; text: string }[]; answer?: unknown; reference?: unknown };
type ImportItem = { title: string; left_md?: string; parts: ImportPart[] };
const importPreview = ref<{ items: ImportItem[]; source: { kind: "paste"; text: string } | { kind: "file"; file: File } } | null>(null);
const importBusy = ref(false);
let importVersion = 0;
function cancelImport() { importVersion++; importPreview.value = null; }
function formatImportValue(value: unknown) { return value == null || value === "" ? "（无）" : typeof value === "string" ? value : JSON.stringify(value); }
const papers = ref<any[]>([]);
const zoneLabel = computed(() => zoneName(displayZone.value));

function fmtTime(iso?: string | null) {
  return fmtInZone(iso);
}
const bankItems = ref<any[]>([]);
const bankTopics = ref<string[]>([]);
let bankLoading = false;
const bankFilter = reactive({
  subject: null as string | null,
  grade: null as number | null,
  difficulty: null as string | null,
  type: null as string | null,
  tags: [] as string[],
});
const assembleTopics = ref<string[]>([]);
const assemble = reactive({
  subject: "math",
  grade: 7 as number | null,
  difficulty: null as string | null,
  tags: [] as string[],
  kind: "homework",
  duration_minutes: 0,
  sections: [] as { id: string; name: string; types: string[]; heading: string; count: number; available: number }[],
});
const llm = reactive({
  base_url: "http://127.0.0.1:8080/v1",
  model: "",
  api_key: "",
  chat_path: "/chat/completions",
  has_key: false,
  from_env: false,
  enable_thinking: false,
  reasoning_effort: "none",
  models: [] as string[],
});
const thinkingMode = computed(() => {
  if (!llm.enable_thinking) return "off";
  if (llm.reasoning_effort === "low" || llm.reasoning_effort === "minimal") return "low";
  return "on";
});

function setThinking(mode: "off" | "low" | "on") {
  if (mode === "off") {
    llm.enable_thinking = false;
    llm.reasoning_effort = "none";
    return;
  }
  llm.enable_thinking = true;
  llm.reasoning_effort = mode === "low" ? "low" : "";
}
const plain = reactive({
  subject: "math",
  type: "blank",
  title: "",
  stem: "",
  answer: "",
  grade: 7 as number,
  difficulty: "medium",
  tags: [] as string[],
});
const plainTopics = ref<string[]>([]);
const plainTagDraft = ref("");
const kid = reactive({ username: "", password: "", display_name: "", grade: 7 as number | null, group_ids: [] as number[] });
const groups = ref<any[]>([]);
const ungrouped = ref(0);
const classGroups = computed(() => groups.value.filter((g) => g.is_class));
const newGroup = reactive({
  mode: "class" as "class" | "inner" | "loose",
  name: "",
  grade: 7 as number | null,
  parent_id: null as number | null,
});
const plainTagChoices = computed(() => {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const t of [...plain.tags, ...plainTopics.value]) {
    if (!t || seen.has(t)) continue;
    seen.add(t);
    out.push(t);
  }
  return out;
});
const plainTypes = [
  { id: "single", name: "单选" },
  { id: "blank", name: "填空" },
  { id: "numeric", name: "数字" },
  { id: "short", name: "简答" },
];

onMounted(async () => {
  meta.value = await api("/api/parent/meta");
  if (meta.value?.subjects?.length) {
    assemble.subject = meta.value.subjects[0].id;
    plain.subject = meta.value.subjects[0].id;
  }
  initAssembleSections();
  await loadForTab();
});

async function loadForTab() {
  if (tab.value === "quizzes") await loadPapers();
  if (tab.value === "assemble") await loadAssemblePool();
  if (tab.value === "bank") await loadBank();
  if (tab.value === "llm") await loadLlm();
  if (tab.value === "progress") progress.value = await api("/api/parent/progress");
  if (tab.value === "add") await loadPlainTopics();
  if (tab.value === "kids") await loadAccounts();
}

watch(tab, () => {
  error.value = "";
  message.value = "";
  loadForTab();
});

async function loadPapers() {
  const data = (await api("/api/parent/papers")) as { papers: any[] };
  papers.value = data.papers;
}

async function loadBank() {
  if (bankLoading) return;
  bankLoading = true;
  try {
    const params = new URLSearchParams();
    if (bankFilter.subject) params.set("subject", bankFilter.subject);
    if (bankFilter.grade) params.set("grade", String(bankFilter.grade));
    if (bankFilter.difficulty) params.set("difficulty", bankFilter.difficulty);
    if (bankFilter.type) params.set("type", bankFilter.type);
    for (const t of bankFilter.tags) params.append("tags", t);
    const data = (await api(`/api/parent/items?${params}`)) as { items: any[]; topics: string[] };
    bankItems.value = data.items;
    bankTopics.value = data.topics || [];
    const pruned = bankFilter.tags.filter((t) => bankTopics.value.includes(t));
    if (pruned.length !== bankFilter.tags.length) {
      bankFilter.tags.splice(0, bankFilter.tags.length, ...pruned);
    }
  } finally {
    bankLoading = false;
  }
}

async function loadPlainTopics() {
  const params = new URLSearchParams();
  if (plain.subject) params.set("subject", plain.subject);
  if (plain.grade) params.set("grade", String(plain.grade));
  const data = (await api(`/api/parent/items?${params}`)) as { topics: string[] };
  plainTopics.value = data.topics || [];
}

function togglePlainTag(name: string) {
  const i = plain.tags.indexOf(name);
  if (i >= 0) plain.tags.splice(i, 1);
  else plain.tags.push(name);
}

function addPlainTag() {
  const name = plainTagDraft.value.trim();
  if (!name) return;
  if (!plain.tags.includes(name)) plain.tags.push(name);
  plainTagDraft.value = "";
}

watch(
  () => [plain.subject, plain.grade],
  () => {
    if (tab.value === "add") loadPlainTopics();
  },
);

function toggleBankTag(name: string) {
  const i = bankFilter.tags.indexOf(name);
  if (i >= 0) bankFilter.tags.splice(i, 1);
  else bankFilter.tags.push(name);
}

watch(bankFilter, () => {
  if (tab.value === "bank") loadBank();
}, { deep: true });

function initAssembleSections() {
  const rows = meta.value?.paper_sections || [];
  assemble.sections = rows.map((s: any) => ({
    id: s.id,
    name: s.name,
    types: s.types || [],
    heading: s.heading || "",
    count: 0,
    available: 0,
  }));
}

function toggleAssembleTag(name: string) {
  const i = assemble.tags.indexOf(name);
  if (i >= 0) assemble.tags.splice(i, 1);
  else assemble.tags.push(name);
}

async function loadAssemblePool() {
  if (!assemble.subject) return;
  if (!assemble.sections.length) initAssembleSections();
  const params = new URLSearchParams();
  params.set("subject", assemble.subject);
  if (assemble.grade) params.set("grade", String(assemble.grade));
  if (assemble.difficulty) params.set("difficulty", assemble.difficulty);
  const data = (await api(`/api/parent/items?${params}`)) as { items: any[]; topics: string[] };
  assembleTopics.value = data.topics || [];
  const pruned = assemble.tags.filter((t) => assembleTopics.value.includes(t));
  if (pruned.length !== assemble.tags.length) {
    assemble.tags.splice(0, assemble.tags.length, ...pruned);
  }
  const items = data.items || [];
  const tagged = assemble.tags.length
    ? items.filter((it: any) => assemble.tags.every((t) => (it.tags || []).includes(t)))
    : items;
  for (const sec of assemble.sections) {
    const allowed = new Set(sec.types || []);
    sec.available = tagged.filter((it: any) => allowed.has(it.type)).length;
  }
}

watch(
  () => [assemble.subject, assemble.grade, assemble.difficulty, assemble.tags.slice()],
  () => {
    if (tab.value === "assemble") loadAssemblePool();
  },
);

async function doAssemble() {
  error.value = "";
  try {
    const sections = assemble.sections
      .filter((s) => s.count > 0)
      .map((s) => ({ id: s.id, count: s.count, heading: s.heading }));
    const data = (await api("/api/parent/assemble", {
      method: "POST",
      body: JSON.stringify({
        subject: assemble.subject,
        grade: assemble.grade,
        difficulty: assemble.difficulty,
        tags: assemble.tags,
        sections,
        kind: assemble.kind,
        duration_minutes: assemble.duration_minutes,
      }),
    })) as { count: number; id: number };
    message.value = `已生成测验，共 ${data.count} 题。到「测验」里点发布后，学生才能打开。`;
    await loadPapers();
    await router.push("/admin/quizzes");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

function applyLlm(data: any) {
  llm.base_url = data.base_url || "http://127.0.0.1:8080/v1";
  llm.model = data.model || "";
  llm.chat_path = data.chat_path || "/chat/completions";
  llm.has_key = Boolean(data.has_key);
  llm.from_env = Boolean(data.from_env);
  llm.enable_thinking = Boolean(data.enable_thinking);
  llm.reasoning_effort = data.reasoning_effort || (data.enable_thinking ? "" : "none");
  llm.models = data.models || [];
  if (data.reach_error) error.value = data.reach_error;
}

async function loadLlm() {
  error.value = "";
  try {
    applyLlm(await api("/api/parent/llm"));
  } catch (err) {
    error.value = err instanceof Error ? err.message : "读不到模型配置";
  }
}

function llmBody() {
  return {
    base_url: llm.base_url,
    model: llm.model,
    api_key: llm.api_key,
    chat_path: llm.chat_path,
    keep_key: !llm.api_key,
    enable_thinking: llm.enable_thinking,
    reasoning_effort: llm.reasoning_effort || (llm.enable_thinking ? "" : "none"),
  };
}

async function saveLlm() {
  error.value = "";
  message.value = "";
  try {
    const data = (await api("/api/parent/llm", { method: "POST", body: JSON.stringify(llmBody()) })) as any;
    applyLlm(data);
    llm.api_key = "";
    const extra = data.queued ? `已把 ${data.queued} 问待评重新排队。` : "";
    message.value = `已接到 ${data.model}。${extra}`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没保存成";
  }
}

async function testLlm() {
  error.value = "";
  message.value = "";
  try {
    const data = (await api("/api/parent/llm/test", { method: "POST", body: JSON.stringify(llmBody()) })) as { reply?: string };
    message.value = data.reply ? `通了。模型回了：${data.reply}` : "通了。";
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没连上";
  }
}

async function copySkill() {
  const data = (await api("/api/parent/skill")) as { text: string };
  await navigator.clipboard.writeText(data.text);
  message.value = "出题说明已复制，去任何聊天人工智能里粘贴即可。";
}

async function importRequest(source: NonNullable<typeof importPreview.value>["source"], preview: boolean) {
  const suffix = preview ? "?preview=true" : "";
  if (source.kind === "paste") return api(`/api/parent/ingest/paste${suffix}`, { method: "POST", body: JSON.stringify({ text: source.text }) });
  const fd = new FormData();
  fd.append("file", source.file);
  return api(`/api/parent/ingest/file${suffix}`, { method: "POST", body: fd });
}
async function previewImport(source: NonNullable<typeof importPreview.value>["source"]) {
  cancelImport();
  const version = importVersion;
  importBusy.value = true;
  error.value = "";
  try {
    const data = await importRequest(source, true) as { items: ImportItem[]; count: number };
    if (version === importVersion) importPreview.value = { items: data.items, source };
  } catch (err) {
    if (version === importVersion) error.value = err instanceof Error ? err.message : "没认出题目，再试一次";
  } finally { importBusy.value = false; }
}
function doPaste() { void previewImport({ kind: "paste", text: paste.value }); }
function doFile(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (file) void previewImport({ kind: "file", file });
  else cancelImport();
}
async function confirmImport() {
  const preview = importPreview.value;
  if (!preview || importBusy.value) return;
  importBusy.value = true;
  error.value = "";
  try {
    const data = await importRequest(preview.source, false) as { count: number };
    message.value = `已入库 ${data.count} 道题。`;
    if (preview.source.kind === "paste" && paste.value === preview.source.text) paste.value = "";
    cancelImport();
  } catch (err) { error.value = err instanceof Error ? err.message : "没做成"; }
  finally { importBusy.value = false; }
}

async function doPlain() {
  error.value = "";
  try {
    const data = (await api("/api/parent/items/plain", { method: "POST", body: JSON.stringify({ ...plain }) })) as { title: string };
    message.value = `已加上：${data.title}`;
    plain.stem = "";
    plain.answer = "";
    plain.title = "";
    await loadPlainTopics();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

async function updateBank() {
  const data = (await api("/api/parent/bank/update", { method: "POST" })) as { message: string };
  message.value = data.message;
}

async function loadAccounts() {
  const data = (await api("/api/parent/groups")) as { groups: any[]; ungrouped: number };
  groups.value = data.groups || [];
  ungrouped.value = data.ungrouped || 0;
}

function toggleKidGroup(id: number) {
  const i = kid.group_ids.indexOf(id);
  if (i >= 0) kid.group_ids.splice(i, 1);
  else kid.group_ids.push(id);
}

async function saveGroup() {
  error.value = "";
  message.value = "";
  try {
    if (newGroup.mode === "inner" && !newGroup.parent_id) {
      error.value = "班内分组要先选挂在哪个班级下面";
      return;
    }
    if (!newGroup.name.trim()) {
      error.value = "请写分组名字";
      return;
    }
    const body: Record<string, unknown> = { name: newGroup.name };
    if (newGroup.mode === "class") {
      body.kind = "class";
      body.grade = newGroup.grade;
    } else {
      body.kind = "group";
      if (newGroup.mode === "inner") body.parent_id = newGroup.parent_id;
    }
    await api("/api/parent/groups", { method: "POST", body: JSON.stringify(body) });
    message.value = "分组已保存，已出现在上面。";
    newGroup.name = "";
    await loadAccounts();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}

async function addKid() {
  error.value = "";
  try {
    await api("/api/parent/students", { method: "POST", body: JSON.stringify(kid) });
    message.value = "学生账号已建好。";
    kid.username = "";
    kid.password = "";
    kid.display_name = "";
    await loadAccounts();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}
</script>
