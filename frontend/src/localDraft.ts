/** Local backups are scoped to a user and a specific attempt/item. */
export function draftKey(userId: number, kind: string, context: string, item: string): string {
  return `subject-hub:draft:${JSON.stringify([userId, kind, context, item])}`;
}
export function readDraft(storage: Storage, key: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(storage.getItem(key) || "null");
    return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
  } catch { return null; }
}
export function writeDraft(storage: Storage, key: string, parts: Record<string, unknown>): boolean {
  try { storage.setItem(key, JSON.stringify(parts)); return true; } catch { return false; }
}
export function clearSavedDraft(storage: Storage, key: string, saved: string): void {
  try { if (storage.getItem(key) === saved) storage.removeItem(key); } catch { /* storage unavailable */ }
}
