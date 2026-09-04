<script lang="ts">
  import { onMount } from 'svelte';
  import ArrowRightIcon from 'phosphor-svelte/lib/ArrowRightIcon';
  import PlusIcon from 'phosphor-svelte/lib/PlusIcon';

  import {
    listBotsApiV1BotsGet,
    listRunsApiV1RunsGet,
    type BotRead,
    type RunRead
  } from '$lib/api/generated';
  import { NAVIGATION_LABEL, NAVIGATION_PATH, botPath, runPath } from '$lib/navigation';
  import RunStatusBadge from '$lib/runs/RunStatusBadge.svelte';
  import { isTerminalRunStatus } from '$lib/runs/status';
  import { formatTime } from '$lib/time';
  import { HOME_COLUMN_LABEL, HOME_COPY, graphRevisionLabel } from './homeCopy';

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
  const activeRunCount = $derived(
    runs.filter(
      (run) => visibleBotIds.has(run.bot_id) && !isTerminalRunStatus(run.status)
    ).length
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

<header class="home-heading page-heading">
  <div>
    <p class="page-kicker">Bot workspace</p>
    <h1>Your trading bots.</h1>
    <p>Configure strategy graphs, control paper-trading limits, and review every run.</p>
  </div>
  <a class="primary-link" href={NAVIGATION_PATH.NEW_BOT}>
    <PlusIcon aria-hidden="true" size={18} weight="bold" />
    {NAVIGATION_LABEL.NEW_BOT}
  </a>
</header>

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
      <div>
        <h2 id="configured-bots-heading">Configured bots</h2>
        <p>Open a bot to change its configuration, edit its graph, or start a run.</p>
      </div>
      <span class="section-count">
        {visibleBots.length} {visibleBots.length === 1 ? 'bot' : 'bots'}
        {activeRunCount > 0 ? `, ${activeRunCount} active` : ''}
      </span>
    </div>

    {#if visibleBots.length === 0}
      <div class="empty-state empty-state-action">
        <div>
          <h3>Create your first bot</h3>
          <p>Set the limits and build the strategy graph in one workspace.</p>
        </div>
        <a class="primary-link" href={NAVIGATION_PATH.NEW_BOT}>
          <PlusIcon aria-hidden="true" size={18} weight="bold" />
          {NAVIGATION_LABEL.NEW_BOT}
        </a>
      </div>
    {:else}
      <div class="bot-list">
        <div class="bot-list-header" aria-hidden="true">
          <span>Bot and markets</span>
          <span>Max order</span>
          <span>Graph</span>
          <span>Latest run</span>
          <span>Updated</span>
          <span></span>
        </div>
        {#each visibleBots as bot (bot.id)}
          {@const recentRun = latestRun(bot.id)}
          <div class="bot-list-item">
            <a
              class="bot-list-row"
              href={botPath(bot.id)}
              aria-label={`Open ${bot.config.name}`}
            >
              <span class="bot-identity" data-label="Bot and markets">
                <strong>{bot.config.name}</strong>
                <small>{marketScope(bot)}</small>
              </span>
              <span class="bot-value" data-label="Max order">{bot.config.max_order_size}</span>
              <span class="bot-value" data-label="Graph">
                {graphRevisionLabel(bot.latest_graph_revision?.revision ?? 1)}
              </span>
              <span class="bot-status" data-label="Latest run">
                {#if recentRun}
                  <RunStatusBadge status={recentRun.status} />
                {:else}
                  <span class="muted-value">Not run yet</span>
                {/if}
              </span>
              <time class="bot-value" data-label="Updated" datetime={bot.updated_at}>
                {formatTime(bot.updated_at)}
              </time>
              <span class="row-arrow" aria-hidden="true">
                <ArrowRightIcon size={18} />
              </span>
            </a>
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <section class="runs-section" aria-labelledby="recent-runs-heading">
    <div class="section-heading">
      <div>
        <h2 id="recent-runs-heading">Recent runs</h2>
        <p>The latest paper runs across your configured bots.</p>
      </div>
      <span class="section-count">{visibleRuns.length} shown</span>
    </div>
    {#if visibleRuns.length === 0}
      <p class="empty-state">Run a configured bot to see its history here.</p>
    {:else}
      <div class="table-wrap">
        <table aria-label="Recent runs">
          <thead>
            <tr>
              <th>{HOME_COLUMN_LABEL.RUN}</th>
              <th>{HOME_COLUMN_LABEL.STATUS}</th>
              <th>{HOME_COLUMN_LABEL.EQUITY}</th>
              <th>{HOME_COLUMN_LABEL.CREATED}</th>
              <th>{HOME_COLUMN_LABEL.ENDED}</th>
            </tr>
          </thead>
          <tbody>
            {#each visibleRuns as run (run.id)}
              <tr>
                <td data-label={HOME_COLUMN_LABEL.RUN}>
                  <a href={runPath(run.id)}>{run.config.name}</a>
                </td>
                <td data-label={HOME_COLUMN_LABEL.STATUS}>
                  <RunStatusBadge status={run.status} />
                </td>
                <td data-label={HOME_COLUMN_LABEL.EQUITY}>
                  {run.latest_equity ?? 'Not available'}
                  {run.equity_status ? ` / ${run.equity_status}` : ''}
                </td>
                <td data-label={HOME_COLUMN_LABEL.CREATED}>{formatTime(run.created_at)}</td>
                <td data-label={HOME_COLUMN_LABEL.ENDED}>{formatTime(run.ended_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
