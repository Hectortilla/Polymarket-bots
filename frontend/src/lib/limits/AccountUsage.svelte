<script lang="ts">
  import { ALLOWANCE_COPY } from './copy';
  import { onMount } from 'svelte';
  import { readUsage, type AccountUsage } from '$lib/api/generated';

  let usage = $state<AccountUsage>();
  let error = $state('');
  let loading = $state(false);

  async function refresh(): Promise<void> {
    loading = true;
    error = '';
    try {
      usage = (await readUsage({ throwOnError: true })).data;
    } catch {
      error = ALLOWANCE_COPY.UNAVAILABLE;
    } finally {
      loading = false;
    }
  }

  onMount(() => { void refresh(); });
</script>

<section aria-label={ALLOWANCE_COPY.HEADING} class="allowance">
  <div class="section-heading">
    <h2>{ALLOWANCE_COPY.HEADING}</h2>
    <button class="secondary" onclick={refresh} disabled={loading}>{ALLOWANCE_COPY.REFRESH}</button>
  </div>
  {#if error}
    <p role="status">{error}</p>
  {:else if usage}
    <p aria-live="polite">
      {usage.active_runs} / {usage.policy.active_runs} active ·
      {usage.queued_runs} / {usage.policy.queued_runs} queued ·
      {usage.saved_bots} / {usage.policy.saved_bots} bots ·
      {usage.saved_templates} / {usage.policy.saved_templates} saved templates
    </p>
    <p class="allowance-note">
      Runs stop after {usage.policy.run_duration_seconds / 60} minutes.
      Each run supports up to {usage.policy.tracked_markets_per_run} tracked markets and
      {usage.policy.followed_wallets_per_run} followed wallets.
      Queued runs start oldest first when their account has a free active slot.
    </p>
  {:else}
    <p role="status">Loading allowance usage…</p>
  {/if}
</section>

<style>
  .allowance { margin-block: 1.5rem 2.5rem; }
  .allowance-note { color: var(--text-muted, #737373); font-size: 0.875rem; max-width: 70ch; }
</style>
