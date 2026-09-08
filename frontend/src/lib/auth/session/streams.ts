export class PrivateStreams {
  private readonly closers = new Set<() => void>();

  track(close: () => void): () => void {
    let closed = false;
    const closeOnce = () => {
      if (closed) return;
      closed = true;
      this.closers.delete(closeOnce);
      close();
    };
    this.closers.add(closeOnce);
    return closeOnce;
  }

  clear(): void {
    for (const close of this.closers) close();
  }
}
