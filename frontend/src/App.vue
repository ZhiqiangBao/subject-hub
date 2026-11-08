<template>
  <div>
    <header class="topbar" v-if="user">
      <router-link class="brand" :to="isAdmin ? '/admin/students' : '/'">学科 Hub</router-link>
      <template v-if="isAdmin">
        <router-link class="nav" :class="{ on: adminOn('students') }" to="/admin/students">学生</router-link>
        <router-link class="nav" :class="{ on: adminOn('quizzes') }" to="/admin/quizzes">测验</router-link>
        <router-link class="nav" :class="{ on: adminOn('assemble') }" to="/admin/assemble">组卷</router-link>
        <router-link class="nav" :class="{ on: adminOn('bank') }" to="/admin/bank">题库</router-link>
        <router-link class="nav" :class="{ on: adminOn('add') }" to="/admin/add">加题</router-link>
        <router-link class="nav" :class="{ on: adminOn('llm') }" to="/admin/llm">模型</router-link>
        <router-link class="nav" :class="{ on: adminOn('accounts') }" to="/admin/accounts">学生账号</router-link>
      </template>
      <template v-else>
        <router-link class="nav" :class="{ on: studentOn('today') }" to="/">今天做什么</router-link>
        <router-link class="nav" :class="{ on: studentOn('papers') }" to="/papers">试卷</router-link>
        <router-link class="nav" :class="{ on: studentOn('scores') }" to="/scores">我的成绩</router-link>
      </template>
      <span class="spacer"></span>
      <TimezoneBar />
      <span>{{ user.username }}</span>
      <button class="btn ghost" type="button" @click="logout">退出</button>
    </header>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Auth } from "./api";
import TimezoneBar from "./components/TimezoneBar.vue";

const route = useRoute();
const router = useRouter();
const user = ref<{ role: string; username: string } | null>(null);
const isAdmin = computed(() => user.value?.role === "admin" || user.value?.role === "parent");

function adminOn(id: string) {
  const p = route.path;
  if (id === "students") return p === "/admin/students" || p.startsWith("/admin/student/") || p.startsWith("/admin/review/challenge");
  if (id === "quizzes") return p === "/admin/quizzes" || p.startsWith("/admin/quiz/") || p.startsWith("/admin/review/paper");
  if (id === "assemble") return p === "/admin/assemble";
  if (id === "bank") return p === "/admin/bank" || p.startsWith("/admin/item/");
  if (id === "add") return p === "/admin/add";
  if (id === "llm") return p === "/admin/llm";
  if (id === "accounts") return p === "/admin/accounts" || p.startsWith("/admin/accounts/");
  return false;
}

function studentOn(id: string) {
  const p = route.path;
  if (id === "today") return p === "/" || p.startsWith("/play/challenge") || p.startsWith("/challenge/");
  if (id === "papers") return p === "/papers" || p.startsWith("/paper/") || p.startsWith("/play/paper");
  if (id === "scores") return p === "/scores";
  return false;
}

async function load() {
  if (route.path === "/login") {
    user.value = null;
    return;
  }
  try {
    user.value = (await Auth.me()) as typeof user.value;
  } catch {
    user.value = null;
  }
}

watch(() => route.path, load, { immediate: true });

async function logout() {
  // Give the current question's leave guard a chance to save while the
  // session is still valid. A failed save cancels logout as well.
  const failure = await router.push("/login");
  if (!failure) await Auth.logout();
}
</script>
