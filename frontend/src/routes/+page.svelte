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

<section class="page-heading">
  <div>
    <p class="eyebrow">Private · paper only</p>
    <h1>Launch and follow bot runs</h1>
    <p>Choose a trusted definition, configure its paper inputs, and follow durable progress.</p>
  </div>
  <button class="secondary" onclick={loadHome} disabled={loading}>Refresh</button>
</section>

{#if error}
  <p class="notice error" role="alert">{error}</p>
{:else if loading}
  <p class="notice">Loading control plane…</p>
{:else}
  <section>
    <div class="section-heading">
      <h2>Bot catalog</h2>
      <span>{definitions.length} definitions</span>
    </div>
    <div class="catalog-grid">
      {#each definitions as definition (definition.definition_id)}
        <article class="catalog-card">
          <div class="card-meta">
            <span class="tag">{definition.label.replace('_', ' ')}</span>
            <span>v{definition.version}</span>
          </div>
          <h3>{definition.display_name}</h3>
          <p>{definition.description}</p>
          <a class="button-link" href={`/launch/${definition.definition_id}`}>Configure run</a>
        </article>
      {/each}
    </div>
  </section>

  <section>
    <div class="section-heading">
      <h2>Active and queued</h2>
      <span>{activeRuns.length} runs</span>
    </div>
    {#if activeRuns.length === 0}
      <p class="empty-state">No runs are active or queued.</p>
    {:else}
      <div class="table-wrap">
        <table>
          <thead><tr><th>Run</th><th>Definition</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>
            {#each activeRuns as run (run.id)}
              <tr>
                <td><a href={`/runs/${run.id}`}>{run.config.name}</a></td>
                <td>{definitionNames.get(run.definition_id) ?? run.definition_id}</td>
                <td><RunStatusBadge status={run.status} /></td>
                <td>{formatTime(run.created_at)}</td>
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
      <span>{terminalRuns.length} shown</span>
    </div>
    {#if terminalRuns.length === 0}
      <p class="empty-state">No terminal runs yet.</p>
    {:else}
      <div class="table-wrap">
        <table>
          <thead><tr><th>Run</th><th>Definition</th><th>Status</th><th>Ended</th></tr></thead>
          <tbody>
            {#each terminalRuns as run (run.id)}
              <tr>
                <td><a href={`/runs/${run.id}`}>{run.config.name}</a></td>
                <td>{definitionNames.get(run.definition_id) ?? run.definition_id}</td>
                <td><RunStatusBadge status={run.status} /></td>
                <td>{formatTime(run.ended_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
