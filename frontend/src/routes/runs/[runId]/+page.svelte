<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';

  import {
    stopRunApiV1RunsRunIdStopPost,
    type RunRead
  } from '$lib/api/generated';
  import {
    EVENT_KIND,
    type PersistedDurableEvent
  } from '$lib/runs/durableEvents';
  import RunStatusBadge from '$lib/runs/RunStatusBadge.svelte';
  import DashboardCharts from '$lib/charts/DashboardCharts.svelte';
  import {
    emptyDashboardHistory,
    mergeDurableEvents,
    mergeLiveEvents,
    type DashboardHistory
  } from '$lib/charts/history';
  import { createLiveDashboardBatcher } from '$lib/charts/liveBatch';
  import {
    loadAndContinueRunDetail,
    loadOlderRunEvents
  } from '$lib/runs/hydrate';
  import {
    RUN_STATUS_PRESENTATION,
    runStatusLabel
  } from '$lib/runs/status';
  import { formatTime } from '$lib/time';

  let run = $state<RunRead | undefined>();
  let events = $state<PersistedDurableEvent[]>([]);
  let dashboard = $state<DashboardHistory>(emptyDashboardHistory());
  let loading = $state(true);
  let stopping = $state(false);
  let loadingOlderEvents = $state(false);
  let nextBeforeEventId = $state<number | null>(null);
  let error = $state('');
  let closeStream = () => {};

  const statusPresentation = $derived(
    run ? RUN_STATUS_PRESENTATION[run.status] : undefined
  );
  const configuredWallets = $derived(
    run?.config.stream_rules.flatMap((rule) => rule.wallet_addresses ?? []) ?? []
  );

  onMount(() => {
    let disposed = false;
    const liveBatcher = createLiveDashboardBatcher((liveEvents) => {
      if (!disposed) dashboard = mergeLiveEvents(dashboard, liveEvents);
    });
    const runId = page.params.runId;
    if (!runId) {
      error = 'Run not found.';
      loading = false;
      return liveBatcher.dispose;
    }
    void loadAndContinueRunDetail(
      runId,
      (hydration) => {
        if (!disposed) {
          run = hydration.run;
          events = hydration.events;
          dashboard = mergeDurableEvents(emptyDashboardHistory(), hydration.events);
          nextBeforeEventId = hydration.nextBeforeEventId;
        }
      },
      appendDurableEvent,
      liveBatcher.push
    )
      .then((close) => {
        if (disposed) close();
        else closeStream = close;
      })
      .catch(() => {
        error = 'The run could not be loaded.';
      })
      .finally(() => {
        loading = false;
      });

    return () => {
      disposed = true;
      liveBatcher.dispose();
      closeStream();
    };
  });

  function appendDurableEvent(event: PersistedDurableEvent): void {
    events = [...events, event];
    dashboard = mergeDurableEvents(dashboard, [event]);
    if (run && event.kind === EVENT_KIND.runLifecycle) {
      run = { ...run, status: event.payload.status };
    }
  }

  async function stopRun(): Promise<void> {
    if (!run || !statusPresentation?.canStop) return;
    stopping = true;
    error = '';
    try {
      const response = await stopRunApiV1RunsRunIdStopPost({
        path: { run_id: run.id },
        throwOnError: true
      });
      run = response.data;
    } catch {
      error = 'The stop request could not be sent.';
    } finally {
      stopping = false;
    }
  }

  async function loadOlderEvents(): Promise<void> {
    if (!run || nextBeforeEventId === null || loadingOlderEvents) return;
    loadingOlderEvents = true;
    error = '';
    try {
      const older = await loadOlderRunEvents(run.id, nextBeforeEventId);
      events = [...older.events, ...events];
      dashboard = mergeDurableEvents(dashboard, older.events);
      nextBeforeEventId = older.nextBeforeEventId;
    } catch {
      error = 'Older durable events could not be loaded.';
    } finally {
      loadingOlderEvents = false;
    }
  }

  function displayValue(value: unknown): string {
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  }

  function eventSummary(event: PersistedDurableEvent): string {
    switch (event.kind) {
      case EVENT_KIND.runLifecycle:
        return `Run ${runStatusLabel(event.payload.status)}`;
      case EVENT_KIND.runBootstrap:
        return `${event.payload.phase}: ${event.payload.completed}/${event.payload.total}`;
      case EVENT_KIND.botActivity:
        return event.payload.message;
      case EVENT_KIND.brokerOrder:
        return `${event.payload.order.side} ${event.payload.order.size} / ${event.payload.order.token_id}`;
      case EVENT_KIND.brokerFill:
        return `${event.payload.fill.status} / ${event.payload.fill.filled_size} filled`;
      case EVENT_KIND.brokerFailure:
        return event.payload.error;
      case EVENT_KIND.marketSettlement:
        return `${event.payload.settlement.resolution.market_slug} / ${event.payload.settlement.resolution.winning_outcome}`;
      case EVENT_KIND.portfolioSnapshot:
        return `Cash ${event.payload.cash_usdc} USDC`;
      case EVENT_KIND.walletTimeline:
        return `${event.payload.trade.side} ${event.payload.trade.size} / ${event.payload.trade.wallet}`;
      case EVENT_KIND.streamHealth:
        return `Queue ${event.payload.queue_depth} / ${event.payload.book_received_count} books`;
      case EVENT_KIND.runFailure:
        return event.payload.error;
      case EVENT_KIND.chartSample:
        return event.payload.equity.value === null
          ? `Equity ${event.payload.equity.status}`
          : `Equity ${event.payload.equity.value} USDC / ${event.payload.equity.status}`;
    }
  }
