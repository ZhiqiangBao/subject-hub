<template>
  <div v-if="item">
    <div class="topbar">
      <strong>{{ title }}</strong>
      <span class="spacer"></span>
      <span v-if="mode === 'paper' && item.timed && !locked">剩余 {{ clock }}</span>
      <span v-if="item.total">{{ (item.index ?? 0) + 1 }} / {{ item.total }}</span>
    </div>
    <div class="player">
      <section class="pane left">
        <div class="md" v-html="renderMd(item.left_md)"></div>
      </section>
      <section class="pane right">
        <SheetNav v-if="mode === 'paper' && sheet.length" :items="sheet" :current="item.slug" @pick="goPaper" />
        <div class="part" v-for="part in item.parts" :key="part.id">
          <div class="md" v-if="part.stem" v-html="renderMd(part.stem)"></div>
          <div v-if="part.type === 'single'">
            <button
              class="choice"
              v-for="c in part.choices"
              :key="c.id"
              type="button"
              :class="{ on: values[part.id] === c.id }"
              :disabled="locked"
              @click="pickSingle(part.id, c.id)"
            >
              {{ c.id }}. <span v-html="renderMd(c.text)"></span>
            </button>
          </div>
          <div v-else-if="part.type === 'multiple'" class="chips">
            <button
              class="chip"
              v-for="c in part.choices"
              :key="c.id"
              type="button"
              :class="{ on: (values[part.id] || []).includes(c.id) }"
              :disabled="locked"
              @click="toggleMulti(part.id, c.id)"
            >
              {{ c.id }}. {{ c.text }}
            </button>
          </div>
          <template v-else-if="part.type === 'blank'">
            <FormulaField
              v-if="showFormula"
              v-model="values[part.id]"
              :subject="item.subject"
              :disabled="locked"
              placeholder="填空。点符号按钮，根号积分用括号包住范围"
              @change="scheduleSave"
            />
            <input
              v-else
              v-model="values[part.id]"
              :disabled="locked"
              placeholder="填空"
              autocomplete="off"
              autocapitalize="off"
              autocorrect="off"
              :spellcheck="false"
              @input="scheduleSave"
            />
          </template>
          <input
            v-else-if="part.type === 'numeric'"
            v-model="values[part.id]"
            :disabled="locked"
            placeholder="填数值，例如 0.5、1/2 或 50%"
            autocomplete="off"
            autocapitalize="off"
            autocorrect="off"
            :spellcheck="false"
            @input="scheduleSave"
          />
          <div v-else>
            <textarea v-model="values[part.id]" :disabled="locked" placeholder="用普通话说就行" @input="scheduleSave"></textarea>
            <div class="chips" v-if="!locked && showFormula">
              <button class="chip" type="button" v-for="sym in symbols" :key="sym" @click="insert(part.id, sym)">{{ sym }}</button>
            </div>
            <div v-if="part.allow_photo && !locked">
              <label class="btn">拍演算纸
                <input type="file" accept="image/*" capture="environment" hidden @change="onPhoto($event, part.id)" />
              </label>
            </div>
            <div v-if="photos[part.id]?.length">
              <img v-for="p in photos[part.id]" :key="p" :src="'/api/uploads/file/' + p" style="max-height:120px;margin:8px 8px 0 0" />
            </div>
          </div>
          <p v-if="showScore(part.id)" class="score" :class="item.answers[part.id].score ? 'good' : 'bad'">
            这问 {{ item.answers[part.id].score }} / {{ part.points }} 分
            <span v-if="item.answers[part.id].comment"> · {{ item.answers[part.id].comment }}</span>
          </p>
          <p v-else-if="item.answers?.[part.id]?.status === 'pending'" class="hint">待评分</p>
        </div>
        <p class="err">{{ error }}</p>
        <div v-if="recoveredDraft" class="card">
          <p>这台设备上有一份尚未确认保存的草稿。恢复后请检查内容，再继续答题。</p>
          <button class="btn" type="button" @click="restoreDraft">恢复草稿</button>
          <button class="btn" type="button" @click="discardDraft">丢弃这份草稿</button>
        </div>
        <p v-if="backupFailed" class="err">无法在这台设备保存本地备份，请保持页面打开并重试保存。</p>
        <p v-if="saveState && !saveFailed" class="hint" role="status">{{ saveState }}</p>
        <template v-if="saveFailed">
          <button class="btn" type="button" @click="retrySave">重试保存</button>
          <button v-if="!backupFailed" class="btn ghost" type="button" @click="leaveWithBackup">保留本机草稿并离开</button>
        </template>
        <p class="hint" v-if="mode === 'paper' && item.section_heading">{{ item.section_heading }}</p>
        <div class="paper-nav" v-if="mode === 'paper'">
          <button class="btn big" type="button" :disabled="!item.prev_slug" @click="goPaper(item.prev_slug)">上一题</button>
          <button class="btn primary big" type="button" :disabled="!item.next_slug" @click="goPaper(item.next_slug)">下一题</button>
        </div>
        <template v-if="mode === 'challenge' && !item.submitted">
          <p class="hint">闯关是一题一交。输入会自动记下。</p>
          <button class="btn primary big" type="button" @click="submitChallenge">提交本题</button>
        </template>
        <button v-else-if="mode === 'challenge'" class="btn primary big" type="button" @click="nextChallenge">下一题</button>
        <router-link v-if="mode === 'paper'" class="btn ghost" :to="'/paper/' + attemptId">答题卡</router-link>
      </section>
    </div>
  </div>
  <p v-else role="status">{{ error || "正在读取题目…" }}</p>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from "vue-router";
