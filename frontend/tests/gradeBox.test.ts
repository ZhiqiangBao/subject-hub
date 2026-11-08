// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { createApp, h, nextTick, reactive, type App } from "vue";
const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../src/api", () => ({ api: mock.api }));
import GradeBox from "../src/components/GradeBox.vue";
let app: App | undefined;
afterEach(() => { app?.unmount(); app = undefined; document.body.innerHTML = ""; vi.useRealTimers(); mock.api.mockReset(); });

it("waits for the new reference task even when an old model score exists, preserving the manual score", async () => {
  vi.useFakeTimers();
  const part = reactive({ answer_id: 1, subjective: true, status: "overridden", status_label: "已改判", admin_touched: true,
    admin_score: 4, score: 4, llm_score: 2, llm_comment: "旧参考", comment: "人工评语", max_score: 5, job_state: null as string | null });
  mock.api.mockResolvedValueOnce({ status: "overridden", admin_score: 4, llm_score: 2, job_state: "queued" })
    .mockResolvedValueOnce({ status: "overridden", admin_score: 4, llm_score: 2, job_state: "running" })
    .mockResolvedValueOnce({ status: "overridden", admin_score: 4, llm_score: 3, llm_comment: "新参考", job_state: "done" });
  const host = document.createElement("div"); document.body.appendChild(host);
  app = createApp({ render: () => h(GradeBox, { part }) }); app.mount(host);
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("用模型"));
  expect(button).toBeDefined(); button!.click();
  await vi.waitFor(() => expect(mock.api).toHaveBeenCalledTimes(1));
  expect(part.status).toBe("overridden");
  expect(part.admin_score).toBe(4);
  expect(part.llm_score).toBe(2);
  expect(host.textContent).not.toContain("模型已评好");
  await vi.advanceTimersByTimeAsync(2000); await nextTick();
  expect(mock.api).toHaveBeenCalledWith("/api/parent/answers/1/grade-job");
  expect(host.textContent).not.toContain("模型已评好");
  expect(part.llm_score).toBe(2);
  expect(host.textContent).not.toContain("用模型再评一次");
  await vi.advanceTimersByTimeAsync(2000); await nextTick();
  expect(part.llm_score).toBe(3);
  expect(part.admin_score).toBe(4);
  expect(part.status).toBe("overridden");
  expect(host.textContent).toContain("模型已评好");
});

it("reports configuration errors without discarding prior scores", async () => {
  const part = reactive({ answer_id: 2, subjective: true, status: "overridden", admin_touched: true,
    admin_score: 4, score: 4, llm_score: 2, max_score: 5, job_state: null });
  mock.api.mockRejectedValueOnce(new Error("未配置模型"));
  const host = document.createElement("div"); document.body.appendChild(host);
  app = createApp({ render: () => h(GradeBox, { part }) }); app.mount(host);
  [...host.querySelectorAll("button")].find((b) => b.textContent?.includes("用模型"))!.click();
  await vi.waitFor(() => expect(host.textContent).toContain("请检查模型配置或手动评分"));
  expect(part.admin_score).toBe(4);
  expect(part.llm_score).toBe(2);
});