</script>

<svelte:head>
  <title>{run ? `${run.config.name} | Polybot` : 'Run detail | Polybot'}</title>
</svelte:head>

<a class="back-link" href="/">Back to runs</a>

{#if loading}
  <div class="loading-state" aria-live="polite">
    <span class="sr-only">Loading run and durable events</span>
    <div class="skeleton skeleton-heading" aria-hidden="true"></div>
    <div class="skeleton skeleton-line" aria-hidden="true"></div>
    <div class="skeleton skeleton-panel" aria-hidden="true"></div>
  </div>
{:else if !run}
  <p class="notice error" role="alert">{error}</p>
{:else}
  <section class="page-heading run-heading">
    <div>
      <p class="route-meta">{run.definition_id} / v{run.definition_version}</p>
      <div class="run-title-row">
        <h1>{run.config.name}</h1>
        <RunStatusBadge status={run.status} />
      </div>
    </div>
    {#if statusPresentation?.stopLabel}
      <button
        class="danger-action"
        onclick={stopRun}
        disabled={!statusPresentation.canStop || stopping}
        aria-busy={stopping}
      >
        {stopping ? 'Sending…' : statusPresentation.stopLabel}
      </button>
    {/if}
  </section>

  {#if error}
    <p class="notice error" role="alert">{error}</p>
  {/if}

  {#if run.failure_detail}
    <p class="notice error">{run.failure_detail}</p>
  {/if}

  <section class="detail-grid">
    <article class="detail-section timing-panel">
      <div class="section-heading"><h2>Timing</h2></div>
      <dl>
        <div><dt>Created</dt><dd>{formatTime(run.created_at)}</dd></div>
        <div><dt>Started</dt><dd>{formatTime(run.started_at)}</dd></div>
        <div><dt>Heartbeat</dt><dd>{formatTime(run.heartbeat_at)}</dd></div>
        <div><dt>Ended</dt><dd>{formatTime(run.ended_at)}</dd></div>
      </dl>
    </article>

    <article class="detail-section configuration-panel">
      <div class="section-heading"><h2>Immutable configuration</h2></div>
      <dl>
        {#each Object.entries(run.config) as [name, value] (name)}
          <div><dt>{name.replaceAll('_', ' ')}</dt><dd>{displayValue(value)}</dd></div>
        {/each}
      </dl>
    </article>
  </section>

  <DashboardCharts
    samples={dashboard.samples}
    walletTimelinePoints={dashboard.walletTimelinePoints}
    {configuredWallets}
  />

  <section class="stream-health-panel" aria-label="Live stream health">
    <div class="section-heading">
      <h2>Stream health</h2>
      <span class:health-stale={dashboard.streamHealth?.book_stale} class="section-count">
        {dashboard.streamHealth ? (dashboard.streamHealth.book_stale ? 'stale book input' : 'current') : 'awaiting telemetry'}
      </span>
    </div>
    {#if dashboard.streamHealth}
      <dl class="health-metrics">
        <div><dt>Queue</dt><dd>{dashboard.streamHealth.queue_depth}</dd></div>
        <div><dt>Peak</dt><dd>{dashboard.streamHealth.peak_queue_depth}</dd></div>
        <div><dt>Book lag</dt><dd>{dashboard.streamHealth.book_dispatch_lag_ms ?? '—'} ms</dd></div>
        <div><dt>Books</dt><dd>{dashboard.streamHealth.book_received_count}</dd></div>
        <div><dt>Coalesced</dt><dd>{dashboard.streamHealth.book_coalesced_count}</dd></div>
      </dl>
    {/if}
  </section>

  <section class="progress-section">
    <div class="section-heading">
      <h2>Durable progress</h2>
      <div class="section-actions">
        <span class="section-count">{events.length} events loaded</span>
        {#if nextBeforeEventId !== null}
          <button
            class="secondary compact"
            onclick={loadOlderEvents}
            disabled={loadingOlderEvents}
            aria-busy={loadingOlderEvents}
          >
            {loadingOlderEvents ? 'Loading…' : 'Load earlier events'}
          </button>
        {/if}
      </div>
    </div>
    {#if events.length === 0}
      <p class="empty-state">No durable events yet.</p>
    {:else}
      <div class="table-wrap event-table">
        <table aria-label="Durable progress events">
          <thead><tr><th>Time</th><th>Kind</th><th>Detail</th></tr></thead>
          <tbody>
            {#each events as event (event.id)}
              <tr>
                <td data-label="Time">{formatTime(event.occurred_at)}</td>
                <td data-label="Kind"><span class="event-kind">{event.kind}</span></td>
                <td data-label="Detail">{eventSummary(event)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