import { DraftSaver } from "../draftSaver";
import { api, Auth } from "../api";
import { draftKey, readDraft, writeDraft, clearSavedDraft } from "../localDraft";
import { renderMd } from "../markdown";
import FormulaField from "../components/FormulaField.vue";
import SheetNav from "../components/SheetNav.vue";
import { usesFormulaBar } from "../formulaSymbols";

const symbols = ["²", "³", "₁", "₂", "√", "×", "÷", "°"];
const route = useRoute();
const router = useRouter();
const item = ref<any>(null);
const values = ref<Record<string, any>>({});
const photos = ref<Record<string, string[]>>({});
const error = ref("");
const left = ref<number | null>(null);
const saveFailed = ref(false);
const saveState = ref("");
const recoveredDraft = ref<Record<string, unknown> | null>(null);
const backupFailed = ref(false);
let localKey = "";
let loadedUserId: number | null = null;
let clockTimer: number | undefined;
let jumping = false;
let loadRevision = 0;
let leaveWithoutSync = false;

const mode = computed(() => (route.params.runId ? "challenge" : "paper"));
const attemptId = computed(() => String(route.params.attemptId || ""));
const locked = computed(() => Boolean(item.value?.locked || (mode.value === "challenge" && item.value?.submitted)));
const title = computed(() => item.value?.title || "答题");
const showFormula = computed(() => usesFormulaBar(item.value?.subject));
const sheet = computed(() => (item.value?.sheet || []) as { n: number; slug: string; saved?: boolean }[]);
const autoJump = computed(() => {
  const parts = item.value?.parts || [];
  return mode.value === "paper" && !locked.value && parts.length > 0 && parts.every((p: any) => p.type === "single");
});
const clock = computed(() => {
  const s = left.value ?? 0;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
});

function showScore(partId: string) {
  const ans = item.value?.answers?.[partId];
  return ans && (ans.status === "graded" || ans.status === "overridden") && ans.score != null;
}

function applySheet(next: { n: number; slug: string; saved?: boolean }[] | undefined) {
  if (!item.value || !next) return;
  item.value.sheet = next;
}

function markCurrentSaved() {
  const slug = item.value?.slug;
  if (!slug || !item.value?.sheet) return;
  item.value.sheet = item.value.sheet.map((row: any) => (row.slug === slug ? { ...row, saved: true } : row));
}

