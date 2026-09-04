<script lang="ts">
  import { onMount } from 'svelte';
  import PlusIcon from 'phosphor-svelte/lib/PlusIcon';

  import {
    listBotsApiV1BotsGet,
    listRunsApiV1RunsGet,
    type BotRead,
    type RunRead
  } from '$lib/api/generated';
  import { NAVIGATION_LABEL, NAVIGATION_PATH, botPath, runPath } from '$lib/navigation';
  import RunStatusBadge from '$lib/runs/RunStatusBadge.svelte';
  import { formatTime } from '$lib/time';
  import {
    HOME_COLUMN_LABEL,
    HOME_COPY,
    botRowLabel,
    graphRevisionLabel,
    runRowLabel
  } from './homeCopy';

  let runs = $state<RunRead[]>([]);
  let bots = $state<BotRead[]>([]);
  let loading = $state(true);
  let error = $state('');

  const visibleBots = $derived(
    bots.filter((bot) => bot.latest_graph_revision !== null && bot.latest_graph_revision !== undefined)
  );
  const visibleBotIds = $derived(new Set(visibleBots.map((bot) => bot.id)));
  const visibleRuns = $derived(
    runs.filter((run) => visibleBotIds.has(run.bot_id)).slice(0, 10)
  );

  onMount(() => {
    void loadHome();
  });

  async function loadHome(): Promise<void> {
    loading = true;
    error = '';
    try {
      const [botsResponse, runsResponse] = await Promise.all([
        listBotsApiV1BotsGet({ throwOnError: true }),
        listRunsApiV1RunsGet({ throwOnError: true })
      ]);
      bots = botsResponse.data;
      runs = runsResponse.data;
    } catch {
      error = HOME_COPY.LOAD_ERROR;
    } finally {
      loading = false;
    }
  }

  function latestRun(botId: string): RunRead | undefined {
    return runs.find((run) => run.bot_id === botId);
  }

  function marketScope(bot: BotRead): string {
    const slugs = [
      ...new Set(bot.config.stream_rules.flatMap((rule) => rule.market_slugs ?? []))
    ];
    if (slugs.length === 0) return 'No markets configured';
    if (slugs.length <= 2) return slugs.join(', ');
    return `${slugs.slice(0, 2).join(', ')} +${slugs.length - 2}`;
  }
</script>

<svelte:head>
  <title>{NAVIGATION_LABEL.BOTS} | Polybot</title>
  <meta
    name="description"
    content="Configure node-based paper bots and inspect their recent runs."
  />
</svelte:head>

<h1 class="sr-only">{NAVIGATION_LABEL.BOTS}</h1>

