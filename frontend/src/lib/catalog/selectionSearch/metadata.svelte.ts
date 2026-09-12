import { untrack } from "svelte";
import type { SelectionSource, SelectionSuggestion } from "../selectionSearch";

export class SelectionMetadata {
  items = $state<Record<string, SelectionSuggestion>>({});
  missingIds = $state<string[]>([]);
  failed = $state(false);
  lookupRetryRevision = $state(0);

  constructor(source: () => SelectionSource, selectedIds: () => string[]) {
    const selectedKey = $derived(JSON.stringify(selectedIds()));
    $effect(() => {
      const currentSource = source();
      const ids: string[] = JSON.parse(selectedKey);
      this.lookupRetryRevision;
      const lookupIds = untrack(() => ids.filter((id) => !this.items[id]));
      this.failed = false;
      if (lookupIds.length === 0) return;
      const controller = new AbortController();
      void (async () => {
        try {
          const data = await currentSource.lookup(lookupIds, controller.signal);
          if (controller.signal.aborted) return;
          this.items = { ...this.items, ...Object.fromEntries(data.map((item) => [item.id, item])) };
          this.missingIds = lookupIds.filter((id) => !data.some((item) => item.id === id));
        } catch {
          if (!controller.signal.aborted) this.failed = true;
        }
      })();
      return () => controller.abort();
    });
  }

  remember(item: SelectionSuggestion): void {
    this.items = { ...this.items, [item.id]: item };
  }
}