async function load() {
  const revision = ++loadRevision;
  item.value = null;
  localKey = "";
  loadedUserId = null;
  saveState.value = "";
  saveFailed.value = false;
  error.value = "";
  const kind = mode.value;
  const context = String(kind === "challenge" ? route.params.runId : route.params.attemptId);
  const key = String(kind === "challenge" ? route.params.index : route.params.slug);
  recoveredDraft.value = null;
  backupFailed.value = false;
  try {
    const [user, loaded] = await Promise.all([
      Auth.me() as Promise<{ id: number }>,
      api(`/api/${kind === "challenge" ? "challenge" : "papers/attempts"}/${context}/item/${encodeURIComponent(key)}`),
    ]);
    if (revision !== loadRevision) return;
    loadedUserId = user.id;
    localKey = draftKey(user.id, kind, context, key);
    item.value = loaded;
    left.value = item.value?.remaining_sec ?? null;
  } catch (err) {
    if (revision === loadRevision) error.value = err instanceof Error ? err.message : "读取失败，请刷新后重试";
    return;
  }
  const next: Record<string, any> = {};
  const ph: Record<string, string[]> = {};
  for (const part of item.value.parts) {
    const ans = item.value.answers?.[part.id];
    next[part.id] = ans?.value ?? (part.type === "multiple" ? [] : "");
    ph[part.id] = ans?.photos || [];
  }
  values.value = next;
  photos.value = ph;
  if (!locked.value) recoveredDraft.value = readDraft(localStorage, localKey);
}

function reportSaveError(err: unknown) {
  saveFailed.value = true;
  error.value = err instanceof Error ? `保存失败：${err.message}` : "保存失败，请重试";
}

const saver = new DraftSaver(async () => {
  saveState.value = "正在保存…";
  await save();
  saveState.value = "已保存";
  if (saveFailed.value) { saveFailed.value = false; error.value = ""; }
}, reportSaveError);
function scheduleSave() {
  if (locked.value) return;
  saveState.value = "等待保存…";
  recoveredDraft.value = null;
  backupFailed.value = !writeDraft(localStorage, localKey, values.value);
  saver.changed();
}
function restoreDraft() {
  if (!recoveredDraft.value) return;
  for (const part of item.value.parts) {
    if (Object.prototype.hasOwnProperty.call(recoveredDraft.value, part.id)) values.value[part.id] = recoveredDraft.value[part.id];
  }
  scheduleSave();
}
function discardDraft() {
  try { localStorage.removeItem(localKey); } catch { backupFailed.value = true; return; }
  recoveredDraft.value = null;
}
async function retrySave() {
  try {
    await saver.flush(true);
    saveFailed.value = false;
    error.value = "";
  } catch (err) { reportSaveError(err); }
}
async function flushBeforeNavigation() {
  if (leaveWithoutSync) return true;
  try {
    await saver.flush();
    saveFailed.value = false;
    return true;
  } catch (err) {
    reportSaveError(err);
    return false;
  }
}
async function leaveWithBackup() {
  if (!writeDraft(localStorage, localKey, values.value)) { backupFailed.value = true; return; }
  leaveWithoutSync = true;
  try { await router.push(mode.value === "paper" ? `/paper/${attemptId.value}` : "/"); }
  finally { leaveWithoutSync = false; }
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (saver.dirty) { event.preventDefault(); event.returnValue = ""; }
}
function saveOnPageHide() { void saver.flush().catch(reportSaveError); }
function saveWhenHidden() {
  if (document.visibilityState === "hidden") void saver.flush().catch(reportSaveError);
}

async function save() {
  const currentUser = await Auth.me() as { id: number };
  if (currentUser.id !== loadedUserId) throw new Error("当前账号已切换，请切回原账号恢复草稿");
  const parts = { ...values.value };
  const saved = JSON.stringify(parts);
  const body = JSON.stringify({ parts });
  // Browsers impose a small body quota on keepalive. Long essays must
  // still be saveable using a normal request.
  const keepalive = new Blob([body]).size < 60000;
  const savedKey = localKey;
  if (mode.value === "challenge") {
    await api(`/api/challenge/${route.params.runId}/item/${route.params.index}/draft`, {
      method: "PUT",
      keepalive, body,
    });
    clearSavedDraft(localStorage, savedKey, saved);
    return;
  }
  const data = (await api(`/api/papers/attempts/${route.params.attemptId}/item/${route.params.slug}/draft`, {
    method: "PUT",
    keepalive, body,
  })) as { sheet?: { n: number; slug: string; saved?: boolean }[] };
  clearSavedDraft(localStorage, savedKey, saved);
  applySheet(data.sheet);
  markCurrentSaved();
}

async function pickSingle(id: string, value: string) {
  if (locked.value || jumping) return;
  values.value[id] = value;
  scheduleSave();
  if (autoJump.value && item.value.parts.every((p: { id: string }) => values.value[p.id] !== "")) {
    jumping = true;
    error.value = "";
    try {
      await saver.flush();
      const slug = item.value?.next_slug;
      if (slug) await router.push(`/play/paper/${attemptId.value}/${encodeURIComponent(slug)}`);
      else await router.push(`/paper/${attemptId.value}`);
    } catch (err) {
      reportSaveError(err);
    } finally {
      jumping = false;
    }
    return;
  }
}

