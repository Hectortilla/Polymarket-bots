<script lang="ts">
  import { SERVICE_NAME } from "$lib/serviceIdentity";
  import { hasReportedUsableBook, RUN_GUIDE_COPY } from "$lib/runs/runGuide";
  import RunGuide from "$lib/runs/RunGuide.svelte";
  import { STREAM_CONNECTION_STATE } from "$lib/runs/events";
  import { RunNotFoundError } from "$lib/runs/hydrate";
  import { page } from "$app/state";
  import { PRESENTATION_COPY } from "$lib/presentation";
  import ArrowLeftIcon from "phosphor-svelte/lib/ArrowLeftIcon";
  import { onMount } from "svelte";
  import "./run.css";

  import {
    listBotDefinitionsApiV1BotDefinitionsGet,
    stopRunApiV1RunsRunIdStopPost,
    type GraphNodeCatalog,
    type RunRead,
  } from "$lib/api/generated";
  import NodeGraphInput from "$lib/catalog/NodeGraphInput.svelte";
  import { hasGraphCapability } from "$lib/catalog/graphContracts";
  import DashboardCharts from "$lib/charts/DashboardCharts.svelte";
  import {
    emptyDashboardHistory,
    mergeDurableEvents,
    mergeLiveEvents,
    type DashboardHistory,
  } from "$lib/charts/history";
  import { createLiveDashboardBatcher } from "$lib/charts/liveBatch";
  import { NAVIGATION_LABEL, NAVIGATION_PATH, botPath } from "$lib/navigation";
  import runtimeContract from "$lib/runtimeContract.fixture.json";
  import FailureDetailTooltip from "$lib/runs/FailureDetailTooltip.svelte";
  import RunStatusBadge from "$lib/runs/RunStatusBadge.svelte";
  import { EVENT_KIND, type PersistedDurableEvent } from "$lib/runs/durableEvents";
  import { eventFailureDetail, eventSummary } from "$lib/runs/eventSummary";
  import { loadAndContinueRunDetail, loadOlderRunEvents } from "$lib/runs/hydrate";
  import { RUN_STATUS_PRESENTATION } from "$lib/runs/status";
  import { formatTime } from "$lib/time";
  import { loadedEventsLabel, RUN_DETAIL_COPY, executedRunGraphRevisionLabel, runGraphRevisionLabel } from "./copy";

  let run = $state<RunRead | undefined>();
  let events = $state<PersistedDurableEvent[]>([]);
  let dashboard = $state<DashboardHistory>(emptyDashboardHistory());
  let loading = $state(true);
  let stopping = $state(false);
  let loadingOlderEvents = $state(false);
  let loadedEventPages = 1;
  let nextBeforeEventId = $state<number | null>(null);
  let error = $state("");
  let streamReconnecting = $state(false);
  let executedGraphCatalog = $state<GraphNodeCatalog>();
  let executedGraphCatalogLoading = $state(false);
  let executedGraphCatalogError = $state("");
  let closeStream = () => {};

  const progressEvents = $derived(events.filter((event) => event.kind !== EVENT_KIND.chartSample));
  const statusPresentation = $derived(run ? RUN_STATUS_PRESENTATION[run.status] : undefined);
  const configuredWallets = $derived(run?.config.stream_rules.flatMap((rule) => rule.wallet_addresses ?? []) ?? []);

  onMount(() => {
    let disposed = false;
    const liveBatcher = createLiveDashboardBatcher((liveEvents) => {
      if (!disposed) dashboard = mergeLiveEvents(dashboard, liveEvents);
    });
    const runId = page.params.runId;
    if (!runId) {
      error = RUN_DETAIL_COPY.NOT_FOUND;
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
          if (hydration.run.graph) {
            executedGraphCatalogLoading = true;
            void loadExecutedGraphCatalog(hydration.run.definition_id)
              .then((catalog) => {
                if (!disposed) executedGraphCatalog = catalog;
              })
              .catch(() => {
                if (!disposed) {
                  executedGraphCatalogError = RUN_DETAIL_COPY.GRAPH_LOAD_ERROR;
                }
              })
              .finally(() => {
                if (!disposed) executedGraphCatalogLoading = false;
              });
          }
        }
      },
      appendDurableEvent,
      liveBatcher.push,
      undefined,
      (state) => {
        if (!disposed) streamReconnecting = state === STREAM_CONNECTION_STATE.RECONNECTING;
      },
    )
      .then((close) => {
        if (disposed) close();
        else closeStream = close;
      })
      .catch((caught) => {
        error = caught instanceof RunNotFoundError ? RUN_DETAIL_COPY.NOT_FOUND : RUN_DETAIL_COPY.RUN_LOAD_ERROR;
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
    trimEventWindow();
    dashboard = mergeDurableEvents(dashboard, [event]);
    if (run && event.kind === EVENT_KIND.runLifecycle) {
      run = { ...run, status: event.payload.status };
    }
  }

  function trimEventWindow(): void {
    const capacity = loadedEventPages * runtimeContract.eventPagination.defaultLimit;
    if (events.length <= capacity) return;
    events = events.slice(-capacity);
    nextBeforeEventId = events[0].id;
  }

  async function loadExecutedGraphCatalog(definitionId: string): Promise<GraphNodeCatalog> {
    const response = await listBotDefinitionsApiV1BotDefinitionsGet({
      throwOnError: true,
    });
    const definition = response.data.find((candidate) => candidate.definition_id === definitionId);
    if (!hasGraphCapability(definition)) {
      throw new Error("Executed graph definition is unavailable");
    }
    return definition.graph_catalog;
  }

  async function stopRun(): Promise<void> {
    if (!run || !statusPresentation?.canStop) return;
    stopping = true;
    error = "";
    try {
      const response = await stopRunApiV1RunsRunIdStopPost({
        path: { run_id: run.id },
        throwOnError: true,
      });
      run = response.data;
    } catch {
      error = RUN_DETAIL_COPY.STOP_ERROR;
    } finally {
      stopping = false;
    }
  }

  async function loadOlderEvents(): Promise<void> {
    if (!run || nextBeforeEventId === null || loadingOlderEvents) return;
    loadingOlderEvents = true;
    error = "";
    // Reserve the next page while fetching so streamed events cannot leave a gap
    // between the requested history and the retained window.
    loadedEventPages += 1;
    const beforeEventId = nextBeforeEventId;
    try {
      const older = await loadOlderRunEvents(run.id, beforeEventId);
      // If streaming filled the expanded window already, this page is outside it.
      if (nextBeforeEventId === beforeEventId) {
        events = [...older.events, ...events];
        nextBeforeEventId = older.nextBeforeEventId;
      }
      dashboard = mergeDurableEvents(dashboard, older.events);
    } catch {
      loadedEventPages -= 1;
      error = RUN_DETAIL_COPY.LOAD_ERROR;
    } finally {
      trimEventWindow();
      loadingOlderEvents = false;
    }
  }

  function displayValue(value: unknown): string {
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  }
</script>

<svelte:head>
  <title>{run ? `${run.config.name} | ${SERVICE_NAME}` : `Run detail | ${SERVICE_NAME}`}</title>
</svelte:head>
{#if streamReconnecting}<p role="status" class="notice error">{RUN_DETAIL_COPY.STREAM_RECONNECTING}</p>{/if}

<a class="back-link" href={NAVIGATION_PATH.HOME}>
  <ArrowLeftIcon aria-hidden="true" size={16} />
  {NAVIGATION_LABEL.BACK_TO_BOTS}
</a>

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
      <p class="route-meta">
        {#if run.bot_deleted}
          <span>{RUN_DETAIL_COPY.BOT_DELETED}</span>
        {:else}
          <a href={botPath(run.bot_id)}>{RUN_DETAIL_COPY.BOT_CONFIGURATION}</a>
        {/if}{run.graph_revision ? ` / ${runGraphRevisionLabel(run.graph_revision)}` : ""}
      </p>
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
        {stopping ? RUN_DETAIL_COPY.SENDING : statusPresentation.stopLabel}
      </button>
    {/if}
  </section>

  {#if error}
    <p class="notice error" role="alert">{error}</p>
  {/if}

  {#if run.failure_detail}
    <p class="notice error">{run.failure_detail}</p>
  {/if}

  <RunGuide {run} {events} health={dashboard.streamHealth} reconnecting={streamReconnecting} />

  <section class="detail-grid">
    <article class="detail-section timing-panel">
      <div class="section-heading"><h2>Timing</h2></div>
      <dl>
        <div>
          <dt>Created</dt>
          <dd>{formatTime(run.created_at)}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{formatTime(run.started_at)}</dd>
        </div>
        <div>
          <dt>Heartbeat</dt>
          <dd>{formatTime(run.heartbeat_at)}</dd>
        </div>
        <div>
          <dt>Ended</dt>
          <dd>{formatTime(run.ended_at)}</dd>
        </div>
      </dl>
    </article>

    <article class="detail-section configuration-panel">
      <div class="section-heading"><h2>Immutable configuration</h2></div>
      <dl>
        {#each Object.entries(run.config) as [name, value] (name)}
          <div>
            <dt>{name.replaceAll("_", " ")}</dt>
            <dd>{displayValue(value)}</dd>
          </div>
        {/each}
      </dl>
    </article>
  </section>

  {#if run.graph}
    <section class="historical-graph">
      <div class="section-heading">
        <h2 id="executed-graph-heading">
          {executedRunGraphRevisionLabel(run.graph_revision)}
        </h2>
        <span class="section-count">immutable run snapshot</span>
      </div>
      <p id="executed-graph-description">
        This is the exact bot graph used by this run. Later revisions do not change it.
      </p>
      {#if executedGraphCatalog}
        <NodeGraphInput
          initialGraph={run.graph}
          graphCatalog={executedGraphCatalog}
          labelledby="executed-graph-heading"
          describedby="executed-graph-description"
          readOnly
        />
      {:else if executedGraphCatalogLoading}
        <p class="empty-state" aria-live="polite">Loading executed graph…</p>
      {:else}
        <p class="notice error" role="alert">{executedGraphCatalogError}</p>
      {/if}
    </section>
  {/if}

  <DashboardCharts
    samples={dashboard.samples}
    walletTimelinePoints={dashboard.walletTimelinePoints}
    {configuredWallets}
    terminal={statusPresentation?.terminal ?? false}
  />

  <section class="stream-health-panel" aria-label="Live stream health">
    <div class="section-heading">
      <h2>Stream health</h2>
      <span class:health-stale={dashboard.streamHealth?.book_stale} class="section-count">
        {hasReportedUsableBook(dashboard.streamHealth) ? RUN_GUIDE_COPY.BOOK_REPORTED : RUN_GUIDE_COPY.BOOK_UNAVAILABLE}
      </span>
    </div>
    {#if dashboard.streamHealth}
      <dl class="health-metrics">
        <div>
          <dt>Queue</dt>
          <dd>{dashboard.streamHealth.queue_depth}</dd>
        </div>
        <div>
          <dt>Peak</dt>
          <dd>{dashboard.streamHealth.peak_queue_depth}</dd>
        </div>
        <div>
          <dt>Book lag</dt>
          <dd>
            {dashboard.streamHealth.book_dispatch_lag_ms === null
              ? PRESENTATION_COPY.NOT_AVAILABLE
              : `${dashboard.streamHealth.book_dispatch_lag_ms} ms`}
          </dd>
        </div>
        <div>
          <dt>Books</dt>
          <dd>{dashboard.streamHealth.book_received_count}</dd>
        </div>
        <div>
          <dt>Coalesced</dt>
          <dd>{dashboard.streamHealth.book_coalesced_count}</dd>
        </div>
      </dl>
    {/if}
  </section>

  <section class="progress-section">
    <div class="section-heading">
      <h2>Durable progress</h2>
      <div class="section-actions">
        <span class="section-count">{loadedEventsLabel(progressEvents.length)}</span>
        {#if nextBeforeEventId !== null}
          <button
            class="secondary compact"
            onclick={loadOlderEvents}
            disabled={loadingOlderEvents}
            aria-busy={loadingOlderEvents}
          >
            {loadingOlderEvents ? RUN_DETAIL_COPY.LOADING : RUN_DETAIL_COPY.LOAD_EARLIER}
          </button>
        {/if}
      </div>
    </div>
    {#if progressEvents.length === 0}
      <p class="empty-state">{RUN_DETAIL_COPY.NO_PROGRESS_EVENTS}</p>
    {:else}
      <div class="table-wrap event-table">
        <table aria-label="Durable progress events">
          <thead><tr><th>Time</th><th>Kind</th><th>Detail</th></tr></thead>
          <tbody>
            {#each progressEvents as event (event.id)}
              {@const failureDetail = eventFailureDetail(event, events, run.failure_detail)}
              {@const failureDetailId = `event-failure-detail-${event.id}`}
              <tr
                class:failure-detail-trigger={failureDetail !== null}
                tabindex={failureDetail === null ? undefined : 0}
                aria-describedby={failureDetail === null ? undefined : failureDetailId}
              >
                <td data-label="Time">{formatTime(event.occurred_at)}</td>
                <td data-label="Kind"><span class="event-kind">{event.kind}</span></td>
                <td class="event-detail-cell" class:failure-detail-host={failureDetail !== null} data-label="Detail">
                  {eventSummary(event)}
                  {#if failureDetail}
                    <FailureDetailTooltip id={failureDetailId} detail={failureDetail} />
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}
