<template>
  <div class="auth-page">
    <form @submit.prevent="submit">
      <h1>学科 Hub</h1>
      <p class="hint" v-if="adminSite">这是主机后台。家长点「全科」，老师点自己的科目。注册后请用答题端口 8090 登录。</p>
      <p class="hint" v-else>用中文登录名注册即可。这个名字会出现在你自己的页面上。注册就是学生账号。管理员请到评测机打开 8091。</p>
      <label>登录名</label>
      <input v-model="username" required maxlength="32" placeholder="中文也可以，例如 张三" />
      <label>密码</label>
      <input v-model="password" type="password" required />
      <template v-if="adminSite && mode === 'register'">
        <p>管哪些科目</p>
        <div class="chips">
          <button class="chip" :class="{ on: allSubjects }" type="button" @click="allSubjects = true; picked = []">全科（家长）</button>
          <button
            class="chip"
            v-for="s in subjectOptions"
            :key="s.id"
            :class="{ on: !allSubjects && picked.includes(s.id) }"
            type="button"
            @click="toggleSubject(s.id)"
          >
            {{ s.name }}
          </button>
        </div>
      </template>
      <p class="err">{{ error }}</p>
      <button class="btn primary" type="submit">{{ mode === "login" ? "登录" : registerLabel }}</button>
      <button class="btn ghost" type="button" @click="mode = mode === 'login' ? 'register' : 'login'">
        {{ mode === "login" ? "没有账号？注册" : "已有账号？登录" }}
      </button>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Auth } from "../api";

const subjectOptions = [
  { id: "chinese", name: "语文" },
  { id: "english", name: "英语" },
  { id: "math", name: "数学" },
  { id: "physics", name: "物理" },
  { id: "chemistry", name: "化学" },
  { id: "biology", name: "生物" },
  { id: "history", name: "历史" },
  { id: "politics", name: "政治" },
];

const router = useRouter();
const route = useRoute();
const adminSite = ref(false);
const mode = ref<"login" | "register">("login");
const username = ref("");
const password = ref("");
const error = ref("");
const allSubjects = ref(true);
const picked = ref<string[]>([]);
const registerLabel = computed(() => (adminSite.value ? "注册管理员" : "注册"));

onMounted(async () => {
  try {
    const status = await Auth.status();
    adminSite.value = status.admin_site;
  } catch {
    adminSite.value = false;
  }
});

function toggleSubject(id: string) {
  allSubjects.value = false;
  picked.value = picked.value.includes(id) ? picked.value.filter((x) => x !== id) : [...picked.value, id];
  if (!picked.value.length) allSubjects.value = true;
}

async function submit() {
  error.value = "";
  try {
    if (mode.value === "login") await Auth.login(username.value, password.value);
    else {
      const subjects = adminSite.value && !allSubjects.value && picked.value.length ? picked.value : ["*"];
      await Auth.register(username.value, password.value, subjects);
    }
    const me = (await Auth.me()) as { role: string };
    const home = me.role === "admin" || me.role === "parent" ? "/admin/students" : "/";
    const next = typeof route.query.next === "string" ? route.query.next : home;
    await router.push(next);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "没做成";
  }
}
</script>
