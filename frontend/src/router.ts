import { createRouter, createWebHistory } from "vue-router";
import { Auth } from "./api";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", component: () => import("./views/LoginView.vue") },
    { path: "/", component: () => import("./views/HomeView.vue") },
    { path: "/papers", component: () => import("./views/StudentPapersView.vue") },
    { path: "/play/challenge/:runId/:index", component: () => import("./views/PlayerView.vue") },
    { path: "/challenge/:runId/result", component: () => import("./views/ResultView.vue") },
    { path: "/play/paper/:attemptId/:slug", component: () => import("./views/PlayerView.vue") },
    { path: "/paper/:attemptId", component: () => import("./views/PaperView.vue") },
    { path: "/scores", component: () => import("./views/ScoresView.vue") },
    { path: "/admin", redirect: "/admin/students" },
    { path: "/admin/students", component: () => import("./views/ParentView.vue") },
    { path: "/admin/quizzes", component: () => import("./views/ParentView.vue") },
    { path: "/admin/assemble", component: () => import("./views/ParentView.vue") },
    { path: "/admin/bank", component: () => import("./views/ParentView.vue") },
    { path: "/admin/add", component: () => import("./views/ParentView.vue") },
    { path: "/admin/grade", component: () => import("./views/ParentView.vue") },
    { path: "/admin/llm", component: () => import("./views/ParentView.vue") },
    { path: "/admin/accounts", component: () => import("./views/ParentView.vue") },
    { path: "/admin/student/:studentId", component: () => import("./views/AdminStudentView.vue") },
    { path: "/admin/quiz/:paperId", component: () => import("./views/AdminPaperView.vue") },
    { path: "/admin/item/:slug", component: () => import("./views/AdminItemView.vue") },
    { path: "/admin/review/:kind/:id", component: () => import("./views/AdminAttemptView.vue") },
    { path: "/parent", redirect: "/admin" },
  ],
});

router.beforeEach(async (to) => {
  if (to.path === "/login") return true;
  try {
    await Auth.me();
    return true;
  } catch {
    return { path: "/login", query: { next: to.fullPath } };
  }
});

export default router;
