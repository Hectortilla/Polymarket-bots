<script lang="ts">
  import { onMount } from 'svelte';

  import {
    listBotDefinitionsApiV1BotDefinitionsGet,
    listBotsApiV1BotsGet,
    listRunsApiV1RunsGet,
    type BotRead,
    type BotDefinitionDescriptor,
    type RunRead
  } from '$lib/api/generated';
  import RunStatusBadge from '$lib/runs/RunStatusBadge.svelte';
  import { isTerminalRunStatus } from '$lib/runs/status';
  import { formatTime } from '$lib/time';
  import {
    NAVIGATION_LABEL,
    NAVIGATION_PATH,
    botPath,
    launchPath,
    runPath
  } from '$lib/navigation';
  import { HOME_COLUMN_LABEL, HOME_COPY, graphRevisionLabel } from './homeCopy';

  let definitions = $state<BotDefinitionDescriptor[]>([]);
  let runs = $state<RunRead[]>([]);
  let bots = $state<BotRead[]>([]);
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
      const [catalogResponse, botsResponse, runsResponse] = await Promise.all([
        listBotDefinitionsApiV1BotDefinitionsGet({ throwOnError: true }),
        listBotsApiV1BotsGet({ throwOnError: true }),
        listRunsApiV1RunsGet({ throwOnError: true })
      ]);
      definitions = catalogResponse.data;
      bots = botsResponse.data;
      runs = runsResponse.data;
    } catch {
      error = HOME_COPY.LOAD_ERROR;
    } finally {
      loading = false;
    }
  }
</script>

<svelte:head>
  <title>{HOME_COPY.OPERATIONS} | Polybot</title>
</svelte:head>

<section class="page-heading home-heading">
  <div>
    <p class="page-kicker">{HOME_COPY.OPERATIONS}</p>
    <h1>Run bots with a clear view of risk.</h1>
    <p>Configure trusted strategies, start paper runs, and inspect durable progress from one place.</p>
  </div>
  <div class="section-actions">
    <a class="catalog-link" href={NAVIGATION_PATH.GRAPH_TEMPLATES}>{NAVIGATION_LABEL.GRAPH_TEMPLATES}</a>
    <button class="secondary" onclick={loadHome} disabled={loading} aria-busy={loading}>Refresh</button>
  </div>
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
            href={launchPath(definition.definition_id)}
            aria-label={`Configure ${definition.display_name}`}
          >Create saved bot</a>
        </article>
      {/each}
    </div>
  </section>

  <section>
    <div class="section-heading">
      <h2>{HOME_COPY.SAVED_BOTS}</h2>
      <span class="section-count">{bots.length} bots</span>
    </div>
    {#if bots.length === 0}
      <p class="empty-state">{HOME_COPY.NO_SAVED_BOTS}</p>
    {:else}
      <div class="table-wrap">
        <table aria-label={HOME_COPY.SAVED_BOTS}>
          <thead><tr><th>{HOME_COLUMN_LABEL.BOT}</th><th>{HOME_COLUMN_LABEL.DEFINITION}</th><th>{HOME_COLUMN_LABEL.GRAPH}</th><th>{HOME_COLUMN_LABEL.UPDATED}</th></tr></thead>
          <tbody>
            {#each bots as bot (bot.id)}
              <tr>
                <td data-label={HOME_COLUMN_LABEL.BOT}><a href={botPath(bot.id)}>{bot.config.name}</a></td>
                <td data-label={HOME_COLUMN_LABEL.DEFINITION}>{definitionNames.get(bot.definition_id) ?? bot.definition_id}</td>
                <td data-label={HOME_COLUMN_LABEL.GRAPH}>{bot.latest_graph_revision ? graphRevisionLabel(bot.latest_graph_revision.revision) : 'not used'}</td>
                <td data-label={HOME_COLUMN_LABEL.UPDATED}>{formatTime(bot.updated_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
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
          <thead><tr><th>{HOME_COLUMN_LABEL.RUN}</th><th>{HOME_COLUMN_LABEL.DEFINITION}</th><th>{HOME_COLUMN_LABEL.STATUS}</th><th>{HOME_COLUMN_LABEL.EQUITY}</th><th>{HOME_COLUMN_LABEL.CREATED}</th></tr></thead>
          <tbody>
            {#each activeRuns as run (run.id)}
              <tr>
                <td data-label={HOME_COLUMN_LABEL.RUN}><a href={runPath(run.id)}>{run.config.name}</a></td>
                <td data-label={HOME_COLUMN_LABEL.DEFINITION}>{definitionNames.get(run.definition_id) ?? run.definition_id}</td>
                <td data-label={HOME_COLUMN_LABEL.STATUS}><RunStatusBadge status={run.status} /></td>
                <td data-label={HOME_COLUMN_LABEL.EQUITY}>{run.latest_equity ?? '—'}{run.equity_status ? ` / ${run.equity_status}` : ''}</td>
                <td data-label={HOME_COLUMN_LABEL.CREATED}>{formatTime(run.created_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section>
    <div class="section-heading">
      <h2>{HOME_COPY.RECENT_TERMINAL_RUNS}</h2>
      <span class="section-count">{terminalRuns.length} shown</span>
    </div>
    {#if terminalRuns.length === 0}
      <p class="empty-state">No terminal runs yet.</p>
    {:else}
      <div class="table-wrap">
        <table aria-label={HOME_COPY.RECENT_TERMINAL_RUNS}>
          <thead><tr><th>{HOME_COLUMN_LABEL.RUN}</th><th>{HOME_COLUMN_LABEL.DEFINITION}</th><th>{HOME_COLUMN_LABEL.STATUS}</th><th>{HOME_COLUMN_LABEL.EQUITY}</th><th>{HOME_COLUMN_LABEL.ENDED}</th></tr></thead>
          <tbody>
            {#each terminalRuns as run (run.id)}
              <tr>
                <td data-label={HOME_COLUMN_LABEL.RUN}><a href={runPath(run.id)}>{run.config.name}</a></td>
                <td data-label={HOME_COLUMN_LABEL.DEFINITION}>{definitionNames.get(run.definition_id) ?? run.definition_id}</td>
                <td data-label={HOME_COLUMN_LABEL.STATUS}><RunStatusBadge status={run.status} /></td>
                <td data-label={HOME_COLUMN_LABEL.EQUITY}>{run.latest_equity ?? '—'}{run.equity_status ? ` / ${run.equity_status}` : ''}</td>
                <td data-label={HOME_COLUMN_LABEL.ENDED}>{formatTime(run.ended_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
