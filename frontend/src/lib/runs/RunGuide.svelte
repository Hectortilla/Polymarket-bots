<script lang="ts">
  import type { RunRead, StreamHealthPayload } from "$lib/api/generated";
  import { EVENT_KIND, type PersistedDurableEvent } from "$lib/runs/durableEvents";
  import { RUN_GUIDE_COPY, runGuidance } from "./runGuide";
  let {
    run,
    events,
    health,
    reconnecting,
  }: { run: RunRead; events: PersistedDurableEvent[]; health: StreamHealthPayload | null; reconnecting: boolean } =
    $props();
  const loadedOrderCount = $derived(events.filter((event) => event.kind === EVENT_KIND.brokerOrder).length);
  const loadedFillCount = $derived(events.filter((event) => event.kind === EVENT_KIND.brokerFill).length);
</script>

<section aria-labelledby="run-guide-heading" class="run-guide">
  <h2 id="run-guide-heading">{RUN_GUIDE_COPY.HEADING}</h2>
  <p aria-live="polite">{runGuidance(run.status, health, reconnecting, loadedOrderCount)}</p>
  <p>{RUN_GUIDE_COPY.LOADED_ORDERS}: {loadedOrderCount} · {RUN_GUIDE_COPY.LOADED_FILLS}: {loadedFillCount}</p>
  <p>{RUN_GUIDE_COPY.BALANCES}</p>
  <p>{RUN_GUIDE_COPY.EVENTS}</p>
</section>

<style>
  .run-guide {
    padding-block: 0;
    margin-block: 0;
  }
  h2 {
    margin-bottom: 12px;
  }
  p {
    margin-bottom: 8px;
    max-width: 85ch;
    font-size: 0.875rem;
  }
  p:last-child {
    margin-bottom: 0;
  }
</style>
