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
  import EquityChart from './EquityChart.svelte';
  import MarketChart from './MarketChart.svelte';
  import WalletChart from './WalletChart.svelte';

  const BASE_WINDOW_POINTS = 180;
  const MIN_WINDOW_POINTS = 12;
  const WALLET_LANES_PER_PAGE = 6;

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
  let walletPage = $state(0);
  let panel: HTMLElement;
  let visible = $state(false);
  let activated = $state(false);
  let renderedSamples = $state<ChartSamplePayload[]>([]);
  let renderedWalletTimelinePoints = $state<WalletChartPointPayload[]>([]);

  const windowPoints = $derived(
    Math.min(
      MAX_CHART_HISTORY_POINTS,
      Math.max(MIN_WINDOW_POINTS, BASE_WINDOW_POINTS * 2 ** zoom)
    )
  );
  const chartSamples = $derived(renderedSamples.slice(-windowPoints));
  const range = $derived.by(() => {
    const start = chartSamples[0]?.sampled_at_ms ?? renderedWalletTimelinePoints[0]?.trade_timestamp_ms ?? 0;
    const end = chartSamples.at(-1)?.sampled_at_ms ?? renderedWalletTimelinePoints.at(-1)?.trade_timestamp_ms ?? start + 1;
    return [start, Math.max(start + 1, end)] as const;
  });
  const lanes = $derived([
    ...new Set([
      ...configuredWallets,
      ...renderedWalletTimelinePoints.map(({ wallet }) => wallet)
    ])
  ]);
  const maximumWalletPage = $derived(
    Math.max(0, Math.ceil(lanes.length / WALLET_LANES_PER_PAGE) - 1)
  );
  const visibleLanes = $derived(
    lanes.slice(
      walletPage * WALLET_LANES_PER_PAGE,
      (walletPage + 1) * WALLET_LANES_PER_PAGE
    )
  );

  $effect(() => {
    walletPage = Math.min(walletPage, maximumWalletPage);
  });

  $effect(() => {
    if (!visible) return;
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
      visible = entry?.isIntersecting ?? false;
      activated ||= visible;
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
      walletPage = 0;
    } else if (key === DASHBOARD_KEY.nextWalletPage && view === 'wallet') {
      walletPage = Math.min(maximumWalletPage, walletPage + 1);
    } else if (key === DASHBOARD_KEY.previousWalletPage && view === 'wallet') {
      walletPage = Math.max(0, walletPage - 1);
    }
  }
</script>

<section bind:this={panel} class="dashboard-panel" aria-label="Run dashboard">
  <div class="dashboard-toolbar">
    <div>
      <p class="page-kicker">{terminal ? 'Run history' : 'Live dashboard'}</p>
      <h2>{view === 'market' ? 'Market prices' : 'Followed-wallet activity'}</h2>
    </div>
    <div class="dashboard-controls" aria-label="Dashboard controls">
      <button class:active={view === 'wallet'} onclick={() => handleControl(DASHBOARD_KEY.view)} title={`Keyboard: ${DASHBOARD_KEY.view}`}>{DASHBOARD_KEY.view} · view</button>
      <button onclick={() => handleControl(DASHBOARD_KEY.closer)} disabled={zoom === MIN_TIME_ZOOM_LEVEL} title={`Keyboard: ${DASHBOARD_KEY.closer}`}>{DASHBOARD_KEY.closer} · closer</button>
      <button onclick={() => handleControl(DASHBOARD_KEY.wider)} disabled={zoom === MAX_TIME_ZOOM_LEVEL} title={`Keyboard: ${DASHBOARD_KEY.wider}`}>{DASHBOARD_KEY.wider} · wider</button>
      <button onclick={() => handleControl(DASHBOARD_KEY.reset)} disabled={zoom === INITIAL_TIME_ZOOM_LEVEL} title={`Keyboard: ${DASHBOARD_KEY.reset}`}>{DASHBOARD_KEY.reset} · reset</button>
      {#if view === 'wallet'}
        <button onclick={() => handleControl(DASHBOARD_KEY.previousWalletPage)} disabled={walletPage === 0} title={`Keyboard: ${DASHBOARD_KEY.previousWalletPage}`}>{DASHBOARD_KEY.previousWalletPage} · previous</button>
        <button onclick={() => handleControl(DASHBOARD_KEY.nextWalletPage)} disabled={walletPage === maximumWalletPage} title={`Keyboard: ${DASHBOARD_KEY.nextWalletPage}`}>{DASHBOARD_KEY.nextWalletPage} · next</button>
      {/if}
    </div>
  </div>

  {#if !activated}
    <div class="dashboard-viewport-placeholder" aria-hidden="true"></div>
  {:else if chartSamples.length === 0 && renderedWalletTimelinePoints.length === 0 && configuredWallets.length === 0}
    <p class="chart-empty">
      {terminal
        ? 'No dashboard samples were recorded for this run.'
        : 'Waiting for the first dashboard sample.'}
    </p>
  {:else}
    <div class="dashboard-grid" data-layout="stacked">
      <div class="primary-chart">
        {#if view === 'market'}
          <MarketChart samples={chartSamples} />
        {:else if visibleLanes.length}
          <WalletChart
            points={renderedWalletTimelinePoints}
            lanes={visibleLanes}
            startMs={range[0]}
            endMs={range[1]}
          />
        {:else}
          <p class="chart-empty">No followed wallets configured or detected.</p>
        {/if}
      </div>
      <div class="equity-chart">
        <div class="chart-label">Executable equity</div>
        <EquityChart samples={chartSamples} />
      </div>
    </div>
  {/if}
</section>
