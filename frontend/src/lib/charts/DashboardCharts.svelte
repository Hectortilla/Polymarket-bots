<script lang="ts">
  import { onMount } from 'svelte';
  import type {
    ChartSamplePayload,
    WalletChartPointPayload
  } from '$lib/api/generated';

  import {
    MAX_CHART_HISTORY_POINTS,
    MAX_TIME_ZOOM_LEVEL,
    MIN_TIME_ZOOM_LEVEL,
    INITIAL_TIME_ZOOM_LEVEL,
    DASHBOARD_KEY
  } from './contracts';
  import { DASHBOARD_COPY } from './copy';
  import EquityChart from './EquityChart.svelte';
  import MarketChart from './MarketChart.svelte';
  import WalletChart from './WalletChart.svelte';
  import { chartWindowPoints } from './chartWindow';

  const BASE_WINDOW_POINTS = 180;
  const MIN_WINDOW_POINTS = 12;

  let {
    samples,
    walletTimelinePoints,
    configuredWallets = [],
    terminal = false
  }: {
    samples: ChartSamplePayload[];
    walletTimelinePoints: WalletChartPointPayload[];
    configuredWallets?: string[];
    terminal?: boolean;
  } = $props();
  let view = $state<'market' | 'wallet'>('market');
  let zoom = $state(INITIAL_TIME_ZOOM_LEVEL);
  let panel: HTMLElement;
  let panelInObservationRange = $state(false);
  let chartsActivated = $state(false);
  let renderedSamples = $state<ChartSamplePayload[]>([]);
  let renderedWalletTimelinePoints = $state<WalletChartPointPayload[]>([]);

  const windowPoints = $derived(
    chartWindowPoints(
      BASE_WINDOW_POINTS,
      zoom,
      MIN_WINDOW_POINTS,
      MAX_CHART_HISTORY_POINTS
    )
  );
  const chartSamples = $derived(renderedSamples.slice(-windowPoints));
  const chartTimeRangeMs = $derived.by(() => {
    const chartStartMs = chartSamples[0]?.sampled_at_ms ?? renderedWalletTimelinePoints[0]?.trade_timestamp_ms ?? 0;
    const chartEndMs = chartSamples.at(-1)?.sampled_at_ms ?? renderedWalletTimelinePoints.at(-1)?.trade_timestamp_ms ?? chartStartMs + 1;
    return [chartStartMs, Math.max(chartStartMs + 1, chartEndMs)] as const;
  });
  $effect(() => {
    if (!panelInObservationRange) return;
    renderedSamples = samples;
    renderedWalletTimelinePoints = walletTimelinePoints;
  });

  onMount(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      handleControl(event.key.toLowerCase());
    };
    window.addEventListener('keydown', keydown);
    const visibility = new IntersectionObserver(([entry]) => {
      panelInObservationRange = entry?.isIntersecting ?? false;
      chartsActivated ||= panelInObservationRange;
    }, { rootMargin: '200px 0px' });
    visibility.observe(panel);
    return () => {
      window.removeEventListener('keydown', keydown);
      visibility.disconnect();
    };
  });

  function handleControl(key: string): void {
    if (key === DASHBOARD_KEY.closer) zoom = Math.max(MIN_TIME_ZOOM_LEVEL, zoom - 1);
    else if (key === DASHBOARD_KEY.wider) zoom = Math.min(MAX_TIME_ZOOM_LEVEL, zoom + 1);
    else if (key === DASHBOARD_KEY.reset) zoom = INITIAL_TIME_ZOOM_LEVEL;
    else if (key === DASHBOARD_KEY.view) {
      view = view === 'market' ? 'wallet' : 'market';
    }
  }
</script>

<section bind:this={panel} class="dashboard-panel" aria-label={DASHBOARD_COPY.ARIA_LABEL}>
  <div class="dashboard-toolbar">
    <div>
      <p class="page-kicker">{terminal ? DASHBOARD_COPY.RUN_HISTORY : DASHBOARD_COPY.LIVE}</p>
      <h2>{view === 'market' ? DASHBOARD_COPY.MARKET_PRICES : DASHBOARD_COPY.WALLET_ACTIVITY}</h2>
    </div>
    <div class="dashboard-controls" aria-label={DASHBOARD_COPY.CONTROLS_ARIA_LABEL}>
      <button class:active={view === 'wallet'} onclick={() => handleControl(DASHBOARD_KEY.view)} title={`Keyboard: ${DASHBOARD_KEY.view}`}>{DASHBOARD_KEY.view} · {DASHBOARD_COPY.CONTROL_VIEW}</button>
      <button onclick={() => handleControl(DASHBOARD_KEY.closer)} disabled={zoom === MIN_TIME_ZOOM_LEVEL} title={`Keyboard: ${DASHBOARD_KEY.closer}`}>{DASHBOARD_KEY.closer} · {DASHBOARD_COPY.CONTROL_CLOSER}</button>
      <button onclick={() => handleControl(DASHBOARD_KEY.wider)} disabled={zoom === MAX_TIME_ZOOM_LEVEL} title={`Keyboard: ${DASHBOARD_KEY.wider}`}>{DASHBOARD_KEY.wider} · {DASHBOARD_COPY.CONTROL_WIDER}</button>
      <button onclick={() => handleControl(DASHBOARD_KEY.reset)} disabled={zoom === INITIAL_TIME_ZOOM_LEVEL} title={`Keyboard: ${DASHBOARD_KEY.reset}`}>{DASHBOARD_KEY.reset} · {DASHBOARD_COPY.CONTROL_RESET}</button>
    </div>
  </div>

  {#if !chartsActivated}
    <div class="dashboard-viewport-placeholder" aria-hidden="true"></div>
  {:else if chartSamples.length === 0 && renderedWalletTimelinePoints.length === 0 && configuredWallets.length === 0}
    <p class="chart-empty">
      {terminal
        ? DASHBOARD_COPY.NO_SAMPLES
        : DASHBOARD_COPY.WAITING_FOR_SAMPLE}
    </p>
  {:else}
    <div class="dashboard-grid" data-layout="stacked">
      <div class="primary-chart">
        {#if view === 'market'}
          <MarketChart samples={chartSamples} />
        {:else}
          <WalletChart
            points={renderedWalletTimelinePoints}
            {configuredWallets}
            startMs={chartTimeRangeMs[0]}
            endMs={chartTimeRangeMs[1]}
          />
        {/if}
      </div>
      <div class="equity-chart">
        <div class="chart-label">{DASHBOARD_COPY.EQUITY}</div>
        <EquityChart samples={chartSamples} />
      </div>
    </div>
  {/if}
</section>