{#if error}
  <div class="notice-with-action">
    <p class="notice error" role="alert">{error}</p>
    <button class="secondary" onclick={loadHome}>Try again</button>
  </div>
{:else if loading}
  <div class="loading-state" aria-live="polite">
    <span class="sr-only">Loading bots</span>
    <div class="skeleton skeleton-heading" aria-hidden="true"></div>
    <div class="skeleton skeleton-line" aria-hidden="true"></div>
    <div class="skeleton skeleton-panel" aria-hidden="true"></div>
  </div>
{:else}
  <section class="bots-section" aria-labelledby="configured-bots-heading">
    <div class="section-heading">
      <h2 id="configured-bots-heading">{HOME_COPY.CONFIGURED_BOTS}</h2>
    </div>
    <div class="data-list bot-list">
      <div class="data-list-header bot-list-header">
        <span aria-hidden="true">{HOME_COLUMN_LABEL.BOT_AND_MARKETS}</span>
        <span aria-hidden="true">{HOME_COLUMN_LABEL.MAX_ORDER}</span>
        <span aria-hidden="true">{HOME_COLUMN_LABEL.GRAPH}</span>
        <span aria-hidden="true">{HOME_COLUMN_LABEL.LATEST_RUN}</span>
        <span aria-hidden="true">{HOME_COLUMN_LABEL.UPDATED}</span>
        <a class="bot-list-create" href={NAVIGATION_PATH.NEW_BOT}>
          <PlusIcon aria-hidden="true" size={15} />
          {NAVIGATION_LABEL.NEW_BOT}
        </a>
      </div>
      {#if visibleBots.length === 0}
        <p class="empty-state">{HOME_COPY.CREATE_FIRST_BOT}</p>
      {:else}
        {#each visibleBots as bot (bot.id)}
          {@const recentRun = latestRun(bot.id)}
          <div class="bot-list-item">
            <a
              class="data-list-row bot-list-row"
              href={botPath(bot.id)}
              aria-label={botRowLabel(bot.config.name)}
            >
              <span class="bot-identity" data-label={HOME_COLUMN_LABEL.BOT_AND_MARKETS}>
                <strong class="data-list-title">{bot.config.name}</strong>
                <small>{marketScope(bot)}</small>
              </span>
              <span class="data-list-value" data-label={HOME_COLUMN_LABEL.MAX_ORDER}>
                {bot.config.max_order_size}
              </span>
              <span class="data-list-value" data-label={HOME_COLUMN_LABEL.GRAPH}>
                {graphRevisionLabel(bot.latest_graph_revision?.revision ?? 1)}
              </span>
              <span class="bot-status" data-label={HOME_COLUMN_LABEL.LATEST_RUN}>
                {#if recentRun}
                  <RunStatusBadge status={recentRun.status} />
                {:else}
                  <span class="muted-value">{HOME_COPY.NOT_RUN_YET}</span>
                {/if}
              </span>
              <time class="data-list-value" data-label={HOME_COLUMN_LABEL.UPDATED} datetime={bot.updated_at}>
                {formatTime(bot.updated_at)}
              </time>
            </a>
          </div>
        {/each}
      {/if}
    </div>
  </section>

  <section class="runs-section" aria-labelledby="recent-runs-heading">
    <div class="section-heading">
      <h2 id="recent-runs-heading">{HOME_COPY.RECENT_RUNS}</h2>
    </div>
    {#if visibleRuns.length === 0}
      <p class="empty-state">Run a configured bot to see its history here.</p>
    {:else}
      <div class="data-list run-list">
        <div class="data-list-header run-list-header" aria-hidden="true">
          <span>{HOME_COLUMN_LABEL.RUN}</span>
          <span>{HOME_COLUMN_LABEL.STATUS}</span>
          <span>{HOME_COLUMN_LABEL.EQUITY}</span>
          <span>{HOME_COLUMN_LABEL.CREATED}</span>
          <span>{HOME_COLUMN_LABEL.ENDED}</span>
        </div>
        {#each visibleRuns as run (run.id)}
          <a
            class="data-list-row run-list-row"
            href={runPath(run.id)}
            aria-label={runRowLabel(run.config.name, formatTime(run.created_at))}
          >
            <strong class="data-list-title" data-label={HOME_COLUMN_LABEL.RUN}>
              {run.config.name}
            </strong>
            <span data-label={HOME_COLUMN_LABEL.STATUS}>
              <RunStatusBadge status={run.status} />
            </span>
            <span class="data-list-value" data-label={HOME_COLUMN_LABEL.EQUITY}>
              {run.latest_equity ?? 'Not available'}
              {run.equity_status ? ` / ${run.equity_status}` : ''}
            </span>
            <time class="data-list-value" data-label={HOME_COLUMN_LABEL.CREATED} datetime={run.created_at}>
              {formatTime(run.created_at)}
            </time>
            <time class="data-list-value" data-label={HOME_COLUMN_LABEL.ENDED} datetime={run.ended_at ?? undefined}>
              {formatTime(run.ended_at)}
            </time>
          </a>
        {/each}
      </div>
    {/if}
  </section>
{/if}
