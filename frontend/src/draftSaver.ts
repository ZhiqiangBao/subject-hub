/** Serializes snapshots so a slow older request cannot overwrite a newer answer. */
export class DraftSaver {
  private revision = 0;
  private savedRevision = 0;
  private pending: Promise<void> | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(private write: () => Promise<void>, private onError: (error: unknown) => void) {}

  get dirty() { return this.revision !== this.savedRevision; }

  changed() {
    this.revision++;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { void this.flush().catch(this.onError); }, 400);
  }

  flush(force = false): Promise<void> {
    clearTimeout(this.timer);
    if (this.pending) return this.pending;
    if (!this.dirty && !force) return Promise.resolve();
    this.pending = (async () => {
      do {
        const revision = this.revision;
        await this.write();
        this.savedRevision = revision;
      } while (this.dirty);
    })().finally(() => { this.pending = undefined; });
    return this.pending;
  }

  dispose() { clearTimeout(this.timer); }
}