function toggleMulti(id: string, choice: string) {
  if (locked.value) return;
  const cur: string[] = Array.isArray(values.value[id]) ? [...values.value[id]] : [];
  const i = cur.indexOf(choice);
  if (i >= 0) cur.splice(i, 1);
  else cur.push(choice);
  values.value[id] = cur;
  scheduleSave();
}

function insert(id: string, sym: string) {
  values.value[id] = String(values.value[id] || "") + sym;
  scheduleSave();
}

async function onPhoto(ev: Event, partId: string) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const ctx = mode.value === "challenge" ? "challenge" : "paper";
  const ctxId = mode.value === "challenge" ? route.params.runId : route.params.attemptId;
  const slug = item.value.slug;
  const revision = loadRevision;
  try {
    const data = (await fetch(`/api/uploads/${ctx}/${ctxId}/${slug}/${partId}`, {
      method: "POST",
      body: fd,
      credentials: "include",
    }).then(async (res) => {
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || "照片没传上去");
      return j;
    })) as { photos: string[] };
    if (revision === loadRevision) {
      photos.value[partId] = data.photos;
      scheduleSave();
    }
  } catch (err) {
    if (revision === loadRevision) error.value = err instanceof Error ? err.message : "照片没传上去，请重试";
  } finally { input.value = ""; }
}

async function submitChallenge() {
  error.value = "";
  try {
    await saver.flush(true);
    const data = (await api(`/api/challenge/${route.params.runId}/item/${route.params.index}/submit`, {
      method: "POST",
      body: JSON.stringify({ parts: values.value }),
    })) as { done?: boolean; next?: number | null };
    if (data.done) await router.push(`/challenge/${route.params.runId}/result`);
    else item.value = { ...item.value, submitted: true, ...data };
  } catch (err) {
    if (saver.dirty) reportSaveError(err);
    else error.value = err instanceof Error ? err.message : "没做成";
  }
}

async function goPaper(slug: string | null) {
  if (!slug || jumping) return;
  error.value = "";
  // Explicitly moving on from a blank question still records a saved blank.
  if (!locked.value && !recoveredDraft.value) {
    try { await saver.flush(true); } catch (err) { reportSaveError(err); return; }
  }
  await router.push(`/play/paper/${attemptId.value}/${encodeURIComponent(slug)}`);
}

async function nextChallenge() {
  const data = (await api(`/api/challenge/${route.params.runId}`)) as { index: number; total: number; status: string };
  if (data.status === "done" || data.index >= data.total) {
    await router.push(`/challenge/${route.params.runId}/result`);
    return;
  }
  await router.push(`/play/challenge/${route.params.runId}/${data.index}`);
}

async function expirePaper() {
  if (!(await flushBeforeNavigation())) return;
  try {
    await api(`/api/papers/attempts/${attemptId.value}/submit`, { method: "POST" });
  } catch {
    /* 到点由主机收卷；这里失败就回答题卡 */
  }
  await router.push(`/paper/${attemptId.value}`);
}

onBeforeRouteLeave(flushBeforeNavigation);
onBeforeRouteUpdate(flushBeforeNavigation);
watch(() => route.fullPath, load);
onMounted(async () => {
  window.addEventListener("beforeunload", beforeUnload);
  document.addEventListener("visibilitychange", saveWhenHidden);
  window.addEventListener("pagehide", saveOnPageHide);
  await load();
  if (mode.value === "paper" && item.value?.timed && !locked.value) {
    clockTimer = window.setInterval(async () => {
      if (left.value == null) return;
      if (left.value <= 0) {
        window.clearInterval(clockTimer);
        await expirePaper();
        return;
      }
      left.value -= 1;
    }, 1000);
  }
});
onUnmounted(() => {
  loadRevision++;
  saver.dispose();
  window.removeEventListener("beforeunload", beforeUnload);
  document.removeEventListener("visibilitychange", saveWhenHidden);
  window.removeEventListener("pagehide", saveOnPageHide);
  if (clockTimer) window.clearInterval(clockTimer);
});
</script>
