import { describe, expect, it, vi } from "vitest";
import { DraftSaver } from "../src/draftSaver";

describe("draft saving", () => {
  it("serializes changes made while a request is in flight", async () => {
    let finish!: () => void;
    const first = new Promise<void>((resolve) => { finish = resolve; });
    const write = vi.fn().mockReturnValueOnce(first).mockResolvedValue(undefined);
    const saver = new DraftSaver(write, vi.fn());
    saver.changed();
    const pending = saver.flush();
    saver.changed();
    const navigation = saver.flush();
    expect(write).toHaveBeenCalledTimes(1);
    finish();
    await Promise.all([pending, navigation]);
    expect(write).toHaveBeenCalledTimes(2);
    expect(saver.dirty).toBe(false);
    saver.dispose();
  });
  it("keeps a failed draft dirty for retry", async () => {
    const write = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
    const saver = new DraftSaver(write, vi.fn());
    saver.changed();
    await expect(saver.flush()).rejects.toThrow("offline");
    expect(saver.dirty).toBe(true);
    await saver.flush();
    expect(saver.dirty).toBe(false);
    saver.dispose();
  });
});
