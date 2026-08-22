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
  import { loadAndContinueRunDetail } from '$lib/runs/hydrate';
  import {
    RUN_STATUS_PRESENTATION,
    runStatusLabel
  } from '$lib/runs/status';
  import { formatTime } from '$lib/time';

  let run = $state<RunRead | undefined>();
  let events = $state<PersistedDurableEvent[]>([]);
  let loading = $state(true);
  let stopping = $state(false);
  let error = $state('');
  let closeStream = () => {};

  const statusPresentation = $derived(
    run ? RUN_STATUS_PRESENTATION[run.status] : undefined
  );

  onMount(() => {
    let disposed = false;
    const runId = page.params.runId;
    if (!runId) {
      error = 'Run not found.';
      loading = false;
      return;
    }
    void loadAndContinueRunDetail(
      runId,
      (hydration) => {
        if (!disposed) {
          run = hydration.run;
          events = hydration.events;
        }
      },
      appendEvent
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
      closeStream();
    };
  });

  function appendEvent(event: PersistedDurableEvent): void {
    events = [...events, event];
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
        return `${event.payload.order.side} ${event.payload.order.size} · ${event.payload.order.token_id}`;
      case EVENT_KIND.brokerFill:
        return `${event.payload.fill.status} · ${event.payload.fill.filled_size} filled`;
      case EVENT_KIND.brokerFailure:
        return event.payload.error;
      case EVENT_KIND.marketSettlement:
        return `${event.payload.settlement.resolution.market_slug} · ${event.payload.settlement.resolution.winning_outcome}`;
      case EVENT_KIND.portfolioSnapshot:
        return `Cash ${event.payload.cash_usdc} USDC`;
      case EVENT_KIND.walletTimeline:
        return `${event.payload.trade.side} ${event.payload.trade.size} · ${event.payload.trade.wallet}`;
      case EVENT_KIND.streamHealth:
        return `Queue ${event.payload.queue_depth} · ${event.payload.book_received_count} books`;
      case EVENT_KIND.runFailure:
        return event.payload.error;
    }
  }
</script>

<a class="back-link" href="/">← Back to runs</a>

{#if loading}
  <p class="notice">Hydrating run and durable events…</p>
{:else if !run}
  <p class="notice error" role="alert">{error}</p>
{:else}
  <section class="page-heading run-heading">
    <div>
      <p class="eyebrow">{run.definition_id} · v{run.definition_version}</p>
      <h1>{run.config.name}</h1>
      <RunStatusBadge status={run.status} />
    </div>
    {#if statusPresentation?.stopLabel}
      <button onclick={stopRun} disabled={!statusPresentation.canStop || stopping}>
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
    <article class="panel">
      <div class="section-heading"><h2>Timing</h2></div>
      <dl>
        <div><dt>Created</dt><dd>{formatTime(run.created_at)}</dd></div>
        <div><dt>Started</dt><dd>{formatTime(run.started_at)}</dd></div>
        <div><dt>Heartbeat</dt><dd>{formatTime(run.heartbeat_at)}</dd></div>
        <div><dt>Ended</dt><dd>{formatTime(run.ended_at)}</dd></div>
      </dl>
    </article>

    <article class="panel">
      <div class="section-heading"><h2>Immutable configuration</h2></div>
      <dl>
        {#each Object.entries(run.config) as [name, value] (name)}
          <div><dt>{name.replaceAll('_', ' ')}</dt><dd>{displayValue(value)}</dd></div>
        {/each}
      </dl>
    </article>
  </section>

  <section class="chart-placeholder" aria-label="Dashboard chart placeholder">
    <p class="eyebrow">Dashboard charts</p>
    <h2>Live charts arrive in Slice 12E</h2>
    <p>Durable lifecycle, activity, portfolio, order, fill, and stream progress is available below.</p>
  </section>

  <section>
    <div class="section-heading">
      <h2>Durable progress</h2>
      <span>{events.length} events</span>
    </div>
    {#if events.length === 0}
      <p class="empty-state">No durable events yet.</p>
    {:else}
      <div class="table-wrap event-table">
        <table>
          <thead><tr><th>Time</th><th>Kind</th><th>Detail</th></tr></thead>
          <tbody>
            {#each events as event (event.id)}
              <tr>
                <td>{formatTime(event.occurred_at)}</td>
                <td><span class="event-kind">{event.kind}</span></td>
                <td>{eventSummary(event)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
