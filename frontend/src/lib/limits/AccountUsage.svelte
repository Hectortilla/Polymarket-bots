<script lang="ts">
  import { minutesFromSeconds } from "$lib/time";
  import { ALLOWANCE_COPY } from "./copy";
  import { LIFECYCLE_COPY } from "$lib/lifecycle/copy";
  import { onMount } from "svelte";
  import { readUsage, type AccountUsage } from "$lib/api/generated";

  let usage = $state<AccountUsage>();
  let error = $state("");
  let loading = $state(false);

  async function refresh(): Promise<void> {
    loading = true;
    error = "";
    try {
      usage = (await readUsage({ throwOnError: true })).data;
    } catch {
      error = ALLOWANCE_COPY.UNAVAILABLE;
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void refresh();
  });
</script>

<section aria-label={ALLOWANCE_COPY.HEADING} class="allowance">
  <div class="section-heading">
    <h2>{ALLOWANCE_COPY.HEADING}</h2>
    <button class="secondary" onclick={refresh} disabled={loading}>{ALLOWANCE_COPY.REFRESH}</button>
  </div>
  {#if error}
    <p role="status">{error}</p>
  {:else if usage}
    <p class="allowance-values" aria-live="polite">
      <span>{usage.active_runs} / {usage.policy.active_runs} active</span>
      <span> {usage.queued_runs} / {usage.policy.queued_runs} queued</span>
      <span> {usage.saved_bots} / {usage.policy.saved_bots} bots</span>
      <span> {usage.saved_templates} / {usage.policy.saved_templates} saved templates</span>
    </p>
    <details class="allowance-details">
      <summary>Run limits and history retention</summary>
      <p class="allowance-note">
        Runs stop after {minutesFromSeconds(usage.policy.run_duration_seconds)} minutes. Each run supports up to {usage
          .policy.tracked_markets_per_run} tracked markets and
        {usage.policy.followed_wallets_per_run} followed wallets. Queued runs start oldest first when their account has a
        free active slot.
      </p>
      <p class="allowance-note">{LIFECYCLE_COPY.HISTORY}</p>
    </details>
  {:else}
    <p role="status">Loading allowance usage…</p>
  {/if}
</section>

<style>
  .allowance {
    margin: 0;
    padding: 24px;
    border: 1px solid var(--line);
    background: var(--surface);
  }
  .allowance-values {
    display: flex;
    flex-wrap: wrap;
    gap: 12px 24px;
    margin: 0 0 16px;
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 0.82rem;
  }
  .allowance-values span {
    white-space: nowrap;
  }
  .allowance-details summary {
    min-height: 44px;
    align-content: center;
    color: var(--text-soft);
    font-size: 0.82rem;
    cursor: pointer;
  }
  .allowance-details summary:hover {
    color: var(--text);
  }
  .allowance-note {
    color: var(--text-muted, #737373);
    font-size: 0.875rem;
    max-width: 85ch;
    margin: 8px 0 0;
    line-height: 1.6;
  }
  @media (max-width: 600px) {
    .allowance :global(.section-heading) {
      flex-direction: column;
      gap: 12px;
    }
  }
  @media (max-width: 767px) {
    .allowance {
      padding: 20px 16px;
    }
    .allowance-values {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
    }
  }
</style>
