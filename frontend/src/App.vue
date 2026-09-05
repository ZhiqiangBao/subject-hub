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
        <router-link class="nav" :class="{ on: adminOn('grade') }" to="/admin/grade">改判</router-link>
        <router-link class="nav" :class="{ on: adminOn('llm') }" to="/admin/llm">模型</router-link>
        <router-link class="nav" :class="{ on: adminOn('accounts') }" to="/admin/accounts">学生账号</router-link>
      </template>
      <template v-else>
        <router-link class="nav" :class="{ on: studentOn('today') }" to="/">今天做什么</router-link>
        <router-link class="nav" :class="{ on: studentOn('papers') }" to="/papers">试卷</router-link>
        <router-link class="nav" :class="{ on: studentOn('scores') }" to="/scores">我的成绩</router-link>
      </template>
      <span class="spacer"></span>
      <span>{{ user.display_name || user.username }}</span>
      <button class="btn ghost" type="button" @click="logout">退出</button>
    </header>
    <router-view />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Auth } from "./api";

const route = useRoute();
const router = useRouter();
const user = ref<{ role: string; username: string; display_name?: string } | null>(null);
const isAdmin = computed(() => user.value?.role === "admin" || user.value?.role === "parent");

function adminOn(id: string) {
  const p = route.path;
  if (id === "students") return p === "/admin/students" || p.startsWith("/admin/student/");
  if (id === "quizzes") return p === "/admin/quizzes" || p.startsWith("/admin/quiz/");
  if (id === "assemble") return p === "/admin/assemble";
  if (id === "bank") return p === "/admin/bank" || p.startsWith("/admin/item/");
  if (id === "add") return p === "/admin/add";
  if (id === "grade") return p === "/admin/grade" || p.startsWith("/admin/review/");
  if (id === "llm") return p === "/admin/llm";
  if (id === "accounts") return p === "/admin/accounts";
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
  await Auth.logout();
  await router.push("/login");
}
</script>
