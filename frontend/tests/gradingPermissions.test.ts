import { expect, it } from "vitest";
import { canOverride, canRegrade } from "../src/gradingPermissions";

it("only offers actions accepted for the grading phase and answer", () => {
  expect(canOverride(false, { answer_id: 1, status: "graded" })).toBe(false);
  expect(canOverride(true, { answer_id: 1, status: "draft" })).toBe(false);
  expect(canOverride(true, { answer_id: null, status: "draft" })).toBe(false);
  expect(canOverride(true, { answer_id: 1, status: "graded" })).toBe(true);
  expect(canRegrade({ subjective: false, status: "graded" })).toBe(false);
  expect(canRegrade({ subjective: true, status: "overridden" })).toBe(true);
  expect(canRegrade({ subjective: true, status: "pending" })).toBe(false);
  expect(canRegrade({ subjective: true, status: "overridden", job_state: "running" })).toBe(false);
  expect(canRegrade({ subjective: true, status: "pending", job_state: "failed" })).toBe(true);
});
