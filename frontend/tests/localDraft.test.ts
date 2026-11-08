// @vitest-environment jsdom
import { expect, it } from "vitest";
import { clearSavedDraft, draftKey, readDraft, writeDraft } from "../src/localDraft";

it("isolates account and item backups and preserves newer edits during a save", () => {
  localStorage.clear();
  const key = draftKey(1, "paper", "2", "item-a");
  writeDraft(localStorage, key, { a: "old" });
  const old = localStorage.getItem(key)!;
  writeDraft(localStorage, key, { a: "new" });
  clearSavedDraft(localStorage, key, old);
  expect(readDraft(localStorage, key)).toEqual({ a: "new" });
  expect(readDraft(localStorage, draftKey(2, "paper", "2", "item-a"))).toBeNull();
  expect(readDraft(localStorage, draftKey(1, "paper", "2", "item-b"))).toBeNull();
  clearSavedDraft(localStorage, key, localStorage.getItem(key)!);
  expect(readDraft(localStorage, key)).toBeNull();
});
