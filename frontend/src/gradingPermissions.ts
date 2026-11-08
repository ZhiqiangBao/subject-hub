export function canOverride(canGrade: boolean, part: { answer_id?: number | null; status?: string }): boolean {
  return Boolean(canGrade && part.answer_id && part.status && part.status !== "draft");
}
export function canRegrade(part: { subjective?: boolean; status?: string; job_state?: string | null }): boolean {
  return Boolean(part.subjective && part.status !== "draft" && part.job_state !== "queued" && part.job_state !== "running" && (part.status !== "pending" || part.job_state === "failed"));
}
