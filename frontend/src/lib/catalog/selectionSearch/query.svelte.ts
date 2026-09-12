import { resourceLimitDetail } from "$lib/limits/validation";
import type { SelectionSource, SelectionSuggestion } from "../selectionSearch";

const SEARCH_DEBOUNCE_MILLISECONDS = 300;

export class SelectionQuery {
  query = $state("");
  searchRetryRevision = $state(0);
  loading = $state(false);
  searched = $state(false);
  error = $state("");
  results = $state<SelectionSuggestion[]>([]);
  hasMore = $state(false);

  constructor(source: () => SelectionSource) {
    $effect(() => {
      const currentSource = source();
      const text = this.query.trim();
      this.searchRetryRevision;
      this.results = [];
      this.searched = false;
      this.error = "";
      this.hasMore = false;
      this.loading = text.length >= currentSource.limits.minimumQueryLength;
      if (text.length < currentSource.limits.minimumQueryLength) return;
      const controller = new AbortController();
      const timer = setTimeout(async () => {
        try {
          const data = await currentSource.search(text, controller.signal);
          if (controller.signal.aborted) return;
          this.results = data.items;
          this.hasMore = data.has_more;
          this.searched = true;
        } catch (caught) {
          if (!controller.signal.aborted) this.error = resourceLimitDetail(caught) ?? currentSource.copy.SEARCH_ERROR;
        } finally {
          if (!controller.signal.aborted) this.loading = false;
        }
      }, SEARCH_DEBOUNCE_MILLISECONDS);
      return () => {
        clearTimeout(timer);
        controller.abort();
      };
    });
  }
}
