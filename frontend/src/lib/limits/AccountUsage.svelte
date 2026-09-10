<script lang="ts">
  import { minutesFromSeconds } from "$lib/time";
  import { ALLOWANCE_COPY } from "./copy";
  import { LIFECYCLE_COPY } from "$lib/lifecycle/copy";
  import InfoIcon from "phosphor-svelte/lib/InfoIcon";
  import { onMount } from "svelte";
  import { readUsage, type AccountUsage } from "$lib/api/generated";

  let usage = $state<AccountUsage>();
  let error = $state("");
  let loading = $state(false);
  let infoHost: HTMLDivElement;
  let infoOpen = $state(false);
  let infoPinned = $state(false);

  function dismissInfo(): void {
    infoOpen = false;
    infoPinned = false;
  }

  function leaveInfo(): void {
    if (!infoPinned && !infoHost.contains(document.activeElement)) infoOpen = false;
  }

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

<svelte:document
  onkeydown={(event) => {
    if (event.key === "Escape") dismissInfo();
  }}
  onpointerdown={(event) => {
    if (event.target instanceof Node && !infoHost?.contains(event.target)) dismissInfo();
  }}
/>

<section aria-label={ALLOWANCE_COPY.HEADING} class="allowance">
  <div class="section-heading">
    <div class="allowance-title" role="group" bind:this={infoHost} onpointerleave={leaveInfo}>
      <h2>{ALLOWANCE_COPY.HEADING}</h2>
      {#if usage && !error}
        <button
          class="allowance-info-button"
          aria-label={ALLOWANCE_COPY.DETAILS}
          aria-describedby={infoOpen ? "allowance-info" : undefined}
          aria-expanded={infoOpen}
          aria-controls="allowance-info"
          onpointerenter={(event) => {
            if (event.pointerType === "mouse") infoOpen = true;
          }}
          onfocus={() => (infoOpen = true)}
          onblur={() => {
            if (!infoPinned) infoOpen = false;
          }}
          onclick={() => {
            infoPinned = !infoPinned;
            infoOpen = infoPinned;
          }}
        >
          <InfoIcon size={18} aria-hidden="true" />
        </button>
        <div class="allowance-info-position" hidden={!infoOpen}>
          <div id="allowance-info" class="allowance-info" role="tooltip">
            <strong>{ALLOWANCE_COPY.DETAILS}</strong>
            <p>
              Runs stop after {minutesFromSeconds(usage.policy.run_duration_seconds)} minutes. Each run supports up to {usage
                .policy.tracked_markets_per_run} tracked markets and
              {usage.policy.followed_wallets_per_run} followed wallets. Queued runs start oldest first when their account
              has a free active slot.
            </p>
            <p>{LIFECYCLE_COPY.HISTORY}</p>
          </div>
        </div>
      {/if}
    </div>
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
    margin: 0;
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 0.82rem;
  }
  .allowance-values span {
    white-space: nowrap;
  }
  .allowance-title {
    position: relative;
    display: flex;
    align-items: center;
    min-width: 0;
    gap: 4px;
  }
  .allowance-info-button {
    flex: none;
    width: 44px;
    height: 44px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text-muted);
  }
  .allowance-info-button:hover,
  .allowance-info-button[aria-expanded="true"] {
    color: var(--text);
    background: var(--surface-raised);
  }
  .allowance-info-position {
    position: absolute;
    z-index: 1;
    top: 100%;
    left: 0;
    width: min(420px, calc(100vw - var(--page-gutter) * 2 - 34px));
    padding-top: 8px;
  }
  .allowance-info {
    padding: 18px 20px;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-surface);
    background: var(--surface-raised);
    box-shadow: 0 12px 28px rgb(0 0 0 / 0.2);
    color: var(--text);
    font-size: 0.82rem;
    line-height: 1.6;
  }
  .allowance-info strong {
    font-weight: 600;
  }
  .allowance-info p {
    margin: 10px 0 0;
    color: var(--text-soft);
  }
  @media (max-width: 600px) {
    .allowance :global(.section-heading) {
      flex-direction: column;
      align-items: flex-start;
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
