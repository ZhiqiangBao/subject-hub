// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { createApp, h, nextTick, type App } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";

const mock = vi.hoisted(() => ({ api: vi.fn(), me: vi.fn() }));
vi.mock("../src/api", () => ({ api: mock.api, Auth: { me: mock.me } }));
import PlayerView from "../src/views/PlayerView.vue";

let app: App | undefined;
afterEach(() => { app?.unmount(); app = undefined; document.body.innerHTML = ""; localStorage.clear(); vi.clearAllMocks(); });

it("saves the current long answer before navigation, blocks failure, and keeps answers in their own items", async () => {
  mock.me.mockResolvedValue({ id: 7 });
  let rejectSave!: (reason: Error) => void;
  const firstSave = new Promise<never>((_, reject) => { rejectSave = reject; });
  const item = (slug: string, value: string, next: string | null) => ({
    slug, title: slug, left_md: "", subject: "chinese", parts: [{ id: "answer", type: "essay" }],
    answers: { answer: { value } }, prev_slug: slug === "b" ? "a" : null, next_slug: next, sheet: [],
  });
  mock.api.mockImplementation((path: string, init?: RequestInit) => {
    if (path.endsWith("/draft")) return firstSave;
    if (path.endsWith("/item/a")) return Promise.resolve(item("a", "", "b"));
    if (path.endsWith("/item/b")) return Promise.resolve(item("b", "原来的第二题", null));
    throw new Error(`Unexpected API call: ${path} ${init?.method || "GET"}`);
  });
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: "/play/paper/:attemptId/:slug", component: PlayerView },
  ] });
  await router.push("/play/paper/42/a");
  await router.isReady();
  const host = document.createElement("div");
  document.body.appendChild(host);
  app = createApp({ render: () => h(RouterView) });
  app.use(router).mount(host);
  await vi.waitFor(() => expect(host.querySelector("textarea")).not.toBeNull());
  const textarea = host.querySelector("textarea")!;
  const longAnswer = "长".repeat(25000);
  textarea.value = longAnswer;
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
  await nextTick();
  const navigation = router.push("/play/paper/42/b");
  await vi.waitFor(() => expect(mock.api.mock.calls.some(([path]) => path.endsWith("/item/a/draft"))).toBe(true));
  const saveCall = mock.api.mock.calls.find(([path]) => path.endsWith("/item/a/draft"))!;
  expect(JSON.parse(saveCall[1].body)).toEqual({ parts: { answer: longAnswer } });
  expect(saveCall[1].keepalive).toBe(false);
  expect(router.currentRoute.value.params.slug).toBe("a");
  expect(mock.api.mock.calls.some(([path]) => path.endsWith("/item/b"))).toBe(false);
  rejectSave(new Error("网络断开"));
  await navigation;
  await vi.waitFor(() => expect(host.textContent).toContain("保存失败"));
  expect(router.currentRoute.value.params.slug).toBe("a");
  expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe(longAnswer);
  expect(localStorage.length).toBe(1);
  mock.api.mockImplementation((path: string) => {
    if (path.endsWith("/item/a/draft")) return Promise.resolve({});
    if (path.endsWith("/item/b")) return Promise.resolve(item("b", "原来的第二题", null));
    throw new Error(`Unexpected API call: ${path}`);
  });
  const retry = [...host.querySelectorAll("button")].find((button) => button.textContent?.includes("重试保存"));
  expect(retry).toBeDefined();
  retry!.click();
  await vi.waitFor(() => expect(host.textContent).toContain("已保存"));
  expect(localStorage.length).toBe(0);
  await router.push("/play/paper/42/b");
  await vi.waitFor(() => expect((host.querySelector("textarea") as HTMLTextAreaElement | null)?.value).toBe("原来的第二题"));
  expect(router.currentRoute.value.params.slug).toBe("b");
  expect(mock.api.mock.calls.filter(([path]) => path.endsWith("/draft")).every(([path]) => path.endsWith("/item/a/draft"))).toBe(true);
});
