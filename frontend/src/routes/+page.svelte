<script lang="ts">
  import { onMount } from 'svelte';

  import {
    listBotDefinitionsApiV1BotDefinitionsGet,
    listRunsApiV1RunsGet,
    type BotDefinitionDescriptor,
    type RunRead
  } from '$lib/api/generated';
  import RunStatusBadge from '$lib/runs/RunStatusBadge.svelte';
  import { isTerminalRunStatus } from '$lib/runs/status';
  import { formatTime } from '$lib/time';

  let definitions = $state<BotDefinitionDescriptor[]>([]);
  let runs = $state<RunRead[]>([]);
  let loading = $state(true);
  let error = $state('');

  const activeRuns = $derived(
    runs.filter((run) => !isTerminalRunStatus(run.status))
  );
  const terminalRuns = $derived(
    runs.filter((run) => isTerminalRunStatus(run.status)).slice(0, 10)
  );
  const definitionNames = $derived(
    new Map(definitions.map((definition) => [definition.definition_id, definition.display_name]))
  );

  onMount(() => {
    void loadHome();
  });

  async function loadHome(): Promise<void> {
    loading = true;
    error = '';
    try {
      const [catalogResponse, runsResponse] = await Promise.all([
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true }),
        listRunsApiV1RunsGet({ throwOnError: true })
      ]);
      definitions = catalogResponse.data;
      runs = runsResponse.data;
    } catch {
      error = 'The control plane could not be loaded.';
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>Paper operations | Polybot</title>
</svelte:head>

<section class="page-heading home-heading">
  <div>
    <p class="page-kicker">Paper operations</p>
    <h1>Run bots with a clear view of risk.</h1>
    <p>Configure trusted strategies, start paper runs, and inspect durable progress from one place.</p>
  </div>
  <button class="secondary" onclick={loadHome} disabled={loading} aria-busy={loading}>Refresh</button>
</section>

{#if error}
  <p class="notice error" role="alert">{error}</p>
{:else if loading}
  <div class="loading-state" aria-live="polite">
    <span class="sr-only">Loading control plane</span>
    <div class="skeleton skeleton-heading" aria-hidden="true"></div>
    <div class="skeleton skeleton-line" aria-hidden="true"></div>
    <div class="skeleton skeleton-panel" aria-hidden="true"></div>
  </div>
{:else}
  <section>
    <div class="section-heading">
      <h2>Bot catalog</h2>
      <span class="section-count">{definitions.length} definitions</span>
    </div>
    <div class="catalog-grid">
      {#each definitions as definition (definition.definition_id)}
        <article class="catalog-item">
          <div class="catalog-meta">
            <span class="tag">{definition.label.replace('_', ' ')}</span>
          </div>
          <h3>{definition.display_name}</h3>
          <p>{definition.description}</p>
          <a
            class="catalog-link"
            href={`/launch/${definition.definition_id}`}
            aria-label={`Configure ${definition.display_name}`}
          >Configure run</a>
        </article>
      {/each}
    </div>
  </section>

  <section>
    <div class="section-heading">
      <h2>Active and queued</h2>
      <span class="section-count">{activeRuns.length} runs</span>
    </div>
    {#if activeRuns.length === 0}
      <p class="empty-state">No runs are active or queued.</p>
    {:else}
      <div class="table-wrap">
        <table aria-label="Active and queued runs">
          <thead><tr><th>Run</th><th>Definition</th><th>Status</th><th>Equity</th><th>Created</th></tr></thead>
          <tbody>
            {#each activeRuns as run (run.id)}
              <tr>
                <td data-label="Run"><a href={`/runs/${run.id}`}>{run.config.name}</a></td>
                <td data-label="Definition">{definitionNames.get(run.definition_id) ?? run.definition_id}</td>
                <td data-label="Status"><RunStatusBadge status={run.status} /></td>
                <td data-label="Equity">{run.latest_equity ?? '—'}{run.equity_status ? ` / ${run.equity_status}` : ''}</td>
                <td data-label="Created">{formatTime(run.created_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section>
    <div class="section-heading">
      <h2>Recent terminal runs</h2>
      <span class="section-count">{terminalRuns.length} shown</span>
    </div>
    {#if terminalRuns.length === 0}
      <p class="empty-state">No terminal runs yet.</p>
    {:else}
      <div class="table-wrap">
        <table aria-label="Recent terminal runs">
          <thead><tr><th>Run</th><th>Definition</th><th>Status</th><th>Equity</th><th>Ended</th></tr></thead>
          <tbody>
            {#each terminalRuns as run (run.id)}
              <tr>
                <td data-label="Run"><a href={`/runs/${run.id}`}>{run.config.name}</a></td>
                <td data-label="Definition">{definitionNames.get(run.definition_id) ?? run.definition_id}</td>
                <td data-label="Status"><RunStatusBadge status={run.status} /></td>
                <td data-label="Equity">{run.latest_equity ?? '—'}{run.equity_status ? ` / ${run.equity_status}` : ''}</td>
                <td data-label="Ended">{formatTime(run.ended_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
